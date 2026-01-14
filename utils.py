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
from flask import flash, redirect, url_for, session, render_template
from plexapi.server import PlexServer
# Import TmdbAlias here
from models import db, CollectionSchedule, SystemLog, Settings, TmdbAlias
from presets import PLAYLIST_PRESETS

# --- CONFIGURATION ---
BACKUP_DIR = '/config/backups'
CACHE_FILE = '/config/plex_cache.json'
LOCK_FILE = '/config/cache.lock'
# URL to your master alias list
ALIAS_SOURCE_URL = "https://f005.backblazeb2.com/file/seekandwatch-data/aliases.json" 

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

# --- LOGGING HELPER ---
def write_log(level, module, message):
    """
    Writes to the database log if logging is enabled.
    Levels: INFO, SUCCESS, WARNING, ERROR
    """
    try:
        s = Settings.query.first()
        if s and (s.logging_enabled or level == 'ERROR'):
            log = SystemLog(level=level, module=module, message=str(message))
            db.session.add(log)
            db.session.commit()
            
            if log.id % 20 == 0: 
                limit_mb = s.max_log_size if s.max_log_size is not None else 5
                if limit_mb <= 0: return
                count = SystemLog.query.count()
                estimated_size_mb = (count * 200) / (1024 * 1024)
                
                if estimated_size_mb > limit_mb:
                    to_delete = int(count * 0.1)
                    oldest = SystemLog.query.order_by(SystemLog.timestamp.asc()).limit(to_delete).all()
                    for o in oldest: db.session.delete(o)
                    db.session.commit()
                    db.session.add(SystemLog(level="WARN", module="System", message=f"Logs exceeded {limit_mb}MB. Pruned {to_delete} oldest entries."))
                    db.session.commit()
    except Exception as e:
        print(f"Logging Failed: {e}")

def normalize_title(title):
    if not title: return ""
    return re.sub(r'[^a-z0-9]', '', str(title).lower())

# --- DYNAMIC ALIAS LOOKUP (DB BACKED) ---
def get_tmdb_aliases(tmdb_id, media_type, settings):
    """
    1. Checks Database for cached aliases.
    2. If missing, asks TMDB.
    3. Saves result to Database for next time.
    """
    # 1. Check DB
    try:
        cached = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=media_type).first()
        if cached:
            return json.loads(cached.aliases)
    except: pass

    # 2. Fetch from TMDB
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/alternative_titles?api_key={settings.tmdb_key}"
        data = requests.get(url, timeout=3).json()
        
        key = 'titles' if 'titles' in data else 'results'
        aliases = [normalize_title(x['title']) for x in data.get(key, [])]
        
        # 3. Save to DB
        try:
            new_entry = TmdbAlias(tmdb_id=tmdb_id, media_type=media_type, aliases=json.dumps(aliases))
            db.session.add(new_entry)
            db.session.commit()
        except: 
            db.session.rollback()
            
        return aliases
    except:
        return []

# --- REMOTE ALIAS SYNC ---
def sync_remote_aliases():
    """
    Downloads alias list from seekandwatch.com and merges into DB.
    """
    write_log("INFO", "System", f"Downloading aliases from {ALIAS_SOURCE_URL}...")
    try:
        resp = requests.get(ALIAS_SOURCE_URL, timeout=10)
        if resp.status_code != 200:
            write_log("ERROR", "System", f"Remote alias download failed: {resp.status_code}")
            return False, f"HTTP Error {resp.status_code}"
            
        data = resp.json()
        count = 0
        
        for item in data:
            # Expecting format: [{"tmdb_id": 123, "media_type": "movie", "aliases": ["title1", "title2"]}]
            tid = item.get('tmdb_id')
            mtype = item.get('media_type', 'movie')
            new_list = [normalize_title(x) for x in item.get('aliases', [])]
            
            if not tid or not new_list: continue
            
            # Check existing
            entry = TmdbAlias.query.filter_by(tmdb_id=tid, media_type=mtype).first()
            if entry:
                # Merge existing with new
                current = set(json.loads(entry.aliases))
                updated = list(current.union(set(new_list)))
                entry.aliases = json.dumps(updated)
            else:
                # Create new
                db.session.add(TmdbAlias(tmdb_id=tid, media_type=mtype, aliases=json.dumps(new_list)))
            count += 1
            
        db.session.commit()
        msg = f"Imported/Updated {count} alias entries from remote server."
        write_log("SUCCESS", "System", msg)
        return True, msg
        
    except Exception as e:
        write_log("ERROR", "System", f"Alias Sync Failed: {str(e)}")
        return False, str(e)

# ==================================================================================
# LOCK MANAGER
# ==================================================================================

def is_system_locked():
    return os.path.exists(LOCK_FILE)

def set_system_lock(status_msg="Busy"):
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(status_msg)
        return True
    except: return False

def remove_system_lock():
    if os.path.exists(LOCK_FILE):
        try: os.remove(LOCK_FILE)
        except: pass

def get_lock_status():
    if not os.path.exists(LOCK_FILE): return "Idle"
    try:
        with open(LOCK_FILE, 'r') as f: return f.read().strip()
    except: return "Busy"

# ==================================================================================
# CACHE MANAGER
# ==================================================================================

def refresh_plex_cache(settings):
    if is_system_locked():
        return False, "System is busy. Please wait."

    print("--- STARTING PLEX CACHE REFRESH ---")
    write_log("INFO", "Cache", "Started background cache refresh.")
    set_system_lock("Refreshing Plex Cache...") 
    start_time = time.time()
    
    try:
        plex = PlexServer(settings.plex_url, settings.plex_token)
        cache_data = {} 

        for section in plex.library.sections():
            if section.type not in ['movie', 'show']: continue
            
            set_system_lock(f"Scanning {section.title}...")
            
            for item in section.all():
                try:
                    key = item.ratingKey
                    year = str(item.year) if item.year else ''
                    norm_title = normalize_title(item.title)
                    # FIX: Save the type so we don't mix Movies/TV later
                    item_type = section.type  # 'movie' or 'show'
                    
                    data_packet = {'key': key, 'year': year, 'type': item_type}
                    
                    cache_data[norm_title] = data_packet
                    
                    if year:
                        cache_data[f"{norm_title}_{year}"] = data_packet

                    if hasattr(item, 'originalTitle') and item.originalTitle:
                        norm_orig = normalize_title(item.originalTitle)
                        cache_data[norm_orig] = data_packet
                        
                except Exception as e:
                    continue

        duration = round(time.time() - start_time, 2)
        
        with open(CACHE_FILE, 'w') as f:
            json.dump({
                'timestamp': time.time(), 
                'duration': duration, 
                'data': cache_data
            }, f)
            
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
        return {} 
    
    try:
        with open(CACHE_FILE, 'r') as f:
            content = json.load(f)
            return content.get('data', {})
    except:
        return {}

# ==================================================================================
# CORE LOGIC: RUN COLLECTION SYNC
# ==================================================================================

def run_collection_logic(preset_key, settings):
    if is_system_locked():
        msg = get_lock_status()
        write_log("WARNING", "Sync", f"Skipped '{preset_key}' - System Busy.")
        return False, f"⚠️ System Busy: {msg}. Please wait..."

    write_log("INFO", "Sync", f"Starting Sync: {preset_key}")
    
    # 1. DETERMINE CONFIGURATION
    if preset_key.startswith('custom_'):
        schedule_entry = CollectionSchedule.query.filter_by(preset_key=preset_key).first()
        if not schedule_entry or not schedule_entry.configuration: 
            return False, "Custom preset not found."
        config = json.loads(schedule_entry.configuration)
        params = config.get('tmdb_params', {})
        params['api_key'] = settings.tmdb_key
        media_type = config.get('media_type', 'movie')
        collection_title = config.get('title')
    else:
        preset = PLAYLIST_PRESETS.get(preset_key)
        if not preset: return False, "Preset key not found."
        params = preset['tmdb_params'].copy()
        params['api_key'] = settings.tmdb_key
        media_type = preset['media_type']
        collection_title = preset['title']

    # 2. FETCH ITEMS FROM TMDB
    tmdb_items = []
    try:
        if 'with_collection_id' in params:
            col_id = params.pop('with_collection_id')
            url = f"https://api.themoviedb.org/3/collection/{col_id}?api_key={settings.tmdb_key}&language=en-US"
            data = requests.get(url).json()
            if 'parts' in data:
                tmdb_items = data['parts']
                for item in tmdb_items: item['media_type'] = 'movie' 
            else:
                write_log("ERROR", "TMDB", f"ID {col_id}: {data.get('status_message')}")
                return False, f"TMDB Error: {data.get('status_message', 'Unknown error')}"
        else:
            endpoint = 'discover/tv' if media_type == 'tv' else 'discover/movie'
            url = f"https://api.themoviedb.org/3/{endpoint}"
            for page in range(1, 3):
                params['page'] = page
                res = requests.get(url, params=params).json()
                results = res.get('results', [])
                if not results: break
                tmdb_items.extend(results)
    except Exception as e:
        write_log("ERROR", "TMDB", f"API Error: {str(e)}")
        return False, f"TMDB API Error: {e}"

    if not tmdb_items: 
        write_log("WARNING", "Sync", "No items returned from TMDB.")
        return False, "No items found on TMDB."

    plex_map = get_plex_cache(settings)
    
    if not plex_map:
        return False, "⚠️ Cache Missing! Click 'Force Refresh Now' at the top of the page first."

    # 3. MATCH TMDB ITEMS TO PLEX KEYS
    matched_rating_keys = []
    target_plex_type = 'show' if media_type == 'tv' else 'movie'

    for t_item in tmdb_items:
        t_title = t_item.get('title') if media_type == 'movie' else t_item.get('name')
        t_date = t_item.get('release_date') if media_type == 'movie' else t_item.get('first_air_date')
        t_year = (t_date or '')[:4]
        
        norm_t_title = normalize_title(t_title)
        match = plex_map.get(norm_t_title)
        
        # 1. Direct Match
        if not match and t_year:
            match = plex_map.get(f"{norm_t_title}_{t_year}")
        
        # 2. Fuzzy Match
        if not match:
            closest = difflib.get_close_matches(norm_t_title, plex_map.keys(), n=1, cutoff=0.9)
            if closest:
                match = plex_map[closest[0]]

        # 3. Dynamic Alias Lookup (DB Backed)
        if not match:
            try:
                aliases = get_tmdb_aliases(t_item['id'], media_type, settings)
                for alias in aliases:
                    match = plex_map.get(alias)
                    if match: break
            except: pass

        if match:
            # FIX: Only add if the cached type matches our target type (if known)
            if match.get('type') and match['type'] != target_plex_type:
                continue
            matched_rating_keys.append(match['key'])

    matched_rating_keys = list(set(matched_rating_keys))
    
    if not matched_rating_keys: 
        write_log("WARNING", "Sync", f"Found 0 matches in library for {len(tmdb_items)} TMDB items.")
        return False, f"Found 0 matches in Plex (out of {len(tmdb_items)} TMDB items)."

    # 4. CREATE PLEX COLLECTION
    try:
        plex = PlexServer(settings.plex_url, settings.plex_token)
        target_lib = None
        for section in plex.library.sections():
            if section.type == target_plex_type:
                target_lib = section
                break
        
        if not target_lib: return False, "Target Library not found"

        # Check existing collection
        found_col = None
        for col in target_lib.collections():
            if col.title == collection_title:
                found_col = col
                break
        
        if found_col: found_col.delete()
            
        final_items = []
        for key in matched_rating_keys:
            try:
                item = plex.fetchItem(key)
                # FIX: Double check the item type before adding to list
                # Plex 'movie' type is 'movie', 'tv' type is 'show'
                if item.type == target_plex_type:
                    final_items.append(item)
            except: pass
            
        if not final_items:
            return False, "No valid items found matching the library type."

        target_lib.createCollection(title=collection_title, items=final_items)
        
        msg = f"Created '{collection_title}' with {len(final_items)} items."
        print(msg)
        write_log("SUCCESS", "Sync", msg)
        
        return True, f"Success! {msg}"

    except Exception as e:
        write_log("ERROR", "Plex", f"Sync failed: {str(e)}")
        return False, f"Plex Error: {e}"

# --- HELPERS (Standard) ---
def is_duplicate(tmdb_title, plex_titles_normalized):
    if not tmdb_title: return False
    target = normalize_title(tmdb_title)
    if target in plex_titles_normalized: return True
    return False

def fetch_omdb_ratings(tmdb_id, media_type, settings):
    if not settings.omdb_key: return None
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids?api_key={settings.tmdb_key}"
        ext_data = requests.get(url).json()
        imdb_id = ext_data.get('imdb_id')
        if imdb_id:
            omdb_url = f"http://www.omdbapi.com/?apikey={settings.omdb_key}&i={imdb_id}"
            omdb_data = requests.get(omdb_url).json()
            if omdb_data.get('Response') == 'True':
                return omdb_data.get('Ratings', [])
    except: pass
    return None

def send_overseerr_request(settings, media_type, tmdb_id, user_id):
    headers = {'X-Api-Key': settings.overseerr_api_key, 'Content-Type': 'application/json'}
    payload = {"mediaType": media_type, "mediaId": int(tmdb_id), "userId": user_id}
    if media_type == 'tv':
        try:
            data = requests.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={settings.tmdb_key}", timeout=5).json()
            payload["seasons"] = [i for i in range(1, data.get('number_of_seasons', 1) + 1)]
        except: payload["seasons"] = [1]
    try:
        resp = requests.post(f"{settings.overseerr_url}/api/v1/request", json=payload, headers=headers, timeout=10)
        return resp.status_code in [200, 201, 409]
    except: return False

def check_for_updates(current_version, raw_url):
    try:
        resp = requests.get(raw_url, timeout=2)
        if resp.status_code == 200:
            match = re.search(r'VERSION\s*=\s*"([^"]+)"', resp.text)
            if match and match.group(1) != current_version: return match.group(1)
    except: pass
    return None

def handle_lucky_mode(settings):
    try:
        random_genre = random.choice([28, 35, 18, 878, 27, 53]) 
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={settings.tmdb_key}&with_genres={random_genre}&sort_by=popularity.desc&page={random.randint(1, 10)}"
        data = requests.get(url).json().get('results', [])
        picks = random.sample(data, min(5, len(data)))
        movies = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average')} for p in picks]
        return render_template('results.html', movies=movies, lucky_mode=True)
    except:
        return redirect(url_for('dashboard'))

def create_backup():
    try:
        filename = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        filepath = os.path.join(BACKUP_DIR, filename)
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists('/config/site.db'): zipf.write('/config/site.db', arcname='site.db')
        return True, filename
    except Exception as e: return False, str(e)

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
        with zipfile.ZipFile(filepath, 'r') as zipf: zipf.extract("site.db", "/config")
        return True, "Restored"
    except Exception as e: return False, str(e)

def prune_backups(retention_days):
    if not os.path.exists(BACKUP_DIR): return
    cutoff = time.time() - (retention_days * 86400)
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith('.zip'): continue
        path = os.path.join(BACKUP_DIR, f)
        if os.path.getmtime(path) < cutoff:
            try: os.remove(path)
            except: pass
