"""Helper functions and utilities used throughout the app."""

import concurrent.futures
import datetime
import difflib
import ipaddress
import json
import math
import os
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from urllib.parse import urlparse

import requests
from flask import flash, redirect, url_for, session, render_template, has_app_context, current_app
from plexapi.server import PlexServer
from werkzeug.utils import secure_filename

from models import db, CollectionSchedule, SystemLog, Settings, TmdbAlias, TmdbKeywordCache
from presets import PLAYLIST_PRESETS

# Configuration
BACKUP_DIR = '/config/backups'
CACHE_FILE = '/config/plex_cache.json'
LOCK_FILE = '/config/cache.lock'
SCANNER_LOG_FILE = '/config/scanner.log'

# in-memory caches (also persisted to disk)
RESULTS_CACHE = {}
HISTORY_CACHE = {}
TMDB_REC_CACHE = {}
TMDB_REC_CACHE_LOCK = threading.Lock()

RESULTS_CACHE_FILE = '/config/results_cache.json'
RESULTS_CACHE_TTL = 60 * 60 * 24
HISTORY_CACHE_FILE = '/config/history_cache.json'
HISTORY_CACHE_TTL = 60 * 60
TMDB_REC_CACHE_TTL = 60 * 60 * 24

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

def _now_ts():
    return int(time.time())

def _load_cache_file(path, ttl):
    if not os.path.exists(path):
        return {}
    try:
        raw = json.loads(open(path, 'r', encoding='utf-8').read())
    except Exception:
        return {}
    now = _now_ts()
    cleaned = {}
    for k, v in (raw or {}).items():
        if not isinstance(v, dict):
            continue
        ts = v.get('ts', 0)
        if ts and now - ts <= ttl:
            cleaned[k] = v
    return cleaned

def _save_cache_file(path, payload):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except Exception:
        pass

def load_results_cache():
    global RESULTS_CACHE
    RESULTS_CACHE = _load_cache_file(RESULTS_CACHE_FILE, RESULTS_CACHE_TTL)

def save_results_cache():
    _save_cache_file(RESULTS_CACHE_FILE, RESULTS_CACHE)

def load_history_cache():
    global HISTORY_CACHE
    HISTORY_CACHE = _load_cache_file(HISTORY_CACHE_FILE, HISTORY_CACHE_TTL)

def save_history_cache():
    _save_cache_file(HISTORY_CACHE_FILE, HISTORY_CACHE)

def get_history_cache(key):
    entry = HISTORY_CACHE.get(key)
    if not entry:
        return None
    if _now_ts() - entry.get('ts', 0) > HISTORY_CACHE_TTL:
        HISTORY_CACHE.pop(key, None)
        return None
    return entry.get('candidates')

def set_history_cache(key, candidates):
    HISTORY_CACHE[key] = {'candidates': candidates, 'ts': _now_ts()}
    save_history_cache()

def get_tmdb_rec_cache(key):
    with TMDB_REC_CACHE_LOCK:
        entry = TMDB_REC_CACHE.get(key)
        if not entry:
            return None
        if _now_ts() - entry.get('ts', 0) > TMDB_REC_CACHE_TTL:
            TMDB_REC_CACHE.pop(key, None)
            return None
        return entry.get('results')

def set_tmdb_rec_cache(key, results):
    with TMDB_REC_CACHE_LOCK:
        TMDB_REC_CACHE[key] = {'results': results, 'ts': _now_ts()}

def score_recommendation(item):
    vote_avg = item.get('vote_average', 0) or 0
    vote_count = item.get('vote_count', 0) or 0
    popularity = item.get('popularity', 0) or 0
    return (vote_avg * math.log1p(vote_count)) + (popularity * 0.5)

def diverse_sample(items, limit, bucket_fn=None):
    if not items or limit <= 0:
        return []
    buckets = {}
    for item in items:
        key = bucket_fn(item) if bucket_fn else None
        buckets.setdefault(key, []).append(item)
    for key in list(buckets.keys()):
        buckets[key].sort(key=lambda x: x.get('score', 0), reverse=True)
    result = []
    keys = list(buckets.keys())
    while len(result) < limit and keys:
        next_keys = []
        for key in keys:
            bucket = buckets.get(key, [])
            if bucket:
                result.append(bucket.pop(0))
                if len(result) >= limit:
                    break
            if bucket:
                next_keys.append(key)
        keys = next_keys
    return result

# session helper functions
def get_session_filters():
    """Gets all the filter settings from the user's session."""
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

# keyword/tag matching stuff

def prefetch_keywords_parallel(items, api_key):
    """
    Fetches TMDB keywords for items in parallel.
    Checks DB first, then API for missing ones, saves to DB.
    """
    if not items: return

    # Identify what we need.
    needed = []
    cached_map = {}
    
    # Get all IDs from the list.
    target_ids = [item['id'] for item in items]
    
    # Bulk fetch existing from DB.
    try:
        existing = TmdbKeywordCache.query.filter(TmdbKeywordCache.tmdb_id.in_(target_ids)).all()
        for row in existing:
            try: cached_map[row.tmdb_id] = json.loads(row.keywords)
            except: cached_map[row.tmdb_id] = []
    except Exception as e:
        print(f"DB Read Error: {e}")

    # find what's missing from the cache
    for item in items:
        if item['id'] not in cached_map:
            needed.append(item)
    
    if not needed:
        return  # already got everything we need

    # fetch the missing ones from TMDB API (in parallel for speed)
    def fetch_tags(item):
        try:
            # TMDB endpoint is different for movies vs TV, but both use /keywords
            ep = 'keywords'  # default endpoint
            url = f"https://api.themoviedb.org/3/{item['media_type']}/{item['id']}/keywords?api_key={api_key}"
            
            r = requests.get(url, timeout=10)
            if r.status_code != 200: return None
            
            data = r.json()
            # movies return 'keywords', TV returns 'results' - handle both
            raw_tags = data.get('keywords', data.get('results', []))
            tags = [k['name'].lower() for k in raw_tags]
            
            return {'id': item['id'], 'type': item['media_type'], 'tags': tags}
        except:
            return None

    new_entries = []
    # use 10 workers so we don't timeout on big batches
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_tags, needed)
        for res in results:
            if res:
                new_entries.append(res)

    # Save to DB.
    if new_entries:
        try:
            # Re-query in case another thread wrote the same IDs.
            new_ids = [e['id'] for e in new_entries]
            existing_in_db = db.session.query(TmdbKeywordCache.tmdb_id).filter(TmdbKeywordCache.tmdb_id.in_(new_ids)).all()
            existing_ids = {r[0] for r in existing_in_db}

            count_added = 0
            for entry in new_entries:
                # Only add if it still doesn't exist.
                if entry['id'] not in existing_ids:
                    db.session.add(TmdbKeywordCache(
                        tmdb_id=entry['id'],
                        media_type=entry['type'],
                        keywords=json.dumps(entry['tags'])
                    ))
                    count_added += 1
            
            # only clean up old entries if we actually added new stuff
            if count_added > 0:
                s = Settings.query.first()
                limit = s.keyword_cache_size or 2000
                
                total = TmdbKeywordCache.query.count()
                if total > limit:
                    # delete the oldest entries to stay under the limit
                    excess = total - limit
                    subq = db.session.query(TmdbKeywordCache.id).order_by(TmdbKeywordCache.timestamp.asc()).limit(excess).subquery()
                    TmdbKeywordCache.query.filter(TmdbKeywordCache.id.in_(subq)).delete(synchronize_session=False)

            db.session.commit()
        except Exception as e:
            print(f"Cache Save Error: {e}")
            db.session.rollback()
            
def item_matches_keywords(item, target_keywords):
    # if no keywords filter, everything matches
    if not target_keywords: return True
    
    # normalize the search terms
    search_terms = {t.lower() for t in target_keywords}
    
    # quick check: see if keywords are in the title/overview
    text_blob = (item.get('title', '') + ' ' + item.get('name', '') + ' ' + item.get('overview', '')).lower()
    for term in search_terms:
        if term in text_blob: return True
            
    # deeper check: look at the cached TMDB keywords
    try:
        entry = TmdbKeywordCache.query.filter_by(tmdb_id=item['id']).first()
        api_tags = json.loads(entry.keywords) if entry else []
    except:
        api_tags = []
    
    if api_tags:
        if search_terms.intersection(set(api_tags)):
            return True
                
    return False

def prefetch_omdb_parallel(items, api_key):
    # grab rotten tomatoes scores in parallel (way faster than one at a time)
    if not api_key or not items:
        return

    def fetch_rt(item):
        if item.get('rt_score') is not None:
            return None
        title = item.get('title') or item.get('name')
        year = item.get('year')
        if not title:
            return None
        ratings = fetch_omdb_ratings(title, year, api_key)
        rt_score = 0
        for r in (ratings or []):
            if r['Source'] == 'Rotten Tomatoes':
                try:
                    rt_score = int(r['Value'].replace('%', ''))
                except Exception:
                    rt_score = 0
                break
        return {'id': item.get('id'), 'rt_score': rt_score}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_rt, items)

    rt_map = {r['id']: r['rt_score'] for r in results if r and r.get('id')}
    for item in items:
        if item.get('id') in rt_map:
            item['rt_score'] = rt_map[item['id']]

load_results_cache()
load_history_cache()
    
# logging functions
def write_log(level, module, message, app_obj=None):
    # need to handle app context since this might be called from background threads
    try:
        if app_obj:
            with app_obj.app_context():
                _write_log_internal(level, module, message)
        elif has_app_context():
            _write_log_internal(level, module, message)
        else:
            # Try to get app from current context.
            try:
                app = current_app._get_current_object()
                with app.app_context():
                    _write_log_internal(level, module, message)
            except RuntimeError:
                print(f"Logging Failed: No Flask application context available. Level: {level}, Module: {module}, Message: {message}")
    except Exception as e:
        print(f"Logging Failed: {e}")

def _write_log_internal(level, module, message):
    # Actual logging logic.
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

def write_scanner_log(message):
    """Writes scanner messages to a file, rotates if it gets too big."""
    try:
        # import here to avoid circular dependency issues
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
    # Read last N lines.
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
    
    # Normalize special chars and accents.
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
    
    # Strip non-alphanumeric.
    return re.sub(r'[^a-z0-9]', '', t)

# alias/title matching stuff
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
        
        # could store aliases here but we mainly just need the ID match
        # (the alias DB handles the rest)
            
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
                # cache is just a list of normalized titles now
                owned_titles = json.load(f)
        except: return

        # figure out which titles we haven't scanned yet
        existing_plex_titles = set([row.plex_title for row in TmdbAlias.query.with_entities(TmdbAlias.plex_title).all()])
        to_scan = [t for t in owned_titles if t not in existing_plex_titles]
        
        total = len(to_scan)
        if total == 0:
            write_scanner_log("All items already indexed. Sleeping.")
            # update timestamp so we don't keep checking on every run
            s.last_alias_scan = int(time.time())
            db.session.commit()
            return

        batch_size = s.scanner_batch or 50
        current_batch = to_scan[:batch_size]
        
        write_scanner_log(f"Found {total} unindexed items. Processing batch of {batch_size}...")

        processed = 0
        
        for title in current_batch:
            try:
                # try searching as a movie first
                search_url = f"https://api.themoviedb.org/3/search/movie?api_key={s.tmdb_key}&query={title}"
                r = requests.get(search_url, timeout=10).json()
                
                tmdb_id = None
                media_type = 'movie'
                hit = None
                
                if r.get('results'):
                    hit = r['results'][0]
                    tmdb_id = hit['id']
                
                if not tmdb_id:
                    # no movie match, try TV instead
                    search_url = f"https://api.themoviedb.org/3/search/tv?api_key={s.tmdb_key}&query={title}"
                    r = requests.get(search_url, timeout=10).json()
                    if r.get('results'):
                        hit = r['results'][0]
                        tmdb_id = hit['id']
                        media_type = 'tv'
                        
                if tmdb_id and hit:
                    # found it! save the mapping
                    main_entry = TmdbAlias(
                        tmdb_id=tmdb_id, media_type=media_type, 
                        plex_title=title, original_title=normalize_title(hit.get('title', hit.get('name'))),
                        match_year=0
                    )
                    db.session.add(main_entry)
                else:
                    # couldn't find it on TMDB, save a placeholder so we don't keep searching
                    dummy = TmdbAlias(tmdb_id=-1, media_type='unknown', plex_title=title)
                    db.session.add(dummy)
                
                processed += 1
                if processed % 10 == 0: db.session.commit()  # commit every 10 to avoid losing progress
                time.sleep(0.2)  # be nice to TMDB API
                
            except Exception as e:
                print(f"Scan Error on {title}: {e}")
        
        s.last_alias_scan = int(time.time())
        db.session.commit()
        write_scanner_log(f"Batch complete. Processed {processed} items.")

# lock file stuff (prevents multiple operations from running at once)
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
    if is_system_locked():
        return False, "System is busy. Please wait."

    print("--- STARTING PLEX CACHE REFRESH ---")
    
    with app_obj.app_context():
        settings = Settings.query.first()
        if not settings or not settings.plex_url:
            return False, "Plex not configured."

        write_log("INFO", "Cache", "Started background cache refresh.", app_obj=app_obj)
        set_system_lock("Refreshing Plex Cache...") 
        start_time = time.time()
        
        try:
            plex = PlexServer(settings.plex_url, settings.plex_token)
            cache_data = set()

            sections = plex.library.sections()
            
            for section in sections:
                if section.type not in ['movie', 'show']:
                    continue
                
                set_system_lock(f"Scanning {section.title}...")
                
                for item in section.all():
                    try:
                        norm_title = normalize_title(item.title)
                        cache_data.add(norm_title)

                        if hasattr(item, 'originalTitle') and item.originalTitle:
                            norm_orig = normalize_title(item.originalTitle)
                            cache_data.add(norm_orig)
                            
                    except Exception as e:
                        continue

            duration = round(time.time() - start_time, 2)
            
            with open(CACHE_FILE, 'w') as f:
                json.dump(list(cache_data), f)
                
            msg = f"Cache rebuilt in {duration}s. Indexed {len(cache_data)} titles."
            print(f"--- {msg} ---")
            write_log("SUCCESS", "Cache", msg, app_obj=app_obj)
            return True, msg
            
        except Exception as e:
            print(f"Cache Refresh Failed: {e}")
            write_log("ERROR", "Cache", f"Refresh Failed: {str(e)}", app_obj=app_obj)
            return False, str(e)
        finally:
            remove_system_lock()

def get_plex_cache(settings):
    if not os.path.exists(CACHE_FILE):
        return []
    
    try:
        with open(CACHE_FILE, 'r') as f:
            content = json.load(f)
            # handle old format
            if isinstance(content, dict) and 'data' in content:
                return list(content['data'].keys())
            return content
    except:
        return []

# collection syncing logic
def run_collection_logic(settings, preset, key, app_obj=None):
    if is_system_locked(): return False, "System busy."
    
    set_system_lock(f"Syncing {preset.get('title', 'Collection')}...")
    write_log("INFO", "Sync", f"Starting Sync: {key}", app_obj=app_obj)

    try:
        plex = PlexServer(settings.plex_url, settings.plex_token)
        params = preset['tmdb_params'].copy()
        params['api_key'] = settings.tmdb_key
        tmdb_items = []

        # figure out if this is a trending collection (needs strict sync)
        category = preset.get('category', '')
        is_trending = 'Trending' in category or 'Trending' in preset.get('title', '')
        
        max_pages = 1 if is_trending else 50
        
        user_mode = preset.get('sync_mode', 'append')
        mode = 'sync' if is_trending else user_mode

        # grab items from TMDB
        if 'with_collection_id' in params:
            col_id = params.pop('with_collection_id')
            url = f"https://api.themoviedb.org/3/collection/{col_id}?api_key={settings.tmdb_key}&language=en-US"
            data = requests.get(url, timeout=10).json()
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

        # safety check - don't wipe collections if TMDB returns nothing
        if not tmdb_items: 
            return False, "Aborted: No items returned from TMDB. Possible API outage?"

        # get list of what we own in plex
        owned_titles = set(get_plex_cache(settings)) 
        
        # load the alias mappings (TMDB ID -> Plex title)
        id_map = {}
        try:
            rows = TmdbAlias.query.with_entities(TmdbAlias.tmdb_id, TmdbAlias.plex_title).all()
            for r in rows:
                id_map[r.tmdb_id] = r.plex_title
        except: pass

        # match TMDB items to what we own
        potential_matches = []
        for item in tmdb_items:
            # ID match is most reliable (from alias DB)
            if item['id'] in id_map:
                item['mapped_plex_title'] = id_map[item['id']]
                potential_matches.append(item)
                continue
            
            # fall back to title matching
            norm_title = normalize_title(item.get('title', item.get('name')))
            if norm_title in owned_titles:
                potential_matches.append(item)

        # actually search plex to verify these items exist
        target_type = 'movie' if preset['media_type'] == 'movie' else 'show'
        target_lib = next((s for s in plex.library.sections() if s.type == target_type), None)
        if not target_lib: 
            return False, f"No library found for {preset['media_type']}"

        found_items = []
        if potential_matches:
            for item in potential_matches:
                # use the mapped title if we have it (from alias DB)
                search_title = item.get('mapped_plex_title', item.get('title', item.get('name')))
                year = int((item.get('release_date') or item.get('first_air_date') or '0000')[:4])
                
                try:
                    results = target_lib.search(search_title)
                    for r in results:
                        # if we have a mapped title, ID match is guaranteed
                        if 'mapped_plex_title' in item:
                             found_items.append(r)
                             break
                        else:
                            # title match - verify the year is close (within 1 year)
                            r_year = r.year if r.year else 0
                            if r_year in [year, year-1, year+1]:
                                found_items.append(r)
                                break
                except: pass
        
        found_items = list(set(found_items))

        # Sync or append.
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

            # Guardrail: bulk add limit to avoid Plex rate limits.
            if len(to_add) > 1000:
                return False, f"Aborted: Attempted to add {len(to_add)} items. Limit is 1000."

            if to_add: existing_col.addItems(to_add)
            if to_remove: existing_col.removeItems(to_remove)
                
            action = "Synced (Strict)" if mode == 'sync' else "Appended"
            msg = f"{action} '{preset['title']}': Added {len(to_add)}, Removed {len(to_remove)}."
            write_log("SUCCESS", "Sync", msg, app_obj=app_obj)
            return True, msg

    except Exception as e:
        write_log("ERROR", "Sync", f"Collection sync failed: {str(e)}", app_obj=app_obj)
        return False, "Collection sync failed. Please check the logs for details."
    
    finally:
        # Release lock.
        remove_system_lock()
        
def is_duplicate(tmdb_item, plex_raw_titles, settings=None):
    # Simple title match check.
    tmdb_title = tmdb_item.get('title') if tmdb_item.get('media_type') == 'movie' else tmdb_item.get('name')
    if not tmdb_title: return False
    
    norm = normalize_title(tmdb_title)
    return norm in plex_raw_titles

# Helpers
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
        
        # TV shows are trickier - need to figure out which seasons to request
        if media_type == 'tv':
            seasons = []
            base_url = settings.overseerr_url.rstrip('/')
            
            # try overseerr first to see what seasons are available
            try:
                media_url = f"{base_url}/api/v1/tv/{tmdb_id}"
                media_resp = requests.get(media_url, headers=headers, timeout=5)
                if media_resp.status_code == 200:
                    media_data = media_resp.json()
                    # overseerr status codes: 1=available, 2=partial, 3=unavailable, 4=requested, 5=pending
                    # only request seasons that aren't unavailable
                    for season in media_data.get('seasons', []):
                        season_num = season.get('seasonNumber', 0)
                        status = season.get('status', 0)
                        # skip specials (season 0) and unavailable seasons
                        if season_num > 0 and status != 3:
                            seasons.append(season_num)
            except Exception as e:
                # if overseerr doesn't have it, fall back to TMDB
                if settings.tmdb_key:
                    try:
                        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={settings.tmdb_key}"
                        data = requests.get(url, timeout=4).json()
                        for s in data.get('seasons', []):
                            season_num = s.get('season_number', 0)
                            if season_num > 0:
                                seasons.append(season_num)
                    except:
                        pass
            
            # If still no seasons, can't request.
            if not seasons:
                return False, "No seasons available to request (all seasons may already be available, requested, or unavailable)"
            
            payload['seasons'] = seasons

        base_url = settings.overseerr_url.rstrip('/')
        url = f"{base_url}/api/v1/request"
        
        print(f"Sending to Overseerr: {url} | Payload: {payload}", flush=True)
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if r.status_code in [200, 201]:
            return True, "Success"
            
        try:
            error_data = r.json()
            error_msg = error_data.get('message', error_data.get('error', r.text))
            # Log full response for debugging.
            if media_type == 'tv':
                print(f"Overseerr TV request error: {error_data}", flush=True)
        except:
            error_msg = f"HTTP Error {r.status_code}: {r.text[:200]}"

        # Friendly error messages.
        error_lower = str(error_msg).lower()
        if "already available" in error_lower:
            return False, "Already Available"
        if "already requested" in error_lower:
            return False, "Already Requested"
        if "no seasons" in error_lower or "seasons available" in error_lower:
            return False, "No seasons available to request (all seasons may already be in your library or requested)"
            
        return False, f"Overseerr: {error_msg}"

    except Exception as e:
        write_log("ERROR", "Overseerr", f"Connection error: {str(e)}")
        return False, "Connection error. Please check your Overseerr URL and API key."
        
def check_for_updates(current_version, url):
    try:
        # github requires a user-agent header
        resp = requests.get(url, headers={'User-Agent': 'SeekAndWatch'}, timeout=3)
        
        if resp.status_code == 200:
            # try parsing as JSON first (github API format)
            try:
                data = resp.json()
                if 'tag_name' in data:
                    remote = data['tag_name'].lstrip('v').strip()
                    local = current_version.lstrip('v').strip()
                    
                    if remote != local:
                        return remote
            except:
                pass

            # fallback: regex search in the raw file (for older releases)
            match = re.search(r'VERSION\s*=\s*"([^"]+)"', resp.text)
            if match:
                remote = match.group(1).lstrip('v').strip()
                local = current_version.lstrip('v').strip()
                if remote != local:
                    return remote
                    
    except Exception as e:
        print(f"Update Check Error: {e}")
        
    return None

def handle_lucky_mode(settings):
    try:
        random_genre = random.choice([28, 35, 18, 878, 27, 53]) 
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={settings.tmdb_key}&with_genres={random_genre}&sort_by=popularity.desc&page={random.randint(1, 10)}"
        data = requests.get(url, timeout=10).json().get('results', [])
        
        random.shuffle(data)
        
        movies = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in data]
        
        return movies
            
    except: pass
    return None

# backup/restore functions
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
    # Force filename to be just the name, preventing absolute path overrides.
    filename = os.path.basename(filename)
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return False, "Invalid backup filename"

    filepath = os.path.abspath(os.path.join(BACKUP_DIR, filename))
    root = os.path.abspath(BACKUP_DIR)
    if os.path.commonpath([root, filepath]) != root:
        return False, "Invalid backup path"
    if not os.path.exists(filepath): return False, "File not found"
    try:
        target_dir = "/config"
        
        # Validate it's actually a zip file.
        if not zipfile.is_zipfile(filepath):
            return False, "Invalid backup file (not a ZIP archive)"
        
        with zipfile.ZipFile(filepath, 'r') as zipf:
            # Check for required files.
            members = zipf.namelist()
            if not members:
                return False, "Backup file is empty"
            
            # Normalize member paths (remove leading slashes, handle subdirectories).
            normalized_members = {}
            for member in members:
                # Skip directories.
                if member.endswith('/'):
                    continue
                
                # Remove leading slashes and normalize.
                clean_member = member.lstrip('/').replace('\\', '/')
                
                # Handle files in subdirectories by extracting the filename.
                if '/' in clean_member:
                    # Backups may have different structures.
                    base_name = os.path.basename(clean_member)
                    # Only allow known backup files.
                    if base_name not in ['seekandwatch.db', 'plex_cache.json']:
                        continue
                    normalized_members[base_name] = member
                else:
                    # File at root.
                    if clean_member in ['seekandwatch.db', 'plex_cache.json']:
                        normalized_members[clean_member] = member
            
            if not normalized_members:
                return False, "Backup file does not contain seekandwatch.db or plex_cache.json"
            
            # Extract files to target directory.
            for target_name, zip_member in normalized_members.items():
                # Security check: ensure we're not escaping the target directory.
                abs_target = os.path.abspath(os.path.join(target_dir, target_name))
                abs_root = os.path.abspath(target_dir)
                
                if not abs_target.startswith(abs_root + os.sep) and abs_target != abs_root:
                    return False, f"Security check failed for {target_name}"
                
                # Extract the file.
                with zipf.open(zip_member) as source:
                    target_path = os.path.join(target_dir, target_name)
                    with open(target_path, 'wb') as target:
                        target.write(source.read())
            
        return True, "Restored"
    except zipfile.BadZipFile:
        return False, "Invalid or corrupted ZIP file"
    except Exception as e:
        write_log("ERROR", "Restore Backup", f"Restore failed: {str(e)}")
        return False, "Backup restoration failed. Please check the logs for details."

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
        if parsed.scheme not in ('http', 'https'):
            return False, "Invalid protocol (only HTTP/HTTPS allowed)"
        
        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname"
            
        # resolve all IPs for this host
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except:
            return False, "Could not resolve hostname"

        # check all resolved IPs
        for res in addr_info:
            family, socktype, proto, canonname, sockaddr = res
            ip_str = sockaddr[0]
            
            if not ip_str: continue

            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            # block dangerous IPs
            if ip.is_loopback:
                return False, f"Access to Loopback ({ip_str}) is denied."
            
            if ip.is_link_local:
                return False, f"Access to Link-Local ({ip_str}) is denied."
            
            if ip.is_multicast:
                return False, "Access to Multicast is denied."
                
            if str(ip) == "0.0.0.0" or str(ip) == "::":
                return False, "Access to 0.0.0.0/:: is denied."

        # allow private IPs (for self-hosted setups)
        
        return True, "OK"
        
    except Exception as e:
        write_log("ERROR", "URL Validation", f"Validation error: {str(e)}")
        return False, "Invalid URL format. Please check your configuration."
        
def prefetch_tv_states_parallel(items, api_key):
    # Fetch TV show status (ended/returning/canceled).
    if not items: return

    tv_items = [i for i in items if i.get('media_type') == 'tv']
    if not tv_items: return

    def fetch_status(item):
        try:
            url = f"https://api.themoviedb.org/3/tv/{item['id']}?api_key={api_key}"
            data = requests.get(url, timeout=2).json()
            return {'id': item['id'], 'status': data.get('status', 'Unknown')}
        except:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_status, tv_items)
        
    status_map = {r['id']: r['status'] for r in results if r}
    
    for item in items:
        if item['id'] in status_map:
            item['status'] = status_map[item['id']]
            
def prefetch_ratings_parallel(items, api_key):
    # Fetch content ratings (PG-13, etc).
    if not items: return

    def fetch_rating(item):
        if 'content_rating' in item: return None

        try:
            m_type = item.get('media_type', 'movie')
            subset = 'release_dates' if m_type == 'movie' else 'content_ratings'
            url = f"https://api.themoviedb.org/3/{m_type}/{item['id']}/{subset}?api_key={api_key}"
            
            data = requests.get(url, timeout=2).json()
            results = data.get('results', [])
            
            rating = "NR"
            # find US rating
            for r in results:
                if r.get('iso_3166_1') == 'US':
                    if m_type == 'movie':
                        dates = r.get('release_dates', [])
                        for d in dates:
                            if d.get('certification'):
                                rating = d.get('certification')
                                break
                    else:
                        rating = r.get('rating')
                    break
            
            if not rating or rating == '': rating = "NR"
            
            return {'id': item['id'], 'rating': rating}
        except:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_rating, items)
        
    rating_map = {r['id']: r['rating'] for r in results if r}
    
    for item in items:
        item['content_rating'] = rating_map.get(item['id'], 'NR')

def get_tautulli_trending(media_type='movie', days=30):
    # get top 5 trending from tautulli
    try:
        s = Settings.query.first()
        if not s or not s.tautulli_url or not s.tautulli_api_key:
            return []

        stat_id = 'popular_movies' if media_type == 'movie' else 'popular_tv'
        
        # validate days parameter
        try:
            days = int(days)
            if days < 1: days = 1
            if days > 365: days = 365
        except:
            days = 30
        
        url = f"{s.tautulli_url.rstrip('/')}/api/v2?apikey={s.tautulli_api_key}&cmd=get_home_stats&time_range={days}&stats_count=10"
        resp = requests.get(url, timeout=5)
        data = resp.json()

        trending_items = []
        
        for block in data.get('response', {}).get('data', []):
            if block.get('stat_id') == stat_id:
                for row in block.get('rows', []):
                    rating_key = row.get('rating_key')
                    
                    # resolve to TMDB via plex
                    try:
                        plex = PlexServer(s.plex_url, s.plex_token)
                        item = plex.fetchItem(rating_key)
                        
                        tmdb_id = None
                        for guid in item.guids:
                            if 'tmdb://' in guid.id:
                                tmdb_id = guid.id.split('//')[1]
                                break
                        
                        if tmdb_id:
                            tmdb_resp = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}", timeout=10).json()
                            trending_items.append({
                                'title': row.get('title'),
                                'poster_path': tmdb_resp.get('poster_path'),
                                'tmdb_id': tmdb_id,
                                'media_type': media_type
                            })
                    except:
                        continue
                break
                
        return trending_items[:5]

    except Exception as e:
        print(f"Tautulli Error: {e}")
        return []
        
# Updater helpers

def is_docker():
    """Checks if we are running inside a Docker container."""
    path = '/proc/self/cgroup'
    return (
        os.path.exists('/.dockerenv') or
        (os.path.isfile(path) and any('docker' in line for line in open(path)))
    )

def is_unraid():
    """Tries to detect if we're running on Unraid (checks env vars and paths)."""
    if os.environ.get('UNRAID_VERSION') or os.environ.get('UNRAID_API_KEY'):
        return True
    if os.path.exists('/etc/unraid-version'):
        return True
    if os.path.exists('/boot/config') or os.path.exists('/usr/local/emhttp'):
        return True
    return False

def is_git_repo():
    """Checks if .git exists in app dir or /config."""
    app_dir = get_app_root()
    return os.path.isdir(os.path.join(app_dir, '.git')) or os.path.isdir('/config/.git')

def get_app_root():
    """Figures out where the app code actually lives."""
    env_root = os.environ.get("APP_DIR")
    if env_root and os.path.isdir(env_root):
        return env_root
    if os.path.isdir("/config/app"):
        return "/config/app"
    return os.path.dirname(os.path.abspath(__file__))

def is_app_dir_writable():
    """Checks if we can write to the app directory (needed for updates)."""
    app_dir = get_app_root()
    return os.path.isdir(app_dir) and os.access(app_dir, os.W_OK)

def _validate_path(path, allowed_dirs, description="path"):
    """
    Validate that a path is within allowed directories and doesn't contain traversal.
    
    Args:
        path: Path to validate
        allowed_dirs: List of allowed directory prefixes
        description: Description for error messages
        
    Returns:
        tuple: (is_valid: bool, normalized_path: str or None, error_message: str or None)
    """
    if not path:
        return False, None, f"Invalid {description}: path is empty"
    
    # make it absolute so we can compare properly
    abs_path = os.path.abspath(path)
    
    # check for .. attempts (path traversal)
    normalized_path = path.replace('\\', '/')
    normalized_abs = abs_path.replace('\\', '/')
    if '..' in normalized_path or '..' in normalized_abs or '/../' in normalized_abs or normalized_abs.endswith('/..'):
        return False, None, f"Invalid {description}: path traversal detected"
    
    # make sure it's actually inside one of the allowed directories
    for allowed in allowed_dirs:
        allowed_abs = os.path.abspath(allowed)
        try:
            # Check if the path is within the allowed directory
            common = os.path.commonpath([allowed_abs, abs_path])
            if common == allowed_abs:
                return True, abs_path, None
        except ValueError:
            # Paths on different drives (Windows) or invalid
            continue
    
    return False, None, f"Invalid {description}: path outside allowed directories"

def _copy_tree(src, dst):
    """
    Copies a directory tree safely - validates paths to prevent traversal attacks.
    """
    # only allow copying from temp directories (for updates)
    allowed_src_dirs = []
    temp_dir = tempfile.gettempdir()
    if temp_dir:
        allowed_src_dirs.append(temp_dir)
    # Add common temp directories if they exist
    for temp_path in ['/tmp', '/var/tmp']:
        if os.path.exists(temp_path) and temp_path not in allowed_src_dirs:
            allowed_src_dirs.append(temp_path)
    
    # only allow copying to these directories
    allowed_dst_dirs = ['/config', '/config/app']
    app_root = get_app_root()
    if app_root and app_root not in allowed_dst_dirs:
        allowed_dst_dirs.append(app_root)
    
    # Validate source path
    src_valid, src_abs, src_error = _validate_path(src, allowed_src_dirs, "source")
    if not src_valid:
        raise ValueError(f"Copy tree validation failed: {src_error}")
    
    # Validate destination path
    dst_valid, dst_abs, dst_error = _validate_path(dst, allowed_dst_dirs, "destination")
    if not dst_valid:
        raise ValueError(f"Copy tree validation failed: {dst_error}")
    
    # Ensure source exists and is a directory
    if not os.path.isdir(src_abs):
        raise ValueError(f"Source path is not a directory: {src_abs}")
    
    # Perform the copy with additional safety checks
    for root, dirs, files in os.walk(src_abs):
        rel = os.path.relpath(root, src_abs)
        target_dir = dst_abs if rel == "." else os.path.join(dst_abs, rel)
        
        # Additional safety: ensure target_dir is still within allowed destination
        target_abs = os.path.abspath(target_dir)
        if not any(target_abs.startswith(os.path.abspath(d) + os.sep) or target_abs == os.path.abspath(d) 
                   for d in allowed_dst_dirs):
            raise ValueError(f"Path traversal detected in copy operation: {target_dir}")
        
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            # Validate filename doesn't contain path traversal
            if '..' in name or '/' in name or '\\' in name:
                continue  # Skip suspicious filenames
            src_file = os.path.join(root, name)
            dst_file = os.path.join(target_dir, name)
            shutil.copy2(src_file, dst_file)

def perform_git_update():
    """
    Updates a git install - pulls latest code and reinstalls requirements.
    Has security checks to prevent path traversal attacks.
    """
    try:
        # only allow updates from these directories
        allowed_cwd_dirs = ['/config', '/config/app']
        app_root = get_app_root()
        if app_root and app_root not in allowed_cwd_dirs:
            allowed_cwd_dirs.append(app_root)
        
        # figure out where the git repo is
        cwd = None
        if os.path.isdir('/config/.git'):
            cwd = '/config'
        elif app_root and os.path.isdir(os.path.join(app_root, '.git')):
            cwd = app_root
        
        # make sure the directory is safe
        if cwd:
            cwd_valid, cwd_abs, cwd_error = _validate_path(cwd, allowed_cwd_dirs, "working directory")
            if not cwd_valid:
                return False, f"Security validation failed: {cwd_error}"
            cwd = cwd_abs
        
        # Additional check: ensure .git directory exists in validated path
        if cwd and not os.path.isdir(os.path.join(cwd, '.git')):
            return False, "Git repository validation failed: .git directory not found"
            
        # 1) Fetch latest changes.
        subprocess.check_call(['git', 'fetch'], cwd=cwd, shell=False)
        
        # 2) Hard reset to the remote default branch.
        subprocess.check_call(['git', 'reset', '--hard', 'origin/main'], cwd=cwd, shell=False)
        
        # 3) Reinstall requirements if needed.
        req_path = 'requirements.txt'
        if cwd: 
            req_path = os.path.join(cwd, 'requirements.txt')
        
        # Validate req_path is within allowed directories and is actually requirements.txt
        if os.path.exists(req_path):
            req_valid, req_abs, req_error = _validate_path(req_path, allowed_cwd_dirs, "requirements file")
            if not req_valid:
                return False, f"Security validation failed: {req_error}"
            
            # Ensure it's actually named requirements.txt (not a symlink or renamed file)
            if os.path.basename(req_abs) != 'requirements.txt':
                return False, "Security validation failed: requirements file name mismatch"
            
            # Ensure it's a regular file (not a directory or symlink)
            if not os.path.isfile(req_abs):
                return False, "Security validation failed: requirements path is not a file"
            
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', req_abs], shell=False)
             
        return True, "Update Successful! Restarting..."
    except Exception as e:
        write_log("ERROR", "Git Update", f"Update failed: {str(e)}")
        return False, "Git update failed. Please check the logs for details."

def perform_release_update():
    """
    Downloads the latest release zip from github and extracts it.
    Used for non-git installs.
    """
    try:
        app_dir = get_app_root()
        if not is_app_dir_writable():
            return False, "App directory is not writable. Mount the repo or rebuild the image."

        api_url = "https://api.github.com/repos/softerfish/seekandwatch/releases/latest"
        headers = {"User-Agent": "SeekAndWatch"}
        resp = requests.get(api_url, headers=headers, timeout=10)
        if not resp.ok:
            return False, f"GitHub release lookup failed: {resp.status_code}"

        data = resp.json()
        archive_url = data.get("zipball_url") or data.get("tarball_url")
        if not archive_url:
            return False, "GitHub release archive URL not found."

        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = os.path.join(tmpdir, "release.zip")
            with requests.get(archive_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(archive_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)

            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmpdir)

            extracted = [p for p in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, p))]
            if not extracted:
                return False, "Release archive did not contain files."

            release_root = os.path.join(tmpdir, extracted[0])
            _copy_tree(release_root, app_dir)

        req_path = os.path.join(app_dir, "requirements.txt")
        if os.path.exists(req_path):
            # Validate requirements.txt path
            allowed_dirs = ['/config', '/config/app']
            if app_dir not in allowed_dirs:
                allowed_dirs.append(app_dir)
            
            req_valid, req_abs, req_error = _validate_path(req_path, allowed_dirs, "requirements file")
            if not req_valid:
                return False, f"Security validation failed: {req_error}"
            
            # Ensure it's actually named requirements.txt
            if os.path.basename(req_abs) != 'requirements.txt':
                return False, "Security validation failed: requirements file name mismatch"
            
            # Ensure it's a regular file
            if not os.path.isfile(req_abs):
                return False, "Security validation failed: requirements path is not a file"
            
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_abs], shell=False)

        return True, "Release Update Successful! Restarting..."
    except Exception as e:
        write_log("ERROR", "Release Update", f"Update failed: {str(e)}")
        return False, "Release update failed. Please check the logs for details."