import re
import requests
import difflib
import random
import json
import time
import datetime
import os
import zipfile
import threading
import concurrent.futures
from flask import flash, redirect, url_for, session, render_template
from plexapi.server import PlexServer
from models import db, CollectionSchedule, SystemLog, Settings, TmdbAlias, TmdbKeywordCache
from presets import PLAYLIST_PRESETS

# --- CONFIGURATION ---
BACKUP_DIR = '/config/backups'
CACHE_FILE = '/config/plex_cache.json'
LOCK_FILE = '/config/cache.lock'
SCANNER_LOG_FILE = '/config/scanner.log'

# --- GLOBAL SHARED STATE ---
RESULTS_CACHE = {}

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# --- SESSION HELPER ---
def get_session_filters():
    """Retrieves filter settings from the current user session."""
    try: min_year = int(session.get('min_year', 0))
    except: min_year = 0
    
    try: min_rating = float(session.get('min_rating', 0))
    except: min_rating = 0
    
    genre = session.get('genre_filter')
    genre_filter = genre if genre and genre != 'all' else None
    
    critic_enabled = session.get('critic_filter') == 'true'
    try: threshold = int(session.get('critic_threshold', 70))
    except: threshold = 70
    
    return min_year, min_rating, genre_filter, critic_enabled, threshold

# --- KEYWORD HELPERS ---

def prefetch_keywords_parallel(items, api_key):
    """
    1. Checks DB for keywords.
    2. Fetches missing ones from API.
    3. Saves to DB and enforces the limit.
    """
    if not items: return

    # 1. Identify what we need
    needed = []
    cached_map = {}
    
    # Get all IDs from the list
    target_ids = [item['id'] for item in items]
    
    # Bulk fetch existing from DB
    try:
        existing = TmdbKeywordCache.query.filter(TmdbKeywordCache.tmdb_id.in_(target_ids)).all()
        for row in existing:
            try: cached_map[row.tmdb_id] = json.loads(row.keywords)
            except: cached_map[row.tmdb_id] = []
    except Exception as e:
        print(f"DB Read Error: {e}")

    # Figure out what is missing
    for item in items:
        if item['id'] not in cached_map:
            needed.append(item)
    
    if not needed:
        return # Everything is already cached!

    # 2. Fetch missing from API (Parallel)
    def fetch_tags(item):
        try:
            # TMDB uses 'keywords' for movies, 'results' for TV keywords
            ep = 'keywords' # Default endpoint suffix
            url = f"https://api.themoviedb.org/3/{item['media_type']}/{item['id']}/keywords?api_key={api_key}"
            
            r = requests.get(url, timeout=2)
            if r.status_code != 200: return None
            
            data = r.json()
            # Handle different JSON structures for Movie vs TV
            raw_tags = data.get('keywords', data.get('results', []))
            tags = [k['name'].lower() for k in raw_tags]
            
            return {'id': item['id'], 'type': item['media_type'], 'tags': tags}
        except:
            return None

    new_entries = []
    # 10 workers to prevent timeouts on large batches
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_tags, needed)
        for res in results:
            if res:
                new_entries.append(res)

    # 3. Save to DB
    if new_entries:
        try:
            # Add new rows
            for entry in new_entries:
                db.session.add(TmdbKeywordCache(
                    tmdb_id=entry['id'],
                    media_type=entry['type'],
                    keywords=json.dumps(entry['tags'])
                ))
            
            # Prune if over limit
            s = Settings.query.first()
            limit = s.keyword_cache_size or 2000
            
            total = TmdbKeywordCache.query.count()
            if total > limit:
                # Delete oldest entries to maintain limit
                excess = total - limit
                # Find the IDs of the oldest rows
                subq = db.session.query(TmdbKeywordCache.id).order_by(TmdbKeywordCache.timestamp.asc()).limit(excess).subquery()
                # Delete them
                TmdbKeywordCache.query.filter(TmdbKeywordCache.id.in_(subq)).delete(synchronize_session=False)

            db.session.commit()
        except Exception as e:
            print(f"Cache Save Error: {e}")
            db.session.rollback()

def item_matches_keywords(item, target_keywords):
    # If no keywords selected, everything passes
    if not target_keywords: return True
    
    # 0. PREPARE SEARCH TERMS
    search_terms = {t.lower() for t in target_keywords}
    
    # 1. FAST CHECK: Title & Overview
    text_blob = (item.get('title', '') + ' ' + item.get('name', '') + ' ' + item.get('overview', '')).lower()
    for term in search_terms:
        if term in text_blob: return True
            
    # 2. DEEP CHECK: Database
    # We query the local DB for this specific item's tags
    try:
        entry = TmdbKeywordCache.query.filter_by(tmdb_id=item['id']).first()
        api_tags = json.loads(entry.keywords) if entry else []
    except:
        api_tags = []
    
    for term in search_terms:
        for tag in api_tags:
            if term in tag: return True
                
    return False
    
# --- LOGGING HELPER ---
def write_log(level, module, message):
    try:
        s = Settings.query.first()
        if s and (s.logging_enabled or level == 'ERROR'):
            log = SystemLog(level=level, category=module, message=str(message))
            db.session.add(log)
            db.session.commit()
            
            if log.id % 20 == 0: 
                limit_mb = s.max_log_size if s.max_log_size is not None else 5
                if limit_mb <= 0:
                    return
                
                count = SystemLog.query.count()
                estimated_size_mb = (count * 200) / (1024 * 1024)
                
                if estimated_size_mb > limit_mb:
                    to_delete = int(count * 0.1)
                    oldest = SystemLog.query.order_by(SystemLog.timestamp.asc()).limit(to_delete).all()
                    for o in oldest:
                        db.session.delete(o)
                    db.session.commit()
                    db.session.add(SystemLog(level="WARN", category="System", message=f"Logs exceeded {limit_mb}MB. Pruned {to_delete} oldest entries."))
                    db.session.commit()
    except Exception as e:
        print(f"Logging Failed: {e}")

def write_scanner_log(message):
    """Writes to a local file, rotating if it exceeds the size limit."""
    try:
        # Local import to avoid circular dependency
        from models import Settings
        s = Settings.query.first()
        limit_mb = s.scanner_log_size if s and s.scanner_log_size is not None else 10
        limit_bytes = limit_mb * 1024 * 1024

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{timestamp}] {message}\n"

        if os.path.exists(SCANNER_LOG_FILE):
            if os.path.getsize(SCANNER_LOG_FILE) > limit_bytes:
                try:
                    bak = SCANNER_LOG_FILE + ".bak"
                    if os.path.exists(bak): os.remove(bak)
                    os.rename(SCANNER_LOG_FILE, bak)
                except: pass

        with open(SCANNER_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
            
    except Exception as e:
        print(f"Scanner Log Error: {e}")

def read_scanner_log(lines=100):
    """Reads the last N lines of the scanner log."""
    if not os.path.exists(SCANNER_LOG_FILE):
        return "No scanner logs found yet."
    try:
        with open(SCANNER_LOG_FILE, 'r', encoding='utf-8') as f:
            content = f.readlines()
            return "".join(content[-lines:])
    except: return "Error reading logs."

def normalize_title(title):
    if not title:
        return ""
    
    # 1. Handle Stylized Characters (Leet Speak / Symbols)
    t = str(title).lower()
    replacements = {
        '¢': 'c', '$': 's', '@': 'a', '&': 'and', 
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
        'ñ': 'n', 'ç': 'c'
    }
    
    for char, rep in replacements.items():
        t = t.replace(char, rep)
    
    # 2. Standard Alphanumeric Strip
    return re.sub(r'[^a-z0-9]', '', t)

# --- ALIAS HELPERS ---
def get_tmdb_aliases(tmdb_id, media_type, settings):
    try:
        cached = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=media_type).first()
        if cached:
            return json.loads(cached.aliases)
    except:
        pass

    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/alternative_titles?api_key={settings.tmdb_key}"
        data = requests.get(url, timeout=3).json()
        
        key = 'titles' if 'titles' in data else 'results'
        aliases = [normalize_title(x['title']) for x in data.get(key, [])]
        
        try:
            # Note: Storing aliases is optional in V1.1 as we mainly check ID presence
            pass 
        except: 
            pass
            
        return aliases
    except:
        return []

def sync_remote_aliases():
    return True, "Started in background"

def run_alias_scan(app_obj):
    write_scanner_log("--- Starting Alias Scan ---")
    
    with app_obj.app_context():
        s = Settings.query.first()
        if not s or not s.scanner_enabled:
            write_scanner_log("Scanner disabled or no settings. Aborting.")
            return

        cache_path = CACHE_FILE
        if not os.path.exists(cache_path):
            write_scanner_log("No Plex Cache found. Please run Sync Engine first.")
            return

        try:
            with open(cache_path, 'r') as f:
                # Cache format is now a LIST of strings based on latest refresh_plex_cache
                owned_titles = json.load(f)
        except: return

        # Map Titles -> TMDB IDs
        existing_plex_titles = set([row.plex_title for row in TmdbAlias.query.with_entities(TmdbAlias.plex_title).all()])
        to_scan = [t for t in owned_titles if t not in existing_plex_titles]
        
        total = len(to_scan)
        if total == 0:
            write_scanner_log("All items already indexed. Sleeping.")
            # FIX: Update timestamp so we don't loop forever
            s.last_alias_scan = int(time.time())
            db.session.commit()
            return

        batch_size = s.scanner_batch or 50
        current_batch = to_scan[:batch_size]
        
        write_scanner_log(f"Found {total} unindexed items. Processing batch of {batch_size}...")

        processed = 0
        
        for title in current_batch:
            try:
                # 1. Search Movie
                search_url = f"https://api.themoviedb.org/3/search/movie?api_key={s.tmdb_key}&query={title}"
                r = requests.get(search_url).json()
                
                tmdb_id = None
                media_type = 'movie'
                hit = None
                
                if r.get('results'):
                    hit = r['results'][0]
                    tmdb_id = hit['id']
                
                if not tmdb_id:
                    # 2. Search TV
                    search_url = f"https://api.themoviedb.org/3/search/tv?api_key={s.tmdb_key}&query={title}"
                    r = requests.get(search_url).json()
                    if r.get('results'):
                        hit = r['results'][0]
                        tmdb_id = hit['id']
                        media_type = 'tv'
                        
                if tmdb_id and hit:
                    # Store Main Entry
                    main_entry = TmdbAlias(
                        tmdb_id=tmdb_id, media_type=media_type, 
                        plex_title=title, original_title=normalize_title(hit.get('title', hit.get('name'))),
                        match_year=0
                    )
                    db.session.add(main_entry)
                else:
                    # Not found, store dummy
                    dummy = TmdbAlias(tmdb_id=-1, media_type='unknown', plex_title=title)
                    db.session.add(dummy)
                
                processed += 1
                if processed % 10 == 0: db.session.commit()
                time.sleep(0.2)
                
            except Exception as e:
                print(f"Scan Error on {title}: {e}")
        
        s.last_alias_scan = int(time.time())
        db.session.commit()
        write_scanner_log(f"Batch complete. Processed {processed} items.")

# --- LOCK & CACHE ---
def is_system_locked():
    return os.path.exists(LOCK_FILE)

def set_system_lock(status_msg="Busy"):
    try:
        with open(LOCK_FILE, 'w') as f:
            json.dump({'stage': status_msg}, f)
        return True
    except:
        return False

def remove_system_lock():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except:
            pass

def get_lock_status():
    if not os.path.exists(LOCK_FILE):
        return {'running': False}
    try:
        with open(LOCK_FILE, 'r') as f:
            data = json.load(f)
            return {'running': True, 'progress': data.get('stage', 'Busy')}
    except:
        return {'running': True, 'progress': 'Unknown'}

def refresh_plex_cache(app_obj):
    # Pass app_obj so we can create a context to read DB settings
    if is_system_locked():
        return False, "System is busy. Please wait."

    print("--- STARTING PLEX CACHE REFRESH ---")
    
    # Create App Context to access Database
    with app_obj.app_context():
        settings = Settings.query.first()
        if not settings or not settings.plex_url:
            return False, "Plex not configured."

        write_log("INFO", "Cache", "Started background cache refresh.")
        set_system_lock("Refreshing Plex Cache...") 
        start_time = time.time()
        
        try:
            plex = PlexServer(settings.plex_url, settings.plex_token)
            cache_data = set() # Use set for titles

            # Loop through libraries
            sections = plex.library.sections()
            
            for section in sections:
                if section.type not in ['movie', 'show']:
                    continue
                
                set_system_lock(f"Scanning {section.title}...")
                
                for item in section.all():
                    try:
                        # Normalize Title
                        norm_title = normalize_title(item.title)
                        cache_data.add(norm_title)

                        if hasattr(item, 'originalTitle') and item.originalTitle:
                            norm_orig = normalize_title(item.originalTitle)
                            cache_data.add(norm_orig)
                            
                    except Exception as e:
                        continue

            duration = round(time.time() - start_time, 2)
            
            # Save as List
            with open(CACHE_FILE, 'w') as f:
                json.dump(list(cache_data), f)
                
            msg = f"Cache rebuilt in {duration}s. Indexed {len(cache_data)} titles."
            print(f"--- {msg} ---")
            write_log("SUCCESS", "Cache", msg)
            return True, msg
            
        except Exception as e:
            print(f"Cache Refresh Failed: {e}")
            write_log("ERROR", "Cache", f"Refresh Failed: {str(e)}")
            return False, str(e)
        finally:
            remove_system_lock()

def get_plex_cache(settings):
    if not os.path.exists(CACHE_FILE):
        return []
    
    try:
        with open(CACHE_FILE, 'r') as f:
            content = json.load(f)
            # Handle legacy format where content might be dict
            if isinstance(content, dict) and 'data' in content:
                # Legacy format was data: { title: {...} } keys
                return list(content['data'].keys())
            return content # Should be list
    except:
        return []

# --- CORE SYNC ---
def run_collection_logic(settings, preset, key):
    # 1. CHECK LOCK (Prevents double-clicking)
    if is_system_locked(): return False, "System busy."
    
    # 2. SET LOCK
    set_system_lock(f"Syncing {preset.get('title', 'Collection')}...")
    write_log("INFO", "Sync", f"Starting Sync: {key}")

    try:
        plex = PlexServer(settings.plex_url, settings.plex_token)
        params = preset['tmdb_params'].copy()
        params['api_key'] = settings.tmdb_key
        tmdb_items = []

        # --- 1. DETERMINE RULES ---
        category = preset.get('category', '')
        is_trending = 'Trending' in category or 'Trending' in preset.get('title', '')
        
        max_pages = 1 if is_trending else 50
        
        user_mode = preset.get('sync_mode', 'append')
        mode = 'sync' if is_trending else user_mode

        # --- 2. FETCH CANDIDATES ---
        if 'with_collection_id' in params:
            col_id = params.pop('with_collection_id')
            url = f"https://api.themoviedb.org/3/collection/{col_id}?api_key={settings.tmdb_key}&language=en-US"
            data = requests.get(url).json()
            tmdb_items = data.get('parts', [])
        else:
            url = f"https://api.themoviedb.org/3/discover/{preset['media_type']}"
            def fetch_page(p):
                try:
                    p_params = params.copy()
                    p_params['page'] = p
                    return requests.get(url, params=p_params, timeout=3).json().get('results', [])
                except: return []

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                results = executor.map(fetch_page, range(1, max_pages + 1))
                for page_items in results:
                    if page_items: tmdb_items.extend(page_items)

        if not tmdb_items: 
            return False, "No items found on TMDB."

        # --- 3. OPTIMIZED MATCHING (The Futureproof Fix) ---
        # A. Load "Dumb" Text Matches (Backup Cache)
        owned_titles = set(get_plex_cache(settings)) 
        
        # B. Load "Smart" ID Matches (Alias DB)
        # We check the database to see which IDs you definitely own
        id_map = {}
        try:
            rows = TmdbAlias.query.with_entities(TmdbAlias.tmdb_id, TmdbAlias.plex_title).all()
            for r in rows:
                id_map[r.tmdb_id] = r.plex_title
        except: pass

        potential_matches = []
        for item in tmdb_items:
            # 1. Check ID (Perfect Match)
            if item['id'] in id_map:
                # We found the ID in your DB! Save the Real Plex Title to use later.
                item['mapped_plex_title'] = id_map[item['id']]
                potential_matches.append(item)
                continue
            
            # 2. Check Title (Fuzzy Fallback)
            # Only runs if the background scanner missed the item
            norm_title = normalize_title(item.get('title', item.get('name')))
            if norm_title in owned_titles:
                potential_matches.append(item)

        # --- 4. VERIFY WITH PLEX ---
        target_type = 'movie' if preset['media_type'] == 'movie' else 'show'
        target_lib = next((s for s in plex.library.sections() if s.type == target_type), None)
        if not target_lib: 
            return False, f"No library found for {preset['media_type']}"

        found_items = []
        if potential_matches:
            for item in potential_matches:
                # USE THE MAPPED TITLE IF AVAILABLE
                # This ensures we search for "Star Wars Episode IV" (which works) 
                # instead of just "Star Wars" (which fails).
                search_title = item.get('mapped_plex_title', item.get('title', item.get('name')))
                year = int((item.get('release_date') or item.get('first_air_date') or '0000')[:4])
                
                try:
                    results = target_lib.search(search_title)
                    for r in results:
                        # If mapped by ID, it's a guaranteed match.
                        if 'mapped_plex_title' in item:
                             found_items.append(r)
                             break
                        else:
                            # If text match, double-check the year
                            r_year = r.year if r.year else 0
                            if r_year in [year, year-1, year+1]:
                                found_items.append(r)
                                break
                except: pass
        
        found_items = list(set(found_items))

        # --- 5. EXECUTE SYNC VS APPEND ---
        try:
            existing_col = target_lib.search(title=preset['title'], libtype='collection')[0]
        except: existing_col = None

        if not existing_col:
            if found_items:
                target_lib.createCollection(title=preset['title'], items=found_items)
                return True, f"Created '{preset['title']}' with {len(found_items)} items."
            return True, "No items found."
        else:
            current_items = existing_col.items()
            current_ids = {x.ratingKey for x in current_items}
            new_ids = {x.ratingKey for x in found_items}
            
            to_add = [x for x in found_items if x.ratingKey not in current_ids]
            
            if mode == 'sync':
                to_remove = [x for x in current_items if x.ratingKey not in new_ids]
            else:
                to_remove = []

            if to_add: existing_col.addItems(to_add)
            if to_remove: existing_col.removeItems(to_remove)
                
            action = "Synced (Strict)" if mode == 'sync' else "Appended"
            msg = f"{action} '{preset['title']}': Added {len(to_add)}, Removed {len(to_remove)}."
            write_log("SUCCESS", "Sync", msg)
            return True, msg

    except Exception as e:
        write_log("ERROR", "Sync", str(e))
        return False, str(e)
    
    finally:
        # 3. RELEASE LOCK
        remove_system_lock()
        
def is_duplicate(tmdb_item, plex_raw_titles, settings=None):
    # Simplified check for V1.1
    # We rely on cache normalization
    tmdb_title = tmdb_item.get('title') if tmdb_item.get('media_type') == 'movie' else tmdb_item.get('name')
    if not tmdb_title: return False
    
    norm = normalize_title(tmdb_title)
    return norm in plex_raw_titles

# --- STANDARD HELPERS ---
def fetch_omdb_ratings(title, year, api_key):
    if not api_key: return []
    try:
        url = f"https://www.omdbapi.com/?apikey={api_key}&t={title}&y={year}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            return r.json().get('Ratings', [])
    except: pass
    return []

def send_overseerr_request(settings, media_type, tmdb_id, uid=None):
    if not settings.overseerr_url or not settings.overseerr_api_key:
        return False
        
    headers = {'X-Api-Key': settings.overseerr_api_key}
    payload = {
        'mediaType': media_type,
        'mediaId': int(tmdb_id)
    }
    
    try:
        r = requests.post(f"{settings.overseerr_url}/api/v1/request", json=payload, headers=headers)
        return r.status_code in [200, 201]
    except:
        return False

def check_for_updates(current_version, raw_url):
    try:
        resp = requests.get(raw_url, timeout=2)
        if resp.status_code == 200:
            match = re.search(r'VERSION\s*=\s*"([^"]+)"', resp.text)
            if match and match.group(1) != current_version:
                return match.group(1)
    except: pass
    return None

def handle_lucky_mode(settings):
    try:
        random_genre = random.choice([28, 35, 18, 878, 27, 53]) 
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={settings.tmdb_key}&with_genres={random_genre}&sort_by=popularity.desc&page={random.randint(1, 10)}"
        data = requests.get(url).json().get('results', [])
        
        picks = random.sample(data, min(5, len(data)))
        movies = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in picks]
        
        return movies  # Return all 5 items
            
    except: pass
    return None

# --- BACKUPS ---
def create_backup():
    filename = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    filepath = os.path.join(BACKUP_DIR, filename)
    
    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        if os.path.exists('/config/seekandwatch.db'):
            zipf.write('/config/seekandwatch.db', arcname='seekandwatch.db')
        if os.path.exists(CACHE_FILE):
            zipf.write(CACHE_FILE, arcname='plex_cache.json')
            
    prune_backups()
    return True, filename

def list_backups():
    if not os.path.exists(BACKUP_DIR): return []
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.zip')]
    files.sort(reverse=True)
    backups = []
    for f in files:
        path = os.path.join(BACKUP_DIR, f)
        try:
            sz = os.path.getsize(path)
            size_str = f"{round(sz / 1024, 2)} KB" if sz < 1024*1024 else f"{round(sz / (1024*1024), 2)} MB"
            date = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
            backups.append({'filename': f, 'size': size_str, 'date': date})
        except: pass
    return backups

def restore_backup(filename):
    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(filepath): return False, "File not found"
    try:
        with zipfile.ZipFile(filepath, 'r') as zipf:
            zipf.extractall("/config")
        return True, "Restored"
    except Exception as e:
        return False, str(e)

def prune_backups(days=7):
    if not os.path.exists(BACKUP_DIR): return
    cutoff = time.time() - (days * 86400)
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith('.zip'): continue
        path = os.path.join(BACKUP_DIR, f)
        if os.path.getmtime(path) < cutoff:
            try: os.remove(path)
            except: pass