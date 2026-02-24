"""Helper functions and utilities used throughout the app."""

import concurrent.futures
import logging
import datetime
import difflib
import ipaddress
import json
import math
import os
import platform
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
from urllib.parse import urlencode, urlparse

import requests
import socket
from urllib.parse import urlparse
from flask import flash, redirect, url_for, session, render_template, has_app_context, current_app
from plexapi.server import PlexServer
from werkzeug.utils import secure_filename

from config import (
    CLOUD_URL,
    CONFIG_DIR,
    get_backup_dir,
    get_cache_file,
    get_database_path,
    get_lock_file,
    get_scanner_log_file,
    get_results_cache_file,
    get_history_cache_file,
)
from models import db, CollectionSchedule, SystemLog, Settings, TmdbAlias, TmdbKeywordCache, TmdbRuntimeCache, RadarrSonarrCache
from presets import PLAYLIST_PRESETS, TMDB_GENRE_MAP, TMDB_STUDIO_MAP

log = logging.getLogger(__name__)


def get_cloud_base_url(settings=None):
    """Moved to services.CloudService.CloudService"""
    from services.CloudService import CloudService
    return CloudService.get_cloud_base_url(settings)


# Configuration (from config module so env override works)
BACKUP_DIR = get_backup_dir()
CACHE_FILE = get_cache_file()
LOCK_FILE = get_lock_file()
SCANNER_LOG_FILE = get_scanner_log_file()
RESULTS_CACHE_FILE = get_results_cache_file()
HISTORY_CACHE_FILE = get_history_cache_file()
CUSTOM_POSTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'custom_posters')

# in-memory caches (also persisted to disk)
RESULTS_CACHE = {}
HISTORY_CACHE = {}
TMDB_REC_CACHE = {}
TMDB_REC_CACHE_LOCK = threading.Lock()

RESULTS_CACHE_TTL = 60 * 60 * 24
HISTORY_CACHE_TTL = 60 * 60
TMDB_REC_CACHE_TTL = 60 * 60 * 24

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR, exist_ok=True)

def _now_ts():
    return int(time.time())

def _load_cache_file(path, ttl):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.loads(f.read())
    except Exception as e:
        log.debug("Load cache %s: %s", path, e)
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
    except Exception as e:
        log.warning("Save cache %s: %s", path, e)

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
        results = entry.get('results')
        # treat empty list as cache miss so we refetch / try similar endpoint
        if not results:
            TMDB_REC_CACHE.pop(key, None)
            return None
        return results

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
    try:
        min_year = int(session.get('min_year', 0))
    except (TypeError, ValueError):
        min_year = 0

    try:
        min_rating = float(session.get('min_rating', 0))
    except (TypeError, ValueError):
        min_rating = 0

    genre = session.get('genre_filter')
    genre_filter = genre if genre and genre != 'all' else None

    critic_enabled = session.get('critic_filter') == 'true'
    try:
        threshold = int(session.get('critic_threshold', 70))
    except (TypeError, ValueError):
        threshold = 70
    
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
            try:
                cached_map[row.tmdb_id] = json.loads(row.keywords)
            except (TypeError, ValueError):
                cached_map[row.tmdb_id] = []
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
        except Exception as e:
            write_log("warning", "Utils", f"TMDB keywords fetch failed ({type(e).__name__})")
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
                limit = s.keyword_cache_size or 3000
                
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
    except Exception as e:
        write_log("warning", "Utils", f"Keyword cache lookup failed ({type(e).__name__})")
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
                except (TypeError, ValueError):
                    rt_score = 0
                break
        return {'id': item.get('id'), 'rt_score': rt_score}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_rt, items)

    rt_map = {r['id']: r['rt_score'] for r in results if r and r.get('id')}
    for item in items:
        if item.get('id') in rt_map:
            item['rt_score'] = rt_map[item['id']]

def prefetch_runtime_parallel(items, api_key):
    """Fetch runtime from TMDB in parallel with database caching."""
    if not api_key or not items:
        return
    
    # Only fetch for movies that don't already have runtime
    movies_to_fetch = [item for item in items if item.get('media_type') == 'movie' and not item.get('runtime')]
    
    if not movies_to_fetch:
        # Set default for TV shows
        for item in items:
            if item.get('media_type') == 'tv' and not item.get('runtime'):
                item['runtime'] = 0
        return
    
    # Check database cache first
    target_ids = [item['id'] for item in movies_to_fetch]
    cached_runtimes = {}
    try:
        existing = TmdbRuntimeCache.query.filter(TmdbRuntimeCache.tmdb_id.in_(target_ids)).all()
        for row in existing:
            cached_runtimes[row.tmdb_id] = row.runtime
    except Exception as e:
        print(f"Runtime cache read error: {e}")
    
    # Apply cached values
    for item in movies_to_fetch:
        if item['id'] in cached_runtimes:
            item['runtime'] = cached_runtimes[item['id']]
    
    # Only fetch what's not cached
    needs_fetch = [item for item in movies_to_fetch if item['id'] not in cached_runtimes]
    
    if not needs_fetch:
        # All were cached, just set TV defaults
        for item in items:
            if item.get('media_type') == 'tv' and not item.get('runtime'):
                item['runtime'] = 0
        return
    
    def fetch_runtime(item):
        """Fetch runtime for a single movie with better error handling."""
        try:
            url = f"https://api.themoviedb.org/3/movie/{item['id']}?api_key={api_key}"
            response = requests.get(url, timeout=5)
            
            # Handle rate limits (429)
            if response.status_code == 429:
                time.sleep(1)  # Wait and retry once
                response = requests.get(url, timeout=5)
            
            if response.status_code != 200:
                return {'id': item.get('id'), 'runtime': 0}
            
            data = response.json()
            runtime = data.get('runtime', 0)
            return {'id': item.get('id'), 'runtime': runtime}
        except requests.exceptions.Timeout:
            return {'id': item.get('id'), 'runtime': 0}
        except requests.exceptions.RequestException:
            return {'id': item.get('id'), 'runtime': 0}
        except (KeyError, ValueError):
            return {'id': item.get('id'), 'runtime': 0}
        except Exception as e:
            print(f"Unexpected error fetching runtime for {item.get('id')}: {e}")
            return {'id': item.get('id'), 'runtime': 0}
    
    # Fetch with rate limiting (5 workers to avoid hitting TMDB limits)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_runtime, needs_fetch))
    
    # Update items and save to cache
    new_entries = []
    for result in results:
        if result and result.get('id'):
            item_id = result['id']
            runtime = result.get('runtime', 0)
            
            # Update item
            for item in items:
                if item.get('id') == item_id:
                    item['runtime'] = runtime
                    break
            
            # Save to cache (only if successful and runtime > 0)
            if runtime > 0:
                new_entries.append(TmdbRuntimeCache(
                    tmdb_id=item_id,
                    media_type='movie',
                    runtime=runtime
                ))
    
    # Bulk save to database
    if new_entries:
        try:
            db.session.bulk_save_objects(new_entries)
            db.session.commit()
            
            # Prune cache if it exceeds the limit (global runtime cache; no request context)
            try:
                s = Settings.query.first()
                if s:
                    limit = s.runtime_cache_size or 3000
                    total = TmdbRuntimeCache.query.count()
                    if total > limit:
                        excess = total - limit
                        subq = db.session.query(TmdbRuntimeCache.id).order_by(TmdbRuntimeCache.timestamp.asc()).limit(excess).subquery()
                        db.session.query(TmdbRuntimeCache).filter(TmdbRuntimeCache.id.in_(db.session.query(subq.c.id))).delete(synchronize_session=False)
                        db.session.commit()
            except Exception as e:
                print(f"Error pruning runtime cache: {e}")
                db.session.rollback()
        except Exception as e:
            print(f"Error saving runtime cache: {e}")
            db.session.rollback()
    
    # Set default for TV shows
    for item in items:
        if item.get('media_type') == 'tv' and not item.get('runtime'):
            item['runtime'] = 0

load_results_cache()
load_history_cache()
    
# logging functions
def _sanitize_log_message(msg):
    """Redact URLs and common secret patterns from log messages to avoid leaking credentials."""
    if msg is None:
        return ""
    s = str(msg)
    if not s:
        return s
    import re
    # Redact URL-like strings (may contain tokens, API keys)
    s = re.sub(r'https?://[^\s\'"]+', '[URL redacted]', s)
    s = re.sub(r'(password|token|api_key|apikey|secret)=[^\s&]+', r'\1=[REDACTED]', s, flags=re.I)
    return s


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
    # Actual logging logic. Sanitize message to avoid logging URLs/tokens.
    s = Settings.query.first()
    if s and (s.logging_enabled or level == 'error'):
        log = SystemLog(level=level, category=module, message=_sanitize_log_message(message))
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
                db.session.add(SystemLog(level="warn", category="System", message=f"Logs exceeded {limit_mb}MB. Pruned {to_delete} oldest entries."))
                db.session.commit()

def write_scanner_log(message):
    """Writes scanner messages to a file, rotates if it gets too big."""
    try:
        # import here to avoid circular dependency issues (no request context; first user's limit)
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
                except Exception as e:
                    log.warning("Rotate scanner log: %s", e)

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
    except Exception as e:
        log.warning("Read scanner log: %s", e)
        return "Error reading logs."

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
    
    # Convert common number words to digits for better matching
    # This helps match "Fantastic Four" with "Fantastic 4"
    number_words = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'ten': '10', 'eleven': '11', 'twelve': '12', 'thirteen': '13',
        'fourteen': '14', 'fifteen': '15', 'sixteen': '16', 'seventeen': '17',
        'eighteen': '18', 'nineteen': '19', 'twenty': '20'
    }
    for word, num in number_words.items():
        # Match whole words only (with word boundaries)
        t = re.sub(r'\b' + word + r'\b', num, t)
    
    # Strip leading "the " to handle "The Fantastic 4" vs "Fantastic Four"
    t = re.sub(r'^the\s+', '', t)
    
    # Strip non-alphanumeric.
    return re.sub(r'[^a-z0-9]', '', t)

# alias/title matching stuff
def get_tmdb_aliases(tmdb_id, media_type, settings):
    try:
        cached = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=media_type).first()
        if cached:
            return json.loads(cached.aliases)
    except Exception as e:
        write_log("warning", "Utils", f"Alias cache lookup failed ({type(e).__name__})")
        pass

    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/alternative_titles?api_key={settings.tmdb_key}"
        data = requests.get(url, timeout=3).json()
        
        key = 'titles' if 'titles' in data else 'results'
        aliases = [normalize_title(x['title']) for x in data.get(key, [])]
        
        # could store aliases here but we mainly just need the ID match
        # (the alias DB handles the rest)

        return aliases
    except Exception as e:
        write_log("warning", "Utils", f"get_tmdb_aliases failed ({type(e).__name__})")
        return []

def sync_remote_aliases():
    return True, "Started in background"

def run_alias_scan(app_obj):
    """No-op. Plex library is indexed by sync_plex_library (Sync library now / Plex library sync), not by the old plex_cache.json + alias scan."""
    return

# lock file stuff (prevents multiple operations from running at once)
def is_system_locked():
    return os.path.exists(LOCK_FILE)

def set_system_lock(status_msg="Busy"):
    try:
        with open(LOCK_FILE, 'w') as f:
            json.dump({'stage': status_msg}, f)
        return True
    except Exception as e:
        write_log("warning", "Utils", f"Lock status write failed ({type(e).__name__})")
        return False

def remove_system_lock():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except OSError as e:
            write_log("warning", "Utils", f"Could not remove lock file ({type(e).__name__})")

def get_lock_status():
    if not os.path.exists(LOCK_FILE):
        return {'running': False}
    try:
        with open(LOCK_FILE, 'r') as f:
            data = json.load(f)
            return {'running': True, 'progress': data.get('stage', 'Busy')}
    except Exception as e:
        write_log("warning", "Utils", f"Lock progress read failed ({type(e).__name__})")
        return {'running': True, 'progress': 'Unknown'}

# Plex guid -> TMDB resolution (like web: TMDB guid, then IMDB, then TVDB, then title+year)
def _plex_guid_str_to_tmdb_id(guid_str):
    """Extract TMDB id from a Plex guid string. Returns int or None."""
    if not guid_str:
        return None
    s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
    if not s or 'tmdb' not in s.lower():
        return None
    m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', s) or re.search(r'themoviedb\.org/\?/(?:movie|tv(?:\/show)?)/(\d+)', s) or re.search(r'tmdb://(\d+)', s) or re.search(r'com\.plexapp\.agents\.themoviedb://(\d+)', s)
    if m:
        return int(m.group(1))
    return None

def _plex_guid_str_parse_imdb(guid_str):
    """Extract IMDb id (tt1234567) from a Plex guid string. Returns str or None."""
    if not guid_str:
        return None
    s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
    m = re.search(r'imdb://(tt\d+)', s, re.I) or re.search(r'com\.plexapp\.agents\.imdb://(tt\d+)', s, re.I)
    return m.group(1) if m else None

def _plex_guid_str_parse_tvdb(guid_str):
    """Extract TVDB id from a Plex guid string. Returns int or None."""
    if not guid_str:
        return None
    s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
    m = re.search(r'tvdb://(\d+)', s) or re.search(r'com\.plexapp\.agents\.thetvdb://(\d+)', s)
    return int(m.group(1)) if m else None

def _plex_imdb_to_tmdb(imdb_id, media_type, tmdb_key):
    """Resolve IMDb id to TMDB id via TMDB find API. media_type 'movie' or 'tv'."""
    if not imdb_id or not re.match(r'^tt\d+$', str(imdb_id).strip(), re.I):
        return None
    if not (tmdb_key and str(tmdb_key).strip()):
        return None
    try:
        url = f"https://api.themoviedb.org/3/find/{imdb_id.strip()}?external_source=imdb_id&api_key={tmdb_key.strip()}"
        r = requests.get(url, timeout=10)
        if not r.ok:
            return None
        data = r.json()
        mt = 'movie' if media_type == 'movie' else 'tv'
        if mt == 'movie' and data.get('movie_results'):
            return int(data['movie_results'][0]['id'])
        if mt == 'tv' and data.get('tv_results'):
            return int(data['tv_results'][0]['id'])
        mr = (data.get('movie_results') or [{}])[0].get('id')
        tr = (data.get('tv_results') or [{}])[0].get('id')
        if media_type == 'movie' and mr:
            return int(mr)
        if media_type in ('tv', 'show') and tr:
            return int(tr)
        return int(mr) if mr else (int(tr) if tr else None)
    except Exception as e:
        log.debug("IMDB->TMDB: %s", e)
        return None

# In-memory cache for TVDB->TMDB to avoid repeated API calls in one sync run
_TVDB_TMDB_CACHE = {}
def _plex_tvdb_to_tmdb(tvdb_id, media_type, tmdb_key):
    """Resolve TVDB id to TMDB id via TMDB find API. Uses in-memory cache."""
    tvdb_id = int(tvdb_id) if tvdb_id is not None else 0
    if tvdb_id <= 0 or not (tmdb_key and str(tmdb_key).strip()):
        return None
    key = (tvdb_id, media_type)
    if key in _TVDB_TMDB_CACHE:
        return _TVDB_TMDB_CACHE[key]
    try:
        url = f"https://api.themoviedb.org/3/find/{tvdb_id}?external_source=tvdb_id&api_key={tmdb_key.strip()}"
        r = requests.get(url, timeout=10)
        if not r.ok:
            _TVDB_TMDB_CACHE[key] = None
            return None
        data = r.json()
        mt = 'movie' if media_type == 'movie' else 'tv'
        if mt == 'movie' and data.get('movie_results'):
            _TVDB_TMDB_CACHE[key] = int(data['movie_results'][0]['id'])
            return _TVDB_TMDB_CACHE[key]
        if mt == 'tv' and data.get('tv_results'):
            _TVDB_TMDB_CACHE[key] = int(data['tv_results'][0]['id'])
            return _TVDB_TMDB_CACHE[key]
        mr = (data.get('movie_results') or [{}])[0].get('id')
        tr = (data.get('tv_results') or [{}])[0].get('id')
        out = int(mr) if (media_type == 'movie' and mr) else (int(tr) if (media_type in ('tv', 'show') and tr) else (int(mr) if mr else (int(tr) if tr else None)))
        _TVDB_TMDB_CACHE[key] = out
        return out
    except Exception as e:
        log.debug("TVDB->TMDB: %s", e)
        _TVDB_TMDB_CACHE[key] = None
        return None

def _plex_title_year_to_tmdb(title, year, media_type, tmdb_key):
    """Resolve title + year to TMDB id via TMDB search API. Returns int or None."""
    title = (title or '').strip()
    if not title or not (tmdb_key and str(tmdb_key).strip()):
        return None
    mt = 'tv' if media_type in ('tv', 'show') else 'movie'
    year_param = ''
    if year and re.match(r'^\d{4}$', str(year).strip()):
        y = int(str(year).strip())
        year_param = f"&year={y}" if mt == 'movie' else f"&first_air_date_year={y}"
    try:
        endpoint = 'search/movie' if mt == 'movie' else 'search/tv'
        url = f"https://api.themoviedb.org/3/{endpoint}?api_key={tmdb_key.strip()}&query={requests.utils.quote(title)}{year_param}&page=1"
        r = requests.get(url, timeout=10)
        if not r.ok:
            return None
        data = r.json()
        results = data.get('results') or []
        if not results:
            return None
        return int(results[0]['id'])
    except Exception as e:
        log.debug("Title/year->TMDB: %s", e)
        return None

def sync_plex_library(app_obj):
    """Sync Plex library to TMDB index (TmdbAlias). First run clears old DB and plex_cache.json. Uses guids then IMDB/TVDB/title+year resolution like web.
    Works with both direct URLs (e.g. http://192.168.1.50:32400) and Plex relay (.plex.direct) URLs; local IP is usually faster and more reliable."""
    if is_system_locked():
        return False, "Another task is running. Please wait and try again."

    print("--- STARTING PLEX LIBRARY SYNC (TMDB INDEX) ---")

    with app_obj.app_context():
        settings = Settings.query.first()
        if not settings or not settings.plex_url or not settings.plex_token:
            return False, "Plex not configured."
        if not (getattr(settings, 'tmdb_key', None) and str(settings.tmdb_key).strip()):
            return False, "TMDB API key required to sync library (Settings -> APIs)."

        write_log("info", "Plex", "Started Plex library sync (TMDB index).", app_obj=app_obj)
        set_system_lock("Syncing Plex library...")
        start_time = time.time()

        # Only clear on first run (migration from old way): never completed this sync before
        last_sync = getattr(settings, 'last_alias_scan', None) or 0
        if last_sync == 0:
            try:
                TmdbAlias.query.delete()
                db.session.commit()
                if os.path.exists(CACHE_FILE):
                    try:
                        os.remove(CACHE_FILE)
                    except OSError:
                        pass
                write_log("info", "Plex", "Cleared TmdbAlias for fresh sync (first run / migration).", app_obj=app_obj)
            except Exception as e:
                write_log("warning", "Plex", f"Clear before sync: {e}", app_obj=app_obj)
                db.session.rollback()

        max_resolve_per_run = 200  # cap IMDB/TVDB/title+year API calls per sync
        resolve_count = 0
        _TVDB_TMDB_CACHE.clear()

        try:
            plex = PlexServer(settings.plex_url, settings.plex_token)
            tmdb_key = settings.tmdb_key.strip()
            added = 0
            sections = plex.library.sections()

            for section in sections:
                if section.type not in ('movie', 'show'):
                    continue
                want_type = 'movie' if section.type == 'movie' else 'tv'
                set_system_lock(f"Scanning {section.title}...")

                for item in section.all():
                    try:
                        title = getattr(item, 'title', None) or ''
                        year = getattr(item, 'year', None) or 0
                        orig = getattr(item, 'originalTitle', None) or ''
                        guids = getattr(item, 'guids', None) or []

                        tmdb_id = None
                        # 1) TMDB from guid
                        for g in guids:
                            tmdb_id = _plex_guid_str_to_tmdb_id(g)
                            if tmdb_id:
                                break
                        # 2) IMDB -> TMDB
                        if not tmdb_id and resolve_count < max_resolve_per_run:
                            for g in guids:
                                imdb_id = _plex_guid_str_parse_imdb(g)
                                if imdb_id:
                                    resolve_count += 1
                                    tmdb_id = _plex_imdb_to_tmdb(imdb_id, want_type, tmdb_key)
                                    if tmdb_id:
                                        break
                                    time.sleep(0.3)
                        # 3) TVDB -> TMDB
                        if not tmdb_id and resolve_count < max_resolve_per_run:
                            for g in guids:
                                tvdb_id = _plex_guid_str_parse_tvdb(g)
                                if tvdb_id:
                                    resolve_count += 1
                                    tmdb_id = _plex_tvdb_to_tmdb(tvdb_id, want_type, tmdb_key)
                                    if tmdb_id:
                                        break
                                    time.sleep(0.3)
                        # 4) Title + year search
                        if not tmdb_id and title and resolve_count < max_resolve_per_run:
                            resolve_count += 1
                            tmdb_id = _plex_title_year_to_tmdb(title, year, want_type, tmdb_key)
                            time.sleep(0.3)

                        if tmdb_id and tmdb_id > 0:
                            norm_title = normalize_title(title) if title else ''
                            norm_orig = normalize_title(orig) if orig else norm_title
                            existing = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=want_type).first()
                            if not existing:
                                db.session.add(TmdbAlias(
                                    tmdb_id=tmdb_id,
                                    media_type=want_type,
                                    plex_title=title or None,
                                    original_title=norm_orig or None,
                                    match_year=int(year) if year else None
                                ))
                                added += 1
                        else:
                            # Placeholder so we don't keep retrying
                            if title:
                                norm_title = normalize_title(title)
                                if not TmdbAlias.query.filter_by(tmdb_id=-1, plex_title=norm_title).first():
                                    db.session.add(TmdbAlias(tmdb_id=-1, media_type='unknown', plex_title=norm_title))

                        if added % 50 == 0 and added:
                            db.session.commit()
                    except Exception as e:
                        log.debug("Sync item: %s", e)
                        continue

            db.session.commit()
            settings.last_alias_scan = int(time.time())
            db.session.commit()
            duration = round(time.time() - start_time, 2)
            total = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).count()
            msg = f"Sync completed in {duration}s. Indexed {total} items (TMDB)."
            print(f"--- {msg} ---")
            write_log("success", "Plex", msg, app_obj=app_obj)
            return True, msg

        except Exception:
            db.session.rollback()
            write_log("error", "Plex", "Plex library sync failed. Please check your Plex URL and Token in Settings.")
            return False, "Sync failed. Check application logs."
        finally:
            remove_system_lock()

def refresh_radarr_sonarr_cache(app_obj):
    """Moved to services.IntegrationsService.IntegrationsService"""
    from services.IntegrationsService import IntegrationsService
    return IntegrationsService.refresh_radarr_sonarr_cache(app_obj)


def get_radarr_sonarr_cache(media_type=None):
    """Moved to services.IntegrationsService.IntegrationsService"""
    from services.IntegrationsService import IntegrationsService
    return IntegrationsService.get_radarr_sonarr_cache(media_type)


def get_owned_tmdb_ids_for_cloud():
    """Build lists of owned movie and TV TMDB IDs (Radarr/Sonarr cache with has_file + Plex alias table) for Cloud sync.
    Used so SeekAndWatch Cloud can show 'Already in library' and hide those from friends. Returns (movie_ids, tv_ids)."""
    movie_ids = set()
    tv_ids = set()
    try:
        for media_type, id_set in [('movie', movie_ids), ('tv', tv_ids)]:
            cache = get_radarr_sonarr_cache(media_type)
            id_set.update(cache.get('tmdb_ids') or [])
        # Plex-originated: TmdbAlias has tmdb_id for items found in Plex (alias scan)
        for row in TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).all():
            mid = getattr(row, 'tmdb_id', None)
            mtype = getattr(row, 'media_type', None)
            if mid and mtype == 'movie':
                movie_ids.add(mid)
            elif mid and mtype == 'tv':
                tv_ids.add(mid)
    except Exception as e:
        log.debug("Get owned IDs: %s", e)
    return (list(movie_ids), list(tv_ids))


def owned_list_hash_for_cloud(movie_ids, tv_ids):
    """Canonical SHA-256 hash of owned movie + TV TMDB IDs for cloud sync.
    Same format as cloud (sorted comma-joined movies, pipe, sorted comma-joined tv)."""
    import hashlib
    movies_part = ','.join(str(x) for x in sorted(movie_ids))
    tv_part = ','.join(str(x) for x in sorted(tv_ids))
    payload = movies_part + '|' + tv_part
    return hashlib.sha256(payload.encode()).hexdigest()


def get_collection_visibility(server, section_id, rating_key):
    """Moved to services.CollectionService.CollectionService"""
    from services.CollectionService import CollectionService
    return CollectionService.get_collection_visibility(server, section_id, rating_key)


def apply_collection_visibility(plex_collection, visible_home=False, visible_library=False, visible_friends=False):
    """Moved to services.CollectionService.CollectionService"""
    from services.CollectionService import CollectionService
    return CollectionService.apply_collection_visibility(plex_collection, visible_home, visible_library, visible_friends)


def _get_plex_tmdb_id(plex_item):
    """Moved to services.CollectionService.CollectionService"""
    from services.CollectionService import CollectionService
    return CollectionService._get_plex_tmdb_id(plex_item)


def run_collection_logic(settings, preset, key, app_obj=None):
    """Moved to services.CollectionService.CollectionService"""
    from services.CollectionService import CollectionService
    return CollectionService.run_collection_logic(settings, preset, key, app_obj)


def is_duplicate(tmdb_item, plex_raw_titles, settings=None):
    # Simple title match check.
    tmdb_title = tmdb_item.get('title') if tmdb_item.get('media_type') == 'movie' else tmdb_item.get('name')
    if not tmdb_title: return False
    
    norm = normalize_title(tmdb_title)
    return norm in plex_raw_titles

def is_owned_item(tmdb_item, media_type):
    """
    Check if a TMDB item is already owned in Plex (TmdbAlias from sync) or Radarr/Sonarr.
    Uses TMDB index (TmdbAlias) and Radarr/Sonarr cache only.
    """
    tmdb_id = tmdb_item.get('id')
    if not tmdb_id:
        return False

    # Check Radarr/Sonarr cache first (fastest check)
    try:
        radarr_sonarr_cache = get_radarr_sonarr_cache(media_type)
        if tmdb_id in radarr_sonarr_cache['tmdb_ids']:
            return True
    except Exception as e:
        write_log("warning", "Utils", f"Radarr/Sonarr cache tmdb check failed ({type(e).__name__})")
        pass

    # Check TmdbAlias (Plex library sync index)
    alias = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=media_type).first()
    if alias and alias.tmdb_id > 0:
        return True

    # Also check if any alias has a matching original_title (handles title variants)
    tmdb_title = tmdb_item.get('title') if media_type == 'movie' else tmdb_item.get('name')
    if tmdb_title:
        norm_tmdb_title = normalize_title(tmdb_title)
        matching_alias = TmdbAlias.query.filter_by(
            original_title=norm_tmdb_title,
            media_type=media_type
        ).filter(TmdbAlias.tmdb_id > 0).first()
        if matching_alias:
            return True

    # Radarr/Sonarr cache by title
    if tmdb_title:
        try:
            radarr_sonarr_cache = get_radarr_sonarr_cache(media_type)
            if normalize_title(tmdb_title) in radarr_sonarr_cache['titles']:
                return True
        except Exception as e:
            write_log("warning", "Utils", f"Radarr/Sonarr cache title check failed ({type(e).__name__})")
            pass

    return False

# Helpers
def fetch_omdb_ratings(title, year, api_key):
    # OMDb fetch removed to prevent API limit issues.
    # We now rely on Plex's internal metadata for critic ratings.
    return []

def prefetch_omdb_parallel(items, api_key):
    # OMDb prefetch removed.
    pass
    
def send_overseerr_request(settings, media_type, tmdb_id, uid=None):
    """Moved to services.IntegrationsService.IntegrationsService"""
    from services.IntegrationsService import IntegrationsService
    return IntegrationsService.send_overseerr_request(settings, media_type, tmdb_id, uid)
        
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
            except Exception:
                # response may be raw file (e.g. app.py) not JSON; fallback to regex below
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
        url = f"https://api.themoviedb.org/3/discover/movie?api_key={settings.tmdb_key}&with_genres={random_genre}&page={random.randint(1, 10)}"
        data = requests.get(url, timeout=10).json().get('results', [])
        
        random.shuffle(data)
        
        movies = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in data]
        
        return movies

    except Exception as e:
        write_log("warning", "Utils", f"handle_lucky_mode failed ({type(e).__name__})")
    return None

# backup/restore functions
def create_backup():
    filename = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    filepath = os.path.join(BACKUP_DIR, filename)
    
    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        db_path = get_database_path()
        if os.path.exists(db_path):
            zipf.write(db_path, arcname='seekandwatch.db')
        # Plex "owned" index is now in TmdbAlias (DB); no longer backing up plex_cache.json
            
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
        except OSError as e:
            write_log("warning", "Utils", f"list_backups stat failed ({type(e).__name__}): {f}")
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
        target_dir = CONFIG_DIR

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
                    # File at root. plex_cache.json allowed for old backups but not required
                    if clean_member in ['seekandwatch.db', 'plex_cache.json']:
                        normalized_members[clean_member] = member

            if 'seekandwatch.db' not in normalized_members:
                return False, "Backup file does not contain seekandwatch.db"
            
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
            
        # Signal all workers to reopen the DB (multi-worker: only the restoring worker disposed).
        _db_restored_flag = os.path.join(CONFIG_DIR, '.seekandwatch_db_restored')
        try:
            open(_db_restored_flag, 'w').close()
            # Remove flag after a delay so every worker gets a request and disposes; then we stop checking.
            def _remove_flag_later():
                time.sleep(30)
                try:
                    if os.path.exists(_db_restored_flag):
                        os.remove(_db_restored_flag)
                except OSError:
                    pass
            t = threading.Thread(target=_remove_flag_later, daemon=True)
            t.start()
        except OSError:
            pass
        return True, "Restored"
    except zipfile.BadZipFile:
        return False, "Invalid or corrupted ZIP file"
    except Exception:
        write_log("error", "Restore Backup", "Restore failed")
        return False, "Backup restoration failed. Please check the logs for details."

def prune_backups(days=7):
    if not os.path.exists(BACKUP_DIR): return
    cutoff = time.time() - (days * 86400)
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith('.zip'): continue
        path = os.path.join(BACKUP_DIR, f)
        if os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
            except OSError as e:
                write_log("warning", "Utils", f"Prune backup remove failed ({type(e).__name__}): {path}")

def reset_stuck_locks():
    """
    Called on startup.
    Deletes any stale 'cache.lock' files from the config folder.
    """
    lock_file = LOCK_FILE
    
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
        except (socket.gaierror, OSError) as e:
            return False, f"Could not resolve hostname ({type(e).__name__})"

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
                # Plex relay (*.plex.direct) can resolve to 0.0.0.0/:: on some systems; allow it
                if hostname and hostname.lower().endswith('.plex.direct'):
                    continue
                return False, "Access to 0.0.0.0/:: is denied."

        # allow private IPs (for self-hosted setups)
        
        return True, "OK"
        
    except Exception:
        write_log("error", "URL Validation", "Validation error")
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
        except Exception as e:
            write_log("warning", "Utils", f"Overseerr status fetch failed ({type(e).__name__})")
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
        except Exception as e:
            write_log("warning", "Utils", f"OMDB rating fetch failed ({type(e).__name__})")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_rating, items)
        
    rating_map = {r['id']: r['rating'] for r in results if r}
    
    for item in items:
        item['content_rating'] = rating_map.get(item['id'], 'NR')

def get_tautulli_trending(media_type='movie', days=30, settings=None):
    # get top 5 trending from tautulli (caller should pass settings for user isolation)
    try:
        s = settings or Settings.query.first()
        if not s or not s.tautulli_url or not s.tautulli_api_key:
            return []

        stat_id = 'popular_movies' if media_type == 'movie' else 'popular_tv'
        
        # validate days parameter
        try:
            days = int(days)
            if days < 1: days = 1
            if days > 365: days = 365
        except (ValueError, TypeError):
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
                    except Exception as e:
                        write_log("warning", "Utils", f"Tautulli history item failed ({type(e).__name__})")
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
    try:
        if os.path.exists('/.dockerenv'):
            return True
        if os.path.isfile(path):
            with open(path, 'r') as f:
                return any('docker' in line for line in f)
    except Exception as e:
        log.debug("Docker check: %s", e)
    return False

def is_unraid():
    """Detect if this is an Unraid App Store install (so we disable one-click updater and show "update via App Store").
    
    Revised Logic:
    - If .git folder exists and is writable, we are running from source (manual install), so allow updates regardless of OS.
    - Only flag as "Unraid App Store" if explicitly marked via env vars (set by template) AND we are not a git repo.
    """
    # if we are a git repo, we are NOT a locked-down App Store container.
    # we allow manual git pulls even on Unraid if the user mapped the volume.
    if is_git_repo():
        return False

    # check for explicit Unraid App Store markers
    if os.environ.get('SEEKANDWATCH_UNRAID') or os.environ.get('SEEKANDWATCH_SOURCE') == 'unraid':
        return True
    
    # check for injected Unraid paths (only if not git repo)
    if os.path.exists('/etc/unraid-version'):
        return True
        
    return False

def is_git_repo():
    """Checks if .git exists in app dir or config dir."""
    app_dir = get_app_root()
    return os.path.isdir(os.path.join(app_dir, '.git')) or os.path.isdir(os.path.join(CONFIG_DIR, '.git'))

def get_app_root():
    """Figures out where the app code actually lives."""
    env_root = os.environ.get("APP_DIR")
    if env_root and os.path.isdir(env_root):
        return env_root
    app_subdir = os.path.join(CONFIG_DIR, "app")
    if os.path.isdir(app_subdir):
        return app_subdir
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

def validate_url_safety(url):
    """
    Validates that a URL is safe to fetch (SSRF protection).
    Blocks localhost, private IPs, and AWS metadata.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname: return False, None
        
        # Block schemes other than http/https
        if parsed.scheme not in ('http', 'https'):
            return False, None
            
        # Check against blacklist
        blacklist = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
        if hostname.lower() in blacklist:
            return False, None
            
        # Resolve hostname to IP
        try:
            ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            return False, None # Can't resolve, safer to block
            
        # Check private IP ranges
        import ipaddress
        ip_addr = ipaddress.ip_address(ip)
        if ip_addr.is_loopback or ip_addr.is_private or ip_addr.is_link_local:
            return False, None
            
        # Block AWS metadata specifically (169.254.169.254)
        if str(ip_addr) == "169.254.169.254":
            return False, None
            
        return True, ip
    except Exception:
        return False, None

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
    allowed_dst_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
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
        allowed_cwd_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
        app_root = get_app_root()
        if app_root and app_root not in allowed_cwd_dirs:
            allowed_cwd_dirs.append(app_root)
        
        # figure out where the git repo is
        cwd = None
        if os.path.isdir(os.path.join(CONFIG_DIR, '.git')):
            cwd = CONFIG_DIR
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
        write_log("error", "Git Update", f"Update failed: {type(e).__name__}")
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
            allowed_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
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
        write_log("error", "Release Update", f"Update failed: {type(e).__name__}")
        return False, "Release update failed. Please check the logs for details."

# SeekAndWatch cloud - helpers for *arr API (root + quality, no cross-import from api)
def _arr_root_and_quality(base_url, headers):
    """Fetch first root folder path and first quality profile id from *arr. Returns (root_path, quality_id, None) or (None, None, error_msg)."""
    try:
        rf_resp = requests.get(f"{base_url}/api/v3/rootfolder", headers=headers, timeout=5)
        rf_data = rf_resp.json()
        rf_list = rf_data if isinstance(rf_data, list) else (rf_data.get('records', rf_data.get('data', [])) if isinstance(rf_data, dict) else [])
        if not rf_list or not isinstance(rf_list[0], dict):
            return None, None, "No root folders configured."
        root_path = rf_list[0].get('path')
        if not root_path:
            return None, None, "Could not get root folder path."
        qp_resp = requests.get(f"{base_url}/api/v3/qualityprofile", headers=headers, timeout=5)
        qp_data = qp_resp.json()
        qp_list = qp_data if isinstance(qp_data, list) else (qp_data.get('records', qp_data.get('data', [])) if isinstance(qp_data, dict) else [])
        if not qp_list or not isinstance(qp_list[0], dict):
            return None, None, "No quality profiles configured."
        quality_id = qp_list[0].get('id')
        if quality_id is None:
            return None, None, "Could not get quality profile id."
        return root_path, quality_id, None
    except Exception:
        return None, None, "Request failed"

def _arr_language_profile(base_url, headers):
    """Fetch first language profile id from Sonarr. Returns (language_id, None) or (None, error_msg)."""
    try:
        lp_resp = requests.get(f"{base_url}/api/v3/languageprofile", headers=headers, timeout=5)
        lp_data = lp_resp.json()
        lp_list = lp_data if isinstance(lp_data, list) else (lp_data.get('records', lp_data.get('data', [])) if isinstance(lp_data, dict) else [])
        if not lp_list or not isinstance(lp_list[0], dict):
            return None, "No language profiles configured."
        lang_id = lp_list[0].get('id')
        if lang_id is None:
            return None, "Could not get language profile id."
        return lang_id, None
    except Exception:
        return None, "Request failed"

def send_to_radarr_sonarr(settings, media_type, tmdb_id):
    """Moved to services.IntegrationsService.IntegrationsService"""
    from services.IntegrationsService import IntegrationsService
    return IntegrationsService.send_to_radarr_sonarr(settings, media_type, tmdb_id)


def send_to_overseerr(settings, media_type, tmdb_id):
    """Moved to services.IntegrationsService.IntegrationsService"""
    from services.IntegrationsService import IntegrationsService
    return IntegrationsService.send_to_overseerr(settings, media_type, tmdb_id)