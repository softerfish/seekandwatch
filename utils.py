import re
import socket
import ipaddress
from urllib.parse import urlparse
import requests
import difflib
import random
import json
import time
import datetime
import os
import zipfile
import threading
import sqlite3
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
            
            r = requests.get(url, timeout=10)
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
            # FIX: Race Condition Protection
            # Re-query the DB to see if any of these IDs appeared while we were fetching from the API.
            new_ids = [e['id'] for e in new_entries]
            existing_in_db = db.session.query(TmdbKeywordCache.tmdb_id).filter(TmdbKeywordCache.tmdb_id.in_(new_ids)).all()
            existing_ids = {r[0] for r in existing_in_db}

            count_added = 0
            for entry in new_entries:
                # Only add if it STILL doesn't exist
                if entry['id'] not in existing_ids:
                    db.session.add(TmdbKeywordCache(
                        tmdb_id=entry['id'],
                        media_type=entry['type'],
                        keywords=json.dumps(entry['tags'])
                    ))
                    count_added += 1
            
            # Only prune if we actually added data (saves performance)
            if count_added > 0:
                s = Settings.query.first()
                limit = s.keyword_cache_size or 2000
                
                total = TmdbKeywordCache.query.count()
                if total > limit:
                    # Delete oldest entries to maintain limit
                    excess = total - limit
                    subq = db.session.query(TmdbKeywordCache.id).order_by(TmdbKeywordCache.timestamp.asc()).limit(excess).subquery()
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

        # [SAFETY GUARD 1] Network/API Failure Protection
        # If we requested pages but got literally 0 items, it's likely a TMDB outage or API key issue.
        # We abort to prevent 'Sync' mode from seeing 0 items and deleting your whole collection.
        if not tmdb_items: 
            return False, "Aborted: No items returned from TMDB. Possible API outage?"

        # --- 3. OPTIMIZED MATCHING ---
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

            # [SAFETY GUARD 2] Bulk Add Limit
            # Prevents crashing Plex or hitting rate limits if a list is unexpectedly huge
            if len(to_add) > 1000:
                return False, f"Aborted: Attempted to add {len(to_add)} items. Limit is 1000."

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
        return False, "Overseerr settings missing."
        
    headers = {'X-Api-Key': settings.overseerr_api_key}
    
    try:
        payload = {
            'mediaType': media_type,
            'mediaId': int(tmdb_id)
        }
        
        # --- TV LOGIC (Restored from v1.1) ---
        # 1. Ask TMDB what seasons exist
        # 2. If that fails, default to Season 1
        if media_type == 'tv':
            seasons = []
            if settings.tmdb_key:
                try:
                    url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={settings.tmdb_key}"
                    data = requests.get(url, timeout=4).json()
                    for s in data.get('seasons', []):
                        if s.get('season_number', 0) > 0:
                            seasons.append(s['season_number'])
                except:
                    pass
            
            # Fallback
            if not seasons: seasons = [1]
            payload['seasons'] = seasons

        # --- SEND REQUEST ---
        # Ensure no double slashes
        base_url = settings.overseerr_url.rstrip('/')
        url = f"{base_url}/api/v1/request"
        
        print(f"Sending to Overseerr: {url} | Payload: {payload}", flush=True)
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # --- RESULT HANDLING ---
        if r.status_code in [200, 201]:
            return True, "Success"
            
        # Parse the error so we can show it to the user
        try:
            error_msg = r.json().get('message', r.text)
        except:
            error_msg = f"HTTP Error {r.status_code}"

        # Friendly overrides for common errors
        if "already available" in str(error_msg).lower():
            return False, "Already Available"
        if "already requested" in str(error_msg).lower():
            return False, "Already Requested"
            
        return False, f"Overseerr: {error_msg}"

    except Exception as e:
        return False, f"Connection Error: {str(e)}"
        
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
        
        random.shuffle(data)
        
        movies = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in data]
        
        return movies
            
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
    # Force filename to be just the name, preventing absolute path overrides
    filename = os.path.basename(filename)

    filepath = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(filepath): return False, "File not found"
    try:
        target_dir = "/config"
        with zipfile.ZipFile(filepath, 'r') as zipf:
            for member in zipf.namelist():
                # Calculate the absolute path where this file wants to go
                abs_target = os.path.abspath(os.path.join(target_dir, member))
                abs_root = os.path.abspath(target_dir)

                # Add os.sep to prevent "Partial Path Traversal" (e.g. /config_hack)
                # We check if it starts with "/config/" not just "/config"
                if not abs_target.startswith(abs_root + os.sep):
                    # If not, it's an attack trying to escape to /etc/ or /root/
                    raise Exception(f"Security Alert: Malicious file path detected ({member}). Restore aborted.")
            
            # If the loop finishes without error, it is safe to extract
            zipf.extractall(target_dir)
            
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

def reset_stuck_locks():
    """
    Called on startup.
    Deletes any stale 'cache.lock' files from the config folder.
    """
    lock_file = '/config/cache.lock'
    
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
            print(f" [Startup] DELETED STALE LOCK FILE: {lock_file}", flush=True)
        except Exception as e:
            print(f" [Startup] Could not delete lock file: {e}")
            
def validate_url(url):
    """
    Security Check: Prevents SSRF attacks.
    Blocks: Localhost, 127.x.x.x, 0.0.0.0, Cloud Metadata (169.254.x.x), and IPv6 Loopbacks.
    Allows: Private LAN IPs (192.168.x.x, 10.x.x.x) for self-hosted usage.
    """
    try:
        parsed = urlparse(url)
        # 1. Check Scheme
        if parsed.scheme not in ('http', 'https'):
            return False, "Invalid protocol (only HTTP/HTTPS allowed)"
        
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname"
            
        # 2. DNS Resolution (IPv4 AND IPv6)
        # Use getaddrinfo to check ALL IPs associated with the host.
        # This prevents an attacker from hiding a localhost IP in a list of valid IPs.
        try:
            # Check both IPv4 and IPv6
            addr_info = socket.getaddrinfo(hostname, None)
        except:
            return False, "Could not resolve hostname"

        # 3. Block Dangerous Ranges on ALL resolved IPs
        for res in addr_info:
            family, socktype, proto, canonname, sockaddr = res
            ip_str = sockaddr[0]
            
            # Skip empty IPs
            if not ip_str: continue

            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue # Skip invalid IPs

            # Critical Checks
            if ip.is_loopback: # Blocks 127.0.0.0/8 and ::1
                return False, f"Access to Loopback ({ip_str}) is denied."
            
            if ip.is_link_local: # Blocks 169.254.x.x
                return False, f"Access to Link-Local ({ip_str}) is denied."
            
            if ip.is_multicast: # Blocks 224.0.0.0/4
                return False, "Access to Multicast is denied."
                
            if str(ip) == "0.0.0.0" or str(ip) == "::":
                return False, "Access to 0.0.0.0/:: is denied."

        # Explicitly ALLOW private IPs (192.168.x.x, 10.x.x.x)
        # We do NOT block ip.is_private because this is a dashboard app.
        
        return True, "OK"
        
    except Exception as e:
        return False, f"Validation Error: {str(e)}"
        
def prefetch_tv_states_parallel(items, api_key):
    """
    Fetches TV Show Status (Ended, Returning, Canceled) for a batch of items.
    Updates the items list in-place.
    """
    if not items: return

    # Filter for TV shows only
    tv_items = [i for i in items if i.get('media_type') == 'tv']
    if not tv_items: return

    def fetch_status(item):
        try:
            # We fetch details to get the 'status' field
            url = f"https://api.themoviedb.org/3/tv/{item['id']}?api_key={api_key}"
            data = requests.get(url, timeout=2).json()
            return {'id': item['id'], 'status': data.get('status', 'Unknown')}
        except:
            return None

    # Use 10 threads to fetch quickly
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_status, tv_items)
        
    status_map = {r['id']: r['status'] for r in results if r}
    
    # Inject status back into the main list
    for item in items:
        if item['id'] in status_map:
            item['status'] = status_map[item['id']]
            
def prefetch_ratings_parallel(items, api_key):
    """
    Fetches US Content Ratings (Certification) for a batch of items.
    Updates items in-place with 'content_rating' key.
    """
    if not items: return

    def fetch_rating(item):
        if 'content_rating' in item: return None

        try:
            m_type = item.get('media_type', 'movie')
            # Endpoint differs by type
            subset = 'release_dates' if m_type == 'movie' else 'content_ratings'
            url = f"https://api.themoviedb.org/3/{m_type}/{item['id']}/{subset}?api_key={api_key}"
            
            data = requests.get(url, timeout=2).json()
            results = data.get('results', [])
            
            rating = "NR"
            # Find US Rating
            for r in results:
                if r.get('iso_3166_1') == 'US':
                    if m_type == 'movie':
                        # Movies return a list of release dates, grab the first non-empty certification
                        dates = r.get('release_dates', [])
                        for d in dates:
                            if d.get('certification'):
                                rating = d.get('certification')
                                break
                    else:
                        # TV returns a direct rating
                        rating = r.get('rating')
                    break
            
            # Normalize NR
            if not rating or rating == '': rating = "NR"
            
            return {'id': item['id'], 'rating': rating}
        except:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_rating, items)
        
    rating_map = {r['id']: r['rating'] for r in results if r}
    
    for item in items:
        # Default to NR if API fails or no US rating found
        item['content_rating'] = rating_map.get(item['id'], 'NR')

def get_tautulli_trending(media_type='movie'):
    """
    Fetches Top 5 Trending from Tautulli (Home Stats)
    media_type: 'movie' or 'tv'
    """
    try:
        s = Settings.query.first()
        if not s or not s.tautulli_url or not s.tautulli_api_key:
            return []

        # Tautulli uses specific stat_ids for home stats
        stat_id = 'popular_movies' if media_type == 'movie' else 'popular_tv'
        
        # We look back 30 days for better data
        url = f"{s.tautulli_url.rstrip('/')}/api/v2?apikey={s.tautulli_api_key}&cmd=get_home_stats&time_range=30&stats_count=10"
        resp = requests.get(url, timeout=5)
        data = resp.json()

        trending_items = []
        
        # Parse Tautulli Response
        for block in data.get('response', {}).get('data', []):
            if block.get('stat_id') == stat_id:
                for row in block.get('rows', []):
                    # Tautulli gives us a rating_key (Plex ID)
                    rating_key = row.get('rating_key')
                    
                    # Resolve to TMDB via Plex
                    try:
                        plex = PlexServer(s.plex_url, s.plex_token)
                        item = plex.fetchItem(rating_key)
                        
                        # Get TMDB ID from GUIDs
                        tmdb_id = None
                        for guid in item.guids:
                            if 'tmdb://' in guid.id:
                                tmdb_id = guid.id.split('//')[1]
                                break
                        
                        if tmdb_id:
                            # Fetch Poster from TMDB for high-quality art
                            tmdb_resp = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}").json()
                            trending_items.append({
                                'title': row.get('title'),
                                'poster_path': tmdb_resp.get('poster_path'),
                                'tmdb_id': tmdb_id,
                                'media_type': media_type
                            })
                    except:
                        continue # Skip if item not found in Plex or TMDB fail
                break
                
        return trending_items[:5]

    except Exception as e:
        print(f"Tautulli Error: {e}")
        return []