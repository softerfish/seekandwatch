"""API endpoints for async stuff - AJAX calls, background tasks, etc."""

import datetime
import json
import os
import random
import re
import subprocess
import threading
import time
import tempfile
import zipfile
from datetime import timedelta

import requests
import socket
from urllib.parse import urlparse, quote, quote_plus
from flask import Blueprint, request, jsonify, session, send_from_directory, current_app
from flask_login import login_required, current_user
from flask_limiter.util import get_remote_address
from plexapi.server import PlexServer
from markupsafe import escape
from werkzeug.utils import secure_filename
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User, AppRequest
from utils import (
    normalize_title,
    is_duplicate,
    is_owned_item,
    fetch_omdb_ratings,
    send_overseerr_request,
    run_collection_logic,
    create_backup,
    list_backups,
    restore_backup,
    prune_backups,
    BACKUP_DIR,
    sync_remote_aliases,
    get_tmdb_aliases,
    refresh_plex_cache,
    get_plex_cache,
    refresh_radarr_sonarr_cache,
    get_radarr_sonarr_cache,
    get_lock_status,
    is_system_locked,
    write_scanner_log,
    read_scanner_log,
    write_log,
    prefetch_keywords_parallel,
    item_matches_keywords,
    RESULTS_CACHE,
    save_results_cache,
    get_session_filters,
    validate_url,
    prefetch_tv_states_parallel,
    prefetch_ratings_parallel,
    prefetch_omdb_parallel,
    score_recommendation,
)
from presets import PLAYLIST_PRESETS

# set up the API blueprint
api_bp = Blueprint('api', __name__)

# rate limiter gets set from app.py after registration
limiter = None

def rate_limit_decorator(limit_str):
    """Decorator for rate limiting API endpoints."""
    def decorator(func):
        if limiter:
            return limiter.limit(limit_str, key_func=get_remote_address)(func)
        return func
    return decorator

def _log_api_exception(context, exc):
    try:
        # keep logs readable: one short line, no raw api responses or tracebacks
        msg = str(exc).strip() if exc else ""
        if len(msg) > 300:
            msg = msg[:297] + "..."
        if msg and "\n" in msg:
            msg = msg.split("\n")[0].strip()
        line = f"{context} failed" + (f" - {msg}" if msg else "")
        write_log("error", "API", line)
    except Exception:
        current_app.logger.exception(context)

def _error_response(message="Request failed"):
    return jsonify({'status': 'error', 'message': message})

def _error_payload(message="Request failed"):
    return jsonify({'error': message})

def _safe_backup_path(filename):
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return None
    root = os.path.abspath(BACKUP_DIR)
    full = os.path.abspath(os.path.join(root, safe_name))
    if os.path.commonpath([root, full]) != root:
        return None
    return full

# recommendation loading and filtering

@api_bp.route('/load_more_recs')
@login_required
def load_more_recs():
    # nothing cached yet, return empty
    if current_user.id not in RESULTS_CACHE: return jsonify([])
    
    cache = RESULTS_CACHE[current_user.id]
    candidates = cache.get('candidates', [])
    start_idx = cache.get('next_index', 0)
    # only sort if not already sorted and not shuffled
    # if sorted=False, it means they were shuffled and should stay that way
    if candidates and cache.get('sorted') is None:
        for item in candidates:
            if item.get('score') is None:
                item['score'] = score_recommendation(item)
        candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
        cache['sorted'] = True
        save_results_cache()
    
    s = current_user.settings
    min_year, min_rating, genre_filter, critic_enabled, threshold = get_session_filters()
    
    # get content rating filter from session (G, PG, etc)
    allowed_ratings = session.get('rating_filter', [])
    # if empty or 'all', don't filter by rating
    if not allowed_ratings or 'all' in allowed_ratings: allowed_ratings = None
    
    # parse keywords (pipe-separated)
    raw_keywords = session.get('keywords', '')
    target_keywords = [k.strip() for k in raw_keywords.split('|') if k.strip()]
    
    batch_end = min(start_idx + 100, len(candidates))
    
    batch_items = candidates[start_idx:batch_end]
    # prefetch ratings so the UI doesn't lag when rendering
    prefetch_ratings_parallel(batch_items, s.tmdb_key)
    if s.omdb_key and critic_enabled:
        prefetch_omdb_parallel(batch_items, s.omdb_key)
    
    # Fetch runtime for movies (TV shows have episode runtime, not series runtime)
    def fetch_runtime(item):
        """Fetch runtime from TMDB for a single item."""
        if item.get('runtime'):  # Already have it
            return
        if item.get('media_type') != 'movie':  # Only fetch for movies
            item['runtime'] = 0  # TV shows use episode runtime
            return
        try:
            url = f"https://api.themoviedb.org/3/movie/{item['id']}?api_key={s.tmdb_key}"
            data = requests.get(url, timeout=5).json()
            item['runtime'] = data.get('runtime', 0)  # Runtime in minutes
        except Exception as e:
            # Runtime fetch failures are non-critical, log as warning
            write_log("warning", "API", f"Failed to fetch runtime for item: {str(e)}")
            item['runtime'] = 0
    
    # Fetch runtime in parallel for movies
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(fetch_runtime, batch_items)
    
    if target_keywords:
        prefetch_keywords_parallel(batch_items, s.tmdb_key)
    else:
        # keywords not critical, fetch them in background
        from flask import current_app
        def async_prefetch(app_obj, items, key):
            with app_obj.app_context():
                prefetch_keywords_parallel(items, key)
                
        threading.Thread(target=async_prefetch, 
                         args=(current_app._get_current_object(), batch_items, s.tmdb_key)).start()
    
    final_list = []
    idx = start_idx
    
    # Get runtime filter from session
    max_runtime = session.get('max_runtime', 9999)
    if not max_runtime or max_runtime >= 9999:
        max_runtime = 9999
    
    # keep filtering until we have 30 items or run out
    while len(final_list) < 30 and idx < len(candidates):
        item = candidates[idx]
        idx += 1
        
        # basic filters
        if item['year'] < min_year: continue
        if item.get('vote_average', 0) < min_rating: continue
        
        # runtime filter
        if max_runtime < 9999:
            item_runtime = item.get('runtime', 9999)
            if item_runtime > max_runtime: continue
        
        # content rating filter (for kid-friendly mode)
        if allowed_ratings:
            c_rate = item.get('content_rating', 'NR')
            if str(c_rate) not in allowed_ratings: continue
            
        if genre_filter and genre_filter != 'all':
            try:
                # Handle old format where it was a single int vs list.
                allowed_ids = [int(g) for g in genre_filter] if isinstance(genre_filter, list) else [int(genre_filter)]
                item_genres = item.get('genre_ids', [])
                if not any(gid in allowed_ids for gid in item_genres): 
                    continue
            except: pass
            
        if target_keywords:
            if not item_matches_keywords(item, target_keywords):
                continue

        # grab rotten tomatoes score if we have OMDB key
        item['rt_score'] = None
        if s.omdb_key:
            if item.get('rt_score') is None and critic_enabled:
                ratings = fetch_omdb_ratings(item.get('title', item.get('name')), item['year'], s.omdb_key)
                rt_score = 0
                for r in (ratings or []):
                    if r['Source'] == 'Rotten Tomatoes':
                        rt_score = int(r['Value'].replace('%',''))
                        break
                if rt_score > 0:
                    item['rt_score'] = rt_score
            if critic_enabled and (item.get('rt_score') or 0) < threshold:
                continue
            
        final_list.append(item)

    # TV shows need status (ended/returning) for display.
    if final_list and final_list[0].get('media_type') == 'tv':
        prefetch_tv_states_parallel(final_list, s.tmdb_key)
        
    RESULTS_CACHE[current_user.id]['next_index'] = idx
    save_results_cache()
    return jsonify(final_list)

@api_bp.route('/api/update_filters', methods=['POST'])
@login_required
def update_filters():
    data = request.json
    try: session['min_year'] = int(data.get('min_year', 0))
    except: session['min_year'] = 0
        
    try: session['min_rating'] = float(data.get('min_rating', 0))
    except: session['min_rating'] = 0
    
    # Runtime filter
    try: 
        max_runtime = int(data.get('max_runtime', 9999))
        session['max_runtime'] = max_runtime if max_runtime > 0 else 9999
    except: 
        session['max_runtime'] = 9999
        
    genre_filter = data.get('genre_filter')
    if isinstance(genre_filter, list):
        safe_genres = []
        for g in genre_filter:
            g_str = str(g)
            if g_str.isdigit():
                safe_genres.append(g_str)
        session['genre_filter'] = safe_genres
    elif isinstance(genre_filter, str):
        session['genre_filter'] = genre_filter if genre_filter == 'all' or genre_filter.isdigit() else None
    else:
        session['genre_filter'] = None

    keywords = data.get('keywords', '')
    session['keywords'] = str(escape(keywords)) if isinstance(keywords, str) else ''

    rating_filter = data.get('rating_filter', [])
    if isinstance(rating_filter, list):
        safe_ratings = []
        for r in rating_filter:
            r_str = str(r).strip()
            if re.fullmatch(r"[A-Za-z0-9\-]+", r_str or ""):
                safe_ratings.append(r_str)
        session['rating_filter'] = safe_ratings
    else:
        session['rating_filter'] = []
    
    # Reset pagination when filters change.
    if current_user.id in RESULTS_CACHE:
        RESULTS_CACHE[current_user.id]['next_index'] = 0
        
    return jsonify({'status': 'success'})

@api_bp.route('/tmdb_search_proxy')
@login_required
def tmdb_search_proxy():
    s = current_user.settings
    q = request.args.get('query', '').strip()
    search_type = request.args.get('type', 'movie')
    if not q:
        return jsonify({'results': []})
    if len(q) > 100:
        return jsonify({'results': []})
    if search_type not in ['movie', 'tv', 'keyword']:
        return jsonify({'results': []})
    
    if search_type == 'keyword':
        # URL encode query to prevent injection
        safe_query = quote(q[:100])  # Limit length and encode
        url = f"https://api.themoviedb.org/3/search/keyword?query={safe_query}&api_key={s.tmdb_key}"
        try:
            res = requests.get(url, timeout=5).json().get('results', [])[:10]
            # Return as JSON (jsonify automatically escapes for JSON safety)
            return jsonify({'results': [{'id': k['id'], 'name': str(k.get('name', ''))} for k in res]})
        except Exception as e:
            _log_api_exception("tmdb_keyword_search", e)
            return jsonify({'results': []})
        
    ep = 'search/tv' if search_type == 'tv' else 'search/movie'
    # URL encode query to prevent injection
    safe_query = quote(q[:100])  # Limit length and encode
    res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={safe_query}&api_key={s.tmdb_key}", timeout=5).json().get('results', [])[:5]
    
    # Normalize response format for frontend (validate search_type to prevent XSS)
    # Return as JSON (jsonify automatically escapes for JSON safety)
    safe_type = 'tv' if search_type == 'tv' else 'movie'
    return jsonify({'results': [{
        'title': str(i.get('name', '') if safe_type == 'tv' else i.get('title', '')),
        'year': str((i.get('first_air_date') or i.get('release_date') or '')[:4]),
        'poster': str(i.get('poster_path', ''))
    } for i in res]})

# metadata and actions

@api_bp.route('/get_metadata/<media_type>/<int:tmdb_id>')
@login_required
def get_metadata(media_type, tmdb_id):
    s = current_user.settings
    try:
        # get everything in one API call (faster)
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}&append_to_response=credits,videos,watch/providers"
        data = requests.get(url, timeout=5).json()
        
        # just grab top 5 cast members
        cast = [c['name'] for c in data.get('credits', {}).get('cast', [])[:5]]
        
        # find a trailer (prefer official ones)
        trailer = None
        for v in data.get('videos', {}).get('results', []):
            if v['type'] == 'Trailer' and v['site'] == 'YouTube':
                trailer = v['key']
                break
        
        # if no official trailer, any youtube video works
        if not trailer:
             for v in data.get('videos', {}).get('results', []):
                if v['site'] == 'YouTube':
                    trailer = v['key']
                    break
                
        # streaming providers (default to US region)
        reg = (s.tmdb_region or 'US').split(',')[0]
        prov = data.get('watch/providers', {}).get('results', {}).get(reg, {}).get('flatrate', [])
        
        return jsonify({
            'title': data.get('title', data.get('name')),
            'year': (data.get('release_date') or data.get('first_air_date') or '')[:4],
            'overview': data.get('overview'),
            'poster_path': data.get('poster_path'),
            'cast': cast,
            'trailer_key': trailer,
            'providers': [{'name': p['provider_name'], 'logo': p['logo_path']} for p in prov]
        })
    except Exception as e:
        _log_api_exception("get_metadata", e)
        return _error_payload("Request failed")

@api_bp.route('/get_trailer/<media_type>/<int:tmdb_id>')
@login_required
def get_trailer(media_type, tmdb_id):
    s = current_user.settings
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/videos?api_key={s.tmdb_key}&language=en-US"
        results = requests.get(url, timeout=5).json().get('results', [])
        
        # look for official trailers first
        for vid in results:
            if vid['site'] == 'YouTube' and vid['type'] == 'Trailer':
                return jsonify({'status': 'success', 'key': vid['key']})
        
        # fallback to any youtube video
        for vid in results:
            if vid['site'] == 'YouTube':
                return jsonify({'status': 'success', 'key': vid['key']})
                
        return jsonify({'status': 'error', 'message': 'No trailer found'})
    except Exception as e:
        _log_api_exception("get_trailer", e)
        return _error_response("Request failed")

@api_bp.route('/request_media', methods=['POST'])
@login_required
def request_media():
    s = current_user.settings
    data = request.json
    try:
        # Bulk mode from import lists.
        if 'items' in data:
             success_count = 0
             last_error = ""
             
             for item in data['items']:
                 success, msg = send_overseerr_request(s, item['media_type'], item['tmdb_id'])
                 if success: success_count += 1
                 else: last_error = msg
             
             if success_count > 0:
                 return jsonify({'status': 'success', 'count': success_count})
             else:
                 return jsonify({'status': 'error', 'message': last_error or "All requests failed"})
        
        # single item request
        else:
             success, msg = send_overseerr_request(s, data['media_type'], data['tmdb_id'])
             if success:
                 return jsonify({'status': 'success'})
             else:
                 return jsonify({'status': 'error', 'message': msg})

    except Exception as e:
        _log_api_exception("request_media", e)
        return _error_response("Request failed")
        
@api_bp.route('/block_movie', methods=['POST'])
@login_required
def block_movie():
    if not request.json or 'title' not in request.json:
        return jsonify({'status': 'error', 'message': 'Title is required'}), 400
    title = request.json['title']
    media_type = request.json.get('media_type', 'movie')
    
    # Avoid duplicates.
    exists = Blocklist.query.filter_by(user_id=current_user.id, title=title, media_type=media_type).first()
    if not exists:
        db.session.add(Blocklist(user_id=current_user.id, title=title, media_type=media_type))
        db.session.commit()
    return {'status': 'success'}

@api_bp.route('/unblock_movie/<int:id>', methods=['POST'])
@login_required
def unblock_movie(id):
    # make sure users can only delete their own blocklist items
    Blocklist.query.filter_by(id=id, user_id=current_user.id).delete()
    db.session.commit()
    return {'status': 'success'}

# list import and collection stuff

@api_bp.route('/get_plex_libraries')
@login_required
def get_plex_libraries():
    s = current_user.settings
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        # only grab movie/TV libraries (ignore music, photos, etc)
        libs = [{'title': sec.title, 'type': sec.type, 'name': sec.title} for sec in plex.library.sections() if sec.type in ['movie', 'show']]
        return jsonify({'status': 'success', 'libraries': libs})
    except Exception as e:
        _log_api_exception("get_plex_libraries", e)
        return _error_response("Unable to connect to Plex")
        
@api_bp.route('/get_plex_collections')
@login_required
def get_plex_collections():
    s = current_user.settings
    if not s.plex_url or not s.plex_token:
        return jsonify({'status': 'error', 'message': 'Plex not configured'})
    
    try:
        plex = PlexServer(s.plex_url, s.plex_token, timeout=5)
        collections = []
        
        for section in plex.library.sections():
            if section.type in ['movie', 'show']:
                for col in section.collections():
                    # Use first item's poster if collection doesn't have one.
                    thumb = col.thumb
                    if not thumb and col.items():
                        thumb = col.items()[0].thumb
                        
                    collections.append({
                        'title': col.title,
                        'key': col.ratingKey,
                        'library': section.title,
                        'count': col.childCount,
                        'thumb': f"{s.plex_url}{thumb}?X-Plex-Token={s.plex_token}" if thumb else None,
                        'url': f"{s.plex_url}/web/index.html#!/server/{plex.machineIdentifier}/details?key={col.key}"
                    })
        
        collections.sort(key=lambda x: x['title'])
        
        return jsonify({'status': 'success', 'collections': collections})
        
    except Exception as e:
        print(f"Error fetching collections: {e}")
        _log_api_exception("get_plex_collections", e)
        return _error_response("Unable to fetch collections")

@api_bp.route('/match_bulk_titles', methods=['POST'])
@login_required
def match_bulk_titles():
    # Paste a list of titles and match them to Plex.
    s = current_user.settings
    data = request.json
    raw_text = data.get('titles', '')
    target_library = data.get('target_library')
    
    # Split on newlines, commas, pipes.
    titles = [x.strip() for x in re.split(r'[\n,|]', raw_text) if x.strip()]
    if not titles: return jsonify({'status': 'error', 'message': 'No titles found.'})
    
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        lib = plex.library.section(target_library)
        
        results = []
        # Limit to 100 so it doesn't hang.
        for t in titles[:100]:
            found = False
            key = None
            final_title = t
            
            try:
                # todo: add fuzzy matching for better results
                hits = lib.search(t)
                if hits:
                    found = True
                    key = hits[0].ratingKey
                    final_title = hits[0].title
            except: pass
            
            results.append({'query': t, 'title': final_title, 'found': found, 'key': key})
            
        return jsonify({'status': 'success', 'results': results})
    except Exception as e:
        _log_api_exception("match_bulk_titles", e)
        return _error_response("Request failed")

@api_bp.route('/create_bulk_collection', methods=['POST'])
@login_required
def create_bulk_collection():
    s = current_user.settings
    data = request.json
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        lib = plex.library.section(data['target_library'])
        keys = data['rating_keys']
        if not keys: return jsonify({'status': 'error', 'message': 'No items.'})
        
        # create collection using the first item
        first = lib.fetchItem(keys[0])
        col = first.addCollection(data['collection_title'])
        
        # add the rest of the items
        for k in keys[1:]:
            try: lib.fetchItem(k).addCollection(data['collection_title'])
            except: pass
            
        # save it as a custom preset so it shows up in the UI (store target_library for delete-from-Plex)
        key = f"custom_import_{int(time.time())}"
        config = {
            'title': data['collection_title'],
            'description': f"Imported Static List ({len(keys)} items)",
            'media_type': 'movie',
            'icon': '📋',
            'target_library': data.get('target_library', '')
        }
        
        db.session.add(CollectionSchedule(preset_key=key, frequency='manual', configuration=json.dumps(config)))
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': 'Collection Created'})
    except Exception as e:
        _log_api_exception("create_bulk_collection", e)
        return _error_response("Request failed")

@api_bp.route('/preview_preset_items/<key>')
@login_required
def preview_preset_items(key):
    s = current_user.settings
    preset = {}
    
    if key.startswith('custom_'):
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        if job and job.configuration:
            config = json.loads(job.configuration)
            params = config.get('tmdb_params', {})
            preset = {'media_type': config.get('media_type', 'movie'), 'tmdb_params': params}
    else:
        preset = PLAYLIST_PRESETS.get(key)
        
    if not preset: return jsonify({'status': 'error', 'message': 'Preset not found'})
    
    try:
        params = preset.get('tmdb_params', {}).copy()
        params['api_key'] = s.tmdb_key
        url = f"https://api.themoviedb.org/3/discover/{preset['media_type']}"
        
        owned_keys = get_plex_cache(s)
        items = []
        media_type = preset.get('media_type', 'movie')
        page = 1
        max_pages = 5  # Don't search forever, limit to 5 pages
        
        # Keep fetching pages until we have 12 unowned items or run out of pages
        while len(items) < 12 and page <= max_pages:
            params['page'] = page
            r = requests.get(url, params=params, timeout=5).json()
            results = r.get('results', [])
            
            if not results:
                break  # No more results
            
            for i in results:
                # Use comprehensive ownership check (checks aliases, titles, original titles, etc.)
                is_owned = is_owned_item(i, owned_keys, media_type)
                
                # Only add items that aren't owned
                if not is_owned:
                    items.append({
                        'title': i.get('title', i.get('name')),
                        'year': (i.get('release_date') or i.get('first_air_date') or '')[:4],
                        'poster_path': i.get('poster_path'),
                        'owned': False,
                        'tmdb_id': i.get('id')
                    })
                
                # Stop once we have 12 unowned items
                if len(items) >= 12:
                    break
            
            page += 1
        
        return jsonify({'status': 'success', 'items': items})
    except Exception as e:
        _log_api_exception("preview_preset_items", e)
        return _error_response("Request failed")

@api_bp.route('/create_collection/<key>', methods=['POST'])
@login_required
def create_collection(key):
    s = current_user.settings
    
    if key.startswith('custom_'):
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        preset = json.loads(job.configuration)
    else:
        preset = PLAYLIST_PRESETS.get(key, {}).copy()
        
        # Check for user overrides (sync mode, etc.).
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        if job and job.configuration:
            try: 
                user_config = json.loads(job.configuration)
                if 'sync_mode' in user_config:
                    preset['sync_mode'] = user_config['sync_mode']
            except: pass
            
    from flask import current_app
    success, msg = run_collection_logic(s, preset, key, app_obj=current_app._get_current_object())
    
    if success:
        # Update last run time.
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        if not job: 
            job = CollectionSchedule(preset_key=key)
            db.session.add(job)
        job.last_run = datetime.datetime.now()
        db.session.commit()
        return jsonify({'status': 'success', 'message': msg})
        
    return jsonify({'status': 'error', 'message': msg})

@api_bp.route('/schedule_collection', methods=['POST'])
@login_required
def schedule_collection():
    preset_key = request.form.get('preset_key')
    frequency = request.form.get('frequency')  # manual, daily, weekly
    sync_mode = request.form.get('sync_mode', 'append')

    job = CollectionSchedule.query.filter_by(preset_key=preset_key).first()
    if not job:
        job = CollectionSchedule(preset_key=preset_key)
        db.session.add(job)
    
    # Keep existing config, update only what changed.
    current_config = {}
    if job.configuration:
        try: current_config = json.loads(job.configuration)
        except: current_config = {}
            
    current_config['sync_mode'] = sync_mode
    
    job.frequency = frequency
    job.configuration = json.dumps(current_config)
    
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Schedule updated.'})

# custom collection builder

@api_bp.route('/preview_custom_collection', methods=['POST'])
@login_required
def preview_custom_collection():
    # test the filters before actually saving the collection
    s = current_user.settings
    data = request.json
    
    # convert UI form fields to TMDB API parameters
    params = {
        'api_key': s.tmdb_key,
        'sort_by': data['sort_by'],
        'vote_average.gte': data['min_rating'],
        'with_genres': data['with_genres'],
        'with_keywords': data.get('with_keywords', '')
    }
    
    # Date fields differ for movies vs TV.
    if data['year_start']:
        k = 'primary_release_date.gte' if data['media_type'] == 'movie' else 'first_air_date.gte'
        params[k] = f"{data['year_start']}-01-01"
    if data['year_end']:
        k = 'primary_release_date.lte' if data['media_type'] == 'movie' else 'first_air_date.lte'
        params[k] = f"{data['year_end']}-12-31"
    
    url = f"https://api.themoviedb.org/3/discover/{data['media_type']}"
    try:
        r = requests.get(url, params=params, timeout=5).json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'TMDB Error'})

    owned_keys = get_plex_cache(s)
    items = []
    
    for i in r.get('results', [])[:10]:
        t_clean = normalize_title(i.get('title', i.get('name')))
        is_owned = t_clean in owned_keys
        
        # Try alias match if title didn't work.
        if not is_owned:
            if TmdbAlias.query.filter_by(tmdb_id=i['id']).first():
                is_owned = True
        
        year = (i.get('release_date') or i.get('first_air_date') or '----')[:4]
        
        items.append({
            'text': f"{i.get('title', i.get('name'))} ({year})",
            'owned': is_owned,
            'tmdb_id': i['id'],
            'media_type': data['media_type']
        })
        
    return jsonify({'status': 'success', 'items': items})

@api_bp.route('/save_custom_collection', methods=['POST'])
@login_required
def save_custom_collection():
    data = request.json
    key = f"custom_{int(time.time())}"
    
    config = {
        'title': data['title'],
        'description': 'Custom Smart Collection',
        'media_type': data['media_type'],
        'tmdb_params': {
            'sort_by': data['sort_by'],
            'vote_average.gte': data['min_rating'],
            'with_genres': data['with_genres'],
            'with_keywords': data.get('with_keywords', '')
        }
    }
    
    if data['year_start']:
        k = 'primary_release_date.gte' if data['media_type'] == 'movie' else 'first_air_date.gte'
        config['tmdb_params'][k] = f"{data['year_start']}-01-01"
        
    db.session.add(CollectionSchedule(preset_key=key, frequency='manual', configuration=json.dumps(config)))
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/delete_custom_collection/<key>', methods=['POST'])
@login_required
def delete_custom_collection(key):
    job = CollectionSchedule.query.filter_by(preset_key=key).first()
    if not job:
        return jsonify({'status': 'error', 'message': 'Collection not found'}), 404

    # Load config before deleting from DB so we can remove from Plex
    config = {}
    if job.configuration:
        try:
            config = json.loads(job.configuration)
        except Exception:
            pass

    title = config.get('title') or 'Unknown'
    media_type = config.get('media_type', 'movie')
    target_library = config.get('target_library')  # set for imported lists

    # Delete from Plex if we have title and connection
    s = current_user.settings
    if s.plex_url and s.plex_token and title:
        try:
            plex = PlexServer(s.plex_url, s.plex_token, timeout=10)
            target_type = 'movie' if media_type == 'movie' else 'show'
            section = None
            if target_library:
                try:
                    section = plex.library.section(target_library)
                except Exception:
                    pass
            if not section:
                section = next((sec for sec in plex.library.sections() if sec.type == target_type), None)
            if section:
                try:
                    results = section.search(title=title, libtype='collection')
                    if results:
                        results[0].delete()
                except Exception as e:
                    _log_api_exception("delete_custom_collection_plex", e)
                    # still delete from DB; Plex failure is non-fatal
        except Exception as e:
            _log_api_exception("delete_custom_collection_plex_connect", e)

    CollectionSchedule.query.filter_by(preset_key=key).delete()
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Collection removed from SeekAndWatch and Plex'})

# system and settings stuff

@api_bp.route('/test_connection', methods=['POST'])
@login_required
def test_connection():
    data = request.json
    service = data.get('service')
    
    # validate URL to prevent SSRF attacks
    if 'url' in data and data['url']:
        is_safe, msg = validate_url(data['url'])
        if not is_safe:
            return jsonify({'status': 'error', 'message': f"Security Block: {msg}", 'msg': f"Security Block: {msg}"})

    try:
        # test each service type
        if service == 'plex':
            p = PlexServer(data['url'], data['token'], timeout=5)
            return jsonify({'status': 'success', 'message': f"Connected: {p.friendlyName}", 'msg': f"Connected: {p.friendlyName}"})
            
        elif service == 'tmdb':
            clean_key = data['api_key'].strip()
            r = requests.get(f"https://api.themoviedb.org/3/configuration?api_key={clean_key}", timeout=10)
            if r.status_code == 200: return jsonify({'status': 'success', 'message': 'TMDB Connected!', 'msg': 'TMDB Connected!'})
            return jsonify({'status': 'error', 'message': 'Invalid Key', 'msg': 'Invalid Key'})
            
        elif service == 'omdb':
            clean_key = data['api_key'].strip()
            r = requests.get(f"https://www.omdbapi.com/?apikey={clean_key}&t=Inception", timeout=10)
            if r.json().get('Response') == 'True': return jsonify({'status': 'success', 'message': 'OMDB Connected!', 'msg': 'OMDB Connected!'})
            return jsonify({'status': 'error', 'message': 'Invalid Key', 'msg': 'Invalid Key'})
            
        elif service == 'overseerr':
            r = requests.get(f"{data['url']}/api/v1/status", headers={'X-Api-Key': data['api_key']}, timeout=5)
            if r.status_code == 200: return jsonify({'status': 'success', 'message': 'Overseerr Connected!', 'msg': 'Overseerr Connected!'})
            return jsonify({'status': 'error', 'message': 'Connection Failed', 'msg': 'Connection Failed'})
            
        elif service == 'tautulli':
            r = requests.get(f"{data['url']}/api/v2?apikey={data['api_key']}&cmd=get_server_info", timeout=5)
            if r.status_code == 200: return jsonify({'status': 'success', 'message': 'Tautulli Connected!', 'msg': 'Tautulli Connected!'})
            return jsonify({'status': 'error', 'message': 'Connection Failed', 'msg': 'Connection Failed'})
            
        elif service == 'radarr':
            r = requests.get(f"{data['url']}/api/v3/system/status", headers={'X-Api-Key': data['api_key']}, timeout=5)
            if r.status_code == 200: return jsonify({'status': 'success', 'message': 'Radarr Connected!', 'msg': 'Radarr Connected!'})
            return jsonify({'status': 'error', 'message': 'Connection Failed', 'msg': 'Connection Failed'})
            
        elif service == 'sonarr':
            r = requests.get(f"{data['url']}/api/v3/system/status", headers={'X-Api-Key': data['api_key']}, timeout=5)
            if r.status_code == 200: return jsonify({'status': 'success', 'message': 'Sonarr Connected!', 'msg': 'Sonarr Connected!'})
            return jsonify({'status': 'error', 'message': 'Connection Failed', 'msg': 'Connection Failed'})
            
    except Exception as e:
        _log_api_exception("test_connection", e)
        return jsonify({'status': 'error', 'message': 'Connection failed', 'msg': 'Connection failed'})
        
        
@api_bp.route('/toggle_logging', methods=['POST'])
@login_required
def toggle_logging():
    s = current_user.settings
    s.logging_enabled = request.json.get('enabled', False)
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/clear_logs', methods=['POST'])
@login_required
def clear_logs():
    SystemLog.query.delete()
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/update_ignore_list', methods=['POST'])
@login_required
def update_ignore_list():
    users = request.json.get('ignored_users', [])
    s = current_user.settings
    s.ignored_users = ",".join(users)
    db.session.commit()
    return jsonify({'status': 'success'})

# Backups

@api_bp.route('/api/backups')
@login_required
def get_backups_api(): return jsonify(list_backups())

@api_bp.route('/api/backup/create', methods=['POST'])
@rate_limit_decorator("10 per hour")
@login_required
def trigger_backup():
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})
    success, msg = create_backup()
    return jsonify({'status': 'success', 'message': msg}) if success else jsonify({'status': 'error', 'message': msg})

@api_bp.route('/api/backup/download/<filename>')
@login_required
def download_backup(filename):
    if not current_user.is_admin:
        return "Unauthorized", 403
    safe_path = _safe_backup_path(filename)
    if not safe_path or not os.path.exists(safe_path):
        return "Invalid", 400
    return send_from_directory(BACKUP_DIR, os.path.basename(safe_path), as_attachment=True)

@api_bp.route('/api/backup/delete/<filename>', methods=['DELETE'])
@login_required
def delete_backup_api(filename):
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})
    safe_path = _safe_backup_path(filename)
    if not safe_path:
        return jsonify({'status': 'error'})
    if os.path.exists(safe_path):
        os.remove(safe_path)
    return jsonify({'status': 'success'})

@api_bp.route('/api/backup/restore/<filename>', methods=['POST'])
@rate_limit_decorator("5 per hour")
@login_required
def run_restore(filename):
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'})
    safe_path = _safe_backup_path(filename)
    if not safe_path:
        return jsonify({'status': 'error', 'message': 'Invalid filename'})

    success, msg = restore_backup(os.path.basename(safe_path))
    return jsonify({'status': 'success' if success else 'error', 'message': msg})

@api_bp.route('/api/backup/upload', methods=['POST'])
@rate_limit_decorator("5 per hour")
@login_required
def upload_backup():
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'})

    file = request.files.get('backup_file')
    if not file or not file.filename:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'})

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.zip'):
        return jsonify({'status': 'error', 'message': 'Only .zip backups are supported.'})

    max_upload_bytes = 50 * 1024 * 1024
    max_unzipped_bytes = 200 * 1024 * 1024
    max_entries = 10
    allowed_files = {'seekandwatch.db', 'plex_cache.json'}

    content_len = request.content_length
    if content_len and content_len > max_upload_bytes:
        return jsonify({'status': 'error', 'message': 'Backup is too large.'})

    os.makedirs(BACKUP_DIR, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=BACKUP_DIR, prefix="upload_", suffix=".zip") as tmp:
            tmp_path = tmp.name
            file.save(tmp_path)

        if not zipfile.is_zipfile(tmp_path):
            os.remove(tmp_path)
            return jsonify({'status': 'error', 'message': 'Invalid backup file (not a ZIP archive).'})

        total_size = 0
        found = set()
        with zipfile.ZipFile(tmp_path, 'r') as zipf:
            entries = zipf.infolist()
            if len(entries) > max_entries:
                os.remove(tmp_path)
                return jsonify({'status': 'error', 'message': 'Backup contains too many files.'})

            for info in entries:
                name = info.filename.replace('\\', '/')
                if not name or name.endswith('/'):
                    continue
                if name.startswith('/') or name.startswith('../') or '/..' in name:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains unsafe paths.'})
                if ':' in name.split('/')[0]:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains unsafe paths.'})

                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains a symbolic link.'})

                base = os.path.basename(name)
                if base in allowed_files:
                    found.add(base)
                else:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': f'Unexpected file in backup: {base}'})

                total_size += info.file_size
                if total_size > max_unzipped_bytes:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup expands too large.'})

        if not found:
            os.remove(tmp_path)
            return jsonify({'status': 'error', 'message': 'Backup is missing required files.'})

        base, ext = os.path.splitext(filename)
        target = os.path.join(BACKUP_DIR, filename)
        counter = 1
        while os.path.exists(target):
            filename = f"{base}_{counter}{ext}"
            target = os.path.join(BACKUP_DIR, filename)
            counter += 1

        os.replace(tmp_path, target)
        tmp_path = None
        return jsonify({'status': 'success', 'message': f'Backup uploaded as {filename}.'})
    except Exception as e:
        _log_api_exception("upload_backup", e)
        return _error_response("Upload failed")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

# cache and scanner settings

@api_bp.route('/save_cache_settings', methods=['POST'])
@login_required
def save_cache_settings():
    s = current_user.settings
    s.cache_interval = int(request.json.get('interval', 24))
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/force_cache_refresh', methods=['POST'])
@login_required
def force_cache_refresh_route():
    from flask import current_app
    # Run in background thread so the UI doesn't hang.
    threading.Thread(target=refresh_plex_cache, args=(current_app._get_current_object(),)).start()
    return jsonify({'status': 'success'})

@api_bp.route('/get_cache_status')
@login_required
def get_cache_status_route():
    return jsonify(get_lock_status())

@api_bp.route('/force_radarr_sonarr_cache_refresh', methods=['POST'])
@login_required
def force_radarr_sonarr_cache_refresh_route():
    from flask import current_app
    import threading
    threading.Thread(target=refresh_radarr_sonarr_cache, args=(current_app._get_current_object(),)).start()
    return jsonify({'status': 'success'})

@api_bp.route('/get_radarr_sonarr_cache_status')
@login_required
def get_radarr_sonarr_cache_status_route():
    s = current_user.settings
    cache_count = 0
    last_scan = "Never"
    
    try:
        from models import RadarrSonarrCache
        cache_count = RadarrSonarrCache.query.count()
    except:
        pass
    
    if s.last_radarr_sonarr_scan:
        try:
            import datetime
            dt = datetime.datetime.fromtimestamp(s.last_radarr_sonarr_scan)
            last_scan = dt.strftime('%Y-%m-%d %H:%M')
        except:
            pass
    
    return jsonify({
        'count': cache_count,
        'last_scan': last_scan,
        'enabled': s.radarr_sonarr_scanner_enabled if s else False,
        'interval': s.radarr_sonarr_scanner_interval if s else 24
    })

@api_bp.route('/api/radarr_sonarr_scanner/save', methods=['POST'])
@login_required
def save_radarr_sonarr_scanner_settings():
    s = current_user.settings
    data = request.json
    s.radarr_sonarr_scanner_enabled = data.get('enabled', False)
    s.radarr_sonarr_scanner_interval = int(data.get('interval', 24))
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/scanner/status')
@login_required
def scanner_status():
    s = current_user.settings
    next_ts = 0
    if s.scanner_enabled:
        last = s.last_alias_scan or 0
        interval_sec = (s.scanner_interval or 15) * 60
        next_ts = last + interval_sec
        
    return jsonify({
        'enabled': s.scanner_enabled,
        'interval': s.scanner_interval,
        'batch': s.scanner_batch,
        'total_indexed': TmdbAlias.query.count(),
        'next_ts': next_ts
    })

@api_bp.route('/api/scanner/aliases', methods=['GET'])
@rate_limit_decorator("30 per minute")  # Rate limit to prevent abuse
@login_required
def get_aliases():
    """Get alias entries - can filter by search term or TMDB ID"""
    search = request.args.get('search', '').strip().lower()
    tmdb_id = request.args.get('tmdb_id', type=int)
    media_type = request.args.get('media_type', '').strip()
    limit = request.args.get('limit', type=int) or 100
    
    # Security: Cap limit to prevent resource exhaustion
    max_limit = 500
    if limit > max_limit:
        limit = max_limit
    
    # Security: Validate media_type to prevent injection
    if media_type and media_type not in ['movie', 'tv']:
        return jsonify({'status': 'error', 'message': 'Invalid media_type'}), 400
    
    # Security: Limit search length to prevent DoS
    if len(search) > 100:
        search = search[:100]
    
    query = TmdbAlias.query
    
    # Filter by TMDB ID if provided
    if tmdb_id:
        query = query.filter_by(tmdb_id=tmdb_id)
    
    # Filter by media type if provided
    if media_type:
        query = query.filter_by(media_type=media_type)
    
    # Filter by search term (searches in plex_title and original_title)
    # Using word-boundary matching to avoid false positives (e.g., "dune" matching "disparition")
    if search:
        # Split search into words and match each word separately
        search_words = [w for w in search.split() if len(w) >= 3]  # Only words 3+ chars
        
        if search_words:
            # Build conditions for each word (all words must match - AND logic)
            for word in search_words:
                # Match word boundaries: start of string, after space, before space, end of string
                # This prevents "dune" from matching "disparition"
                word_conditions = db.or_(
                    # Word at start of title
                    TmdbAlias.plex_title.ilike(f'{word} %'),
                    TmdbAlias.original_title.ilike(f'{word} %'),
                    # Word at end of title
                    TmdbAlias.plex_title.ilike(f'% {word}'),
                    TmdbAlias.original_title.ilike(f'% {word}'),
                    # Word in middle (surrounded by spaces)
                    TmdbAlias.plex_title.ilike(f'% {word} %'),
                    TmdbAlias.original_title.ilike(f'% {word} %'),
                    # Exact match (single word title)
                    TmdbAlias.plex_title == word,
                    TmdbAlias.original_title == word
                )
                query = query.filter(word_conditions)
    
    # Only show valid entries (not placeholders)
    query = query.filter(TmdbAlias.tmdb_id > 0)
    
    aliases = query.order_by(TmdbAlias.plex_title).limit(limit).all()
    
    results = []
    for alias in aliases:
        results.append({
            'id': alias.id,
            'tmdb_id': alias.tmdb_id,
            'media_type': alias.media_type,
            'plex_title': alias.plex_title,
            'original_title': alias.original_title,
            'match_year': alias.match_year
        })
    
    # Also include some stats
    total_count = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).count()
    placeholder_count = TmdbAlias.query.filter(TmdbAlias.tmdb_id == -1).count()
    
    return jsonify({
        'status': 'success',
        'count': len(results),
        'aliases': results,
        'stats': {
            'total_matched': total_count,
            'not_found': placeholder_count,
            'showing': len(results)
        }
    })

@api_bp.route('/api/scanner/save', methods=['POST'])
@login_required
def save_scanner_settings():
    s = current_user.settings
    data = request.json
    s.scanner_enabled = data.get('enabled')
    s.scanner_interval = int(data.get('interval'))
    s.scanner_batch = int(data.get('batch'))
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/scanner/log_size', methods=['POST'])
@login_required
def update_scanner_log_size():
    """Update scanner log size limit."""
    s = current_user.settings
    data = request.json
    try:
        s.scanner_log_size = int(data.get('scanner_log_size', 10))
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        _log_api_exception("update_scanner_log_size", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/scanner/reset', methods=['POST'])
@login_required
def reset_scanner():
    # nuke the alias database and start fresh
    TmdbAlias.query.delete()
    s = current_user.settings
    s.last_alias_scan = 0
    db.session.commit()
    
    write_scanner_log("Database Wiped by User.")
    write_log("info", "Scanner", "Alias Database wiped by user.")
    
    return jsonify({'status': 'success', 'message': 'Database wiped.'})
    
@api_bp.route('/api/scanner/logs_stream')
@login_required
def stream_scanner_logs():
    return jsonify({'logs': read_scanner_log()})

@api_bp.route('/save_kometa_config', methods=['POST'])
@login_required
@rate_limit_decorator("30 per minute")  # rate limit saves
def save_kometa_config():
    s = current_user.settings
    data = request.json
    
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'}), 400
    
    # validate data structure - ensure it's a dict and has expected keys
    if not isinstance(data, dict):
        return jsonify({'status': 'error', 'message': 'Invalid data format'}), 400
    
    # validate and sanitize libraries array
    if 'libraries' in data:
        if not isinstance(data['libraries'], list):
            return jsonify({'status': 'error', 'message': 'Libraries must be a list'}), 400
        # limit number of libraries (reasonable limit)
        if len(data['libraries']) > 100:
            return jsonify({'status': 'error', 'message': 'Too many libraries (max 100)'}), 400
        # validate each library structure
        for lib in data['libraries']:
            if not isinstance(lib, dict):
                return jsonify({'status': 'error', 'message': 'Invalid library structure'}), 400
            if 'name' not in lib or not isinstance(lib.get('name'), str):
                return jsonify({'status': 'error', 'message': 'Library name is required'}), 400
            # limit name length
            if len(lib['name']) > 200:
                return jsonify({'status': 'error', 'message': 'Library name too long'}), 400
            # validate cols and ovls are lists
            if 'cols' in lib and not isinstance(lib['cols'], list):
                lib['cols'] = []
            if 'ovls' in lib and not isinstance(lib['ovls'], list):
                lib['ovls'] = []
            # limit collection/overlay counts per library
            if len(lib.get('cols', [])) > 500 or len(lib.get('ovls', [])) > 500:
                return jsonify({'status': 'error', 'message': 'Too many collections/overlays per library'}), 400
    
    # validate templateVars structure
    if 'templateVars' in data and not isinstance(data['templateVars'], dict):
        data['templateVars'] = {}
    
    if 'libraryTemplateVars' in data and not isinstance(data['libraryTemplateVars'], dict):
        data['libraryTemplateVars'] = {}
    
    # validate inlineComments structure
    if 'inlineComments' in data and not isinstance(data['inlineComments'], dict):
        data['inlineComments'] = {}
    
    # validate settings structure
    if 'settings' in data and not isinstance(data['settings'], dict):
        data['settings'] = {}
    
    # sanitize string fields (limit length, basic validation)
    string_fields = ['plex_url', 'plex_token', 'tmdb_key']
    for field in string_fields:
        if field in data and data[field]:
            if not isinstance(data[field], str):
                data[field] = str(data[field])
            # limit length
            if len(data[field]) > 1000:
                return jsonify({'status': 'error', 'message': f'{field} is too long'}), 400
    
    # limit total config size (prevent huge payloads)
    config_json = json.dumps(data)
    if len(config_json) > 2 * 1024 * 1024:  # 2MB max
        return jsonify({'status': 'error', 'message': 'Config too large (max 2MB)'}), 400
    
    # Include templateVars in saved config (ensure it exists)
    if 'templateVars' not in data:
        data['templateVars'] = {}
    
    s.kometa_config = config_json
    
    # Sync these settings with main config if user changed them here.
    if data.get('plex_url'): s.plex_url = data['plex_url']
    if data.get('plex_token'): s.plex_token = data['plex_token']
    if data.get('tmdb_key'): s.tmdb_key = data['tmdb_key']
    
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/kometa_templates', methods=['GET'])
@login_required
def get_kometa_templates():
    """Get all Kometa templates for the current user."""
    from models import KometaTemplate
    templates = KometaTemplate.query.filter_by(user_id=current_user.id).order_by(KometaTemplate.created_at.desc()).all()
    result = []
    for t in templates:
        result.append({
            'id': t.id,
            'name': t.name,
            'type': t.type,
            'cols': json.loads(t.cols) if t.cols else [],
            'ovls': json.loads(t.ovls) if t.ovls else [],
            'templateVars': json.loads(t.template_vars) if t.template_vars else {},
            'created_at': t.created_at.isoformat() if t.created_at else None
        })
    return jsonify({'status': 'success', 'templates': result})

@api_bp.route('/api/kometa_templates', methods=['POST'])
@login_required
def save_kometa_template():
    """Save a Kometa template."""
    from models import KometaTemplate
    data = request.json
    
    if not data.get('name') or not data.get('name').strip():
        return jsonify({'status': 'error', 'message': 'Template name is required'}), 400
    
    # Validate and sanitize input
    name = data['name'].strip()[:200]  # Limit length
    template_type = data.get('type', 'movie')
    cols = data.get('cols', [])
    ovls = data.get('ovls', [])
    template_vars = data.get('templateVars', {})
    
    # Validate type
    if template_type not in ['movie', 'tv', 'anime']:
        template_type = 'movie'
    
    # Validate cols/ovls are arrays
    if not isinstance(cols, list):
        cols = []
    if not isinstance(ovls, list):
        ovls = []
    if not isinstance(template_vars, dict):
        template_vars = {}
    
    template = KometaTemplate(
        user_id=current_user.id,
        name=name,
        type=template_type,
        cols=json.dumps(cols),
        ovls=json.dumps(ovls),
        template_vars=json.dumps(template_vars)
    )
    
    db.session.add(template)
    db.session.commit()
    
    return jsonify({'status': 'success', 'id': template.id})

@api_bp.route('/api/kometa_templates/<int:template_id>', methods=['DELETE'])
@login_required
def delete_kometa_template(template_id):
    """Delete a Kometa template."""
    from models import KometaTemplate
    template = KometaTemplate.query.filter_by(id=template_id, user_id=current_user.id).first()
    
    if not template:
        return jsonify({'status': 'error', 'message': 'Template not found'}), 404
    
    db.session.delete(template)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@api_bp.route('/api/import_kometa_config', methods=['POST'])
@login_required
@rate_limit_decorator("10 per minute")  # Rate limit imports
def import_kometa_config():
    """Securely import Kometa config from URL."""
    import re
    from requests.exceptions import RequestException, Timeout
    
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({'status': 'error', 'message': 'URL is required'}), 400
    
    # Validate URL format
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return jsonify({'status': 'error', 'message': 'Invalid URL format'}), 400
        
        # Only allow http/https
        if parsed.scheme not in ['http', 'https']:
            return jsonify({'status': 'error', 'message': 'Only HTTP and HTTPS URLs are allowed'}), 400
        
        # Block local/private IPs and localhost
        hostname = parsed.hostname.lower()
        if hostname in ['localhost', '127.0.0.1', '0.0.0.0']:
            return jsonify({'status': 'error', 'message': 'Local URLs are not allowed'}), 400
        
        # Block private IP ranges in hostname
        if re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', hostname):
            return jsonify({'status': 'error', 'message': 'Private IP addresses are not allowed'}), 400
        
        # Block IPv6 localhost variants
        if hostname in ['::1', '[::1]', 'ip6-localhost', 'ip6-loopback']:
            return jsonify({'status': 'error', 'message': 'Local URLs are not allowed'}), 400
        
    except Exception as e:
        _log_api_exception("import_kometa_config_url_validation", e)
        return jsonify({'status': 'error', 'message': 'Invalid URL'}), 400
    
    # Resolve DNS and check actual IP to prevent DNS rebinding attacks
    try:
        resolved_ip = socket.gethostbyname(parsed.hostname)
        # Block private/local IPs at resolved IP level
        if resolved_ip in ['127.0.0.1', '0.0.0.0']:
            return jsonify({'status': 'error', 'message': 'Local URLs are not allowed'}), 400
        # Block private IP ranges (10.x, 172.16-31.x, 192.168.x)
        if re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', resolved_ip):
            return jsonify({'status': 'error', 'message': 'Private IP addresses are not allowed'}), 400
    except (socket.gaierror, socket.herror, OSError) as e:
        _log_api_exception("import_kometa_config_dns_resolution", e)
        return jsonify({'status': 'error', 'message': 'Could not resolve hostname'}), 400
    
    # Reconstruct URL from validated components to prevent SSRF via malformed URL
    safe_url = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.path:
        safe_url += parsed.path
    if parsed.query:
        safe_url += f"?{parsed.query}"
    if parsed.fragment:
        safe_url += f"#{parsed.fragment}"
    
    # Fetch the file with security measures
    try:
        response = requests.get(
            safe_url,
            timeout=10,  # 10 second timeout
            max_redirects=5,  # Limit redirects
            allow_redirects=True,
            headers={'User-Agent': 'SeekAndWatch/1.0'}
        )
        response.raise_for_status()
        
        # Check content size (max 1MB)
        if len(response.content) > 1024 * 1024:
            return jsonify({'status': 'error', 'message': 'File too large (max 1MB)'}), 400
        
        # Check content type (should be text)
        content_type = response.headers.get('content-type', '').lower()
        if 'text' not in content_type and 'yaml' not in content_type and 'yml' not in content_type:
            # Warn but don't block - some servers don't set content-type correctly
            pass
        
        yaml_text = response.text
        
        # Basic validation - check if it looks like YAML
        if not yaml_text.strip():
            return jsonify({'status': 'error', 'message': 'Empty file'}), 400
        
        # Return the YAML text for client-side parsing
        return jsonify({'status': 'success', 'yaml': yaml_text})
        
    except Timeout as e:
        _log_api_exception("import_kometa_config_timeout", e)
        return jsonify({'status': 'error', 'message': 'Request timed out'}), 408
    except RequestException as e:
        _log_api_exception("import_kometa_config_request", e)
        return jsonify({'status': 'error', 'message': 'Failed to fetch URL'}), 400
    except Exception as e:
        _log_api_exception("import_kometa_config", e)
        return jsonify({'status': 'error', 'message': 'Import failed'}), 500

@api_bp.route('/api/sync_aliases', methods=['POST'])
@login_required
def manual_alias_sync():
    # Legacy button, rarely used now.
    success, msg = sync_remote_aliases()
    status = 'success' if success else 'error'
    try: total = TmdbAlias.query.count()
    except: total = 0
    return jsonify({'status': status, 'message': msg, 'count': total})

# admin user management stuff

@api_bp.route('/api/admin/users')
@login_required
def get_all_users():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
        
    users = User.query.all()
    user_list = []
    for u in users:
        user_list.append({
            'id': u.id,
            'username': u.username,
            'is_admin': u.is_admin,
            'is_current': (u.id == current_user.id)
        })
    return jsonify(user_list)

@api_bp.route('/api/admin/toggle_role', methods=['POST'])
@rate_limit_decorator("20 per hour")
@login_required
def toggle_user_role():
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        
    data = request.json
    target_id = data.get('user_id')
    
    if target_id == current_user.id:
        return jsonify({'status': 'error', 'message': 'You cannot remove your own admin status.'})
        
    user = User.query.get(target_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'})
        
    user.is_admin = not user.is_admin
    db.session.commit()
    
    status_str = "Admin" if user.is_admin else "User"
    return jsonify({'status': 'success', 'message': f"User {user.username} is now: {status_str}"})

@api_bp.route('/api/admin/delete_user', methods=['POST'])
@rate_limit_decorator("10 per hour")
@login_required
def admin_delete_user():
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        
    data = request.json
    target_id = data.get('user_id')
    
    # can't delete yourself (obviously)
    if target_id == current_user.id:
        return jsonify({'status': 'error', 'message': 'Cannot delete yourself.'})
        
    user = User.query.get(target_id)
    if user:
        # delete their settings and blocklist too (cleanup)
        Settings.query.filter_by(user_id=user.id).delete()
        Blocklist.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'User deleted.'})
        
    return jsonify({'status': 'error', 'message': 'User not found'})
    
@api_bp.route('/save_schedule_time', methods=['POST'])
@login_required
def save_schedule_time():
    s = current_user.settings
    new_time = request.form.get('time', '04:00')
    
    # Quick validation.
    if ':' in new_time and len(new_time) == 5:
        s.schedule_time = new_time
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Global Run Time set to {new_time}'})
    return jsonify({'status': 'error', 'message': 'Invalid time format'})

# Radarr/Sonarr integration endpoints (duplicates removed - see lines ~2011+ for actual implementations)

@api_bp.route('/api/media/requested')
@login_required
def get_requested_media():
    """Get requested media from Overseerr and from app (Radarr/Sonarr adds)."""
    s = current_user.settings
    items = []
    
    try:
        if s.overseerr_url and s.overseerr_api_key:
            headers = {'X-Api-Key': s.overseerr_api_key}
            base_url = s.overseerr_url.rstrip('/')
            r = requests.get(f"{base_url}/api/v1/request", headers=headers, params={'take': 100, 'filter': 'all'}, timeout=10)
            if r.status_code != 200:
                return jsonify({'status': 'error', 'message': 'Failed to fetch requests', 'items': []})
            requests_data = r.json().get('results', [])
            for req in requests_data:
                # Overseerr can return media data in 'media' or 'mediaInfo' fields
                media = req.get('media', {}) or req.get('mediaInfo', {})
                status_map = {1: 'Pending', 2: 'Approved', 3: 'Available', 4: 'Failed'}
                status = status_map.get(req.get('status', 0), 'Unknown')
                media_type = media.get('mediaType') or req.get('mediaType') or 'movie'
                title = None
                if media:
                    title = (media.get('title') or media.get('name') or media.get('originalTitle') or media.get('originalName'))
                if not title:
                    title = (req.get('title') or req.get('name') or req.get('mediaTitle') or req.get('mediaName'))
                tmdb_id = media.get('tmdbId') or req.get('tmdbId')
                tmdb_data = None
                if (not title or title == 'Unknown') and tmdb_id and s.tmdb_key:
                    try:
                        tmdb_type = 'movie' if media_type == 'movie' else 'tv'
                        tmdb_url = f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}?api_key={s.tmdb_key}"
                        tmdb_resp = requests.get(tmdb_url, timeout=5)
                        if tmdb_resp.status_code == 200:
                            tmdb_data = tmdb_resp.json()
                            title = tmdb_data.get('title') or tmdb_data.get('name')
                    except Exception:
                        pass
                title = title or 'Unknown'
                year = None
                if media:
                    release_date = media.get('releaseDate') or media.get('release_date')
                    first_air_date = media.get('firstAirDate') or media.get('first_air_date')
                    if release_date:
                        year = str(release_date)[:4] if release_date else None
                    elif first_air_date:
                        year = str(first_air_date)[:4] if first_air_date else None
                if not year:
                    release_date = req.get('releaseDate') or req.get('release_date')
                    first_air_date = req.get('firstAirDate') or req.get('first_air_date')
                    if release_date:
                        year = str(release_date)[:4] if release_date else None
                    elif first_air_date:
                        year = str(first_air_date)[:4] if first_air_date else None
                if not year and tmdb_data:
                    try:
                        release_date = tmdb_data.get('release_date') or tmdb_data.get('first_air_date')
                        if release_date:
                            year = str(release_date)[:4]
                    except Exception:
                        pass
                requested_by_obj = req.get('requestedBy', {})
                if isinstance(requested_by_obj, dict):
                    requested_by = (requested_by_obj.get('displayName') or requested_by_obj.get('username') or requested_by_obj.get('email') or 'N/A')
                else:
                    requested_by = str(requested_by_obj) if requested_by_obj else 'N/A'
                if requested_by and 'agregarr' in requested_by.lower():
                    requested_by = 'Agregarr'
                overseerr_url = None
                if tmdb_id:
                    overseerr_url = f"{base_url}/movie/{tmdb_id}" if media_type == 'movie' else f"{base_url}/tv/{tmdb_id}"
                poster_url = None
                if media:
                    poster_path = media.get('posterPath') or media.get('poster_path')
                    if poster_path:
                        poster_url = poster_path if poster_path.startswith('http') else f"https://image.tmdb.org/t/p/w500{poster_path}"
                if not poster_url and tmdb_data and tmdb_data.get('poster_path'):
                    poster_url = f"https://image.tmdb.org/t/p/w500{tmdb_data.get('poster_path')}"
                added_date = req.get('createdAt') or req.get('addedAt') or req.get('created_at')
                items.append({
                    'title': title,
                    'year': year,
                    'status': status,
                    'requested_via': 'Overseerr',
                    'requested_by': requested_by,
                    'overseerr_url': overseerr_url,
                    'poster_url': poster_url,
                    'added': added_date,
                    'media_type': media_type
                })
            # merge requests made from the app (Radarr/Sonarr add)
            try:
                app_requests = AppRequest.query.order_by(AppRequest.requested_at.desc()).limit(500).all()
                for ar in app_requests:
                    added = ar.requested_at.isoformat() if ar.requested_at else ''
                    items.append({
                        'title': ar.title or 'Unknown',
                        'year': None,
                        'status': 'Requested',
                        'requested_via': ar.requested_via or 'Radarr',
                        'requested_by': 'SeekAndWatch',
                        'overseerr_url': None,
                        'poster_url': None,
                        'added': added,
                        'media_type': ar.media_type or 'movie'
                    })
            except Exception:
                pass
        else:
            # no Overseerr - show only requests made from the app (Radarr/Sonarr)
            try:
                app_requests = AppRequest.query.order_by(AppRequest.requested_at.desc()).limit(500).all()
                for ar in app_requests:
                    added = ar.requested_at.isoformat() if ar.requested_at else ''
                    items.append({
                        'title': ar.title or 'Unknown',
                        'year': None,
                        'status': 'Requested',
                        'requested_via': ar.requested_via or 'Radarr',
                        'requested_by': 'SeekAndWatch',
                        'overseerr_url': None,
                        'poster_url': None,
                        'added': added,
                        'media_type': ar.media_type or 'movie'
                    })
            except Exception:
                pass
        
        # Apply filters
        status_filter = request.args.get('status', '').lower()
        source_filter = request.args.get('source', '').lower()
        sort_by = request.args.get('sort', 'added_desc')
        
        if status_filter:
            items = [i for i in items if i['status'].lower() == status_filter]
        if source_filter:
            items = [i for i in items if i['requested_via'].lower() == source_filter]
        
        # Sort
        if sort_by == 'title_asc':
            items.sort(key=lambda x: (x.get('title') or '').lower())
        elif sort_by == 'year_desc':
            items.sort(key=lambda x: int(x.get('year')) if x.get('year') else 0, reverse=True)
        elif sort_by == 'added_desc':
            items.sort(key=lambda x: x.get('added') or '', reverse=True)
        # Default is already sorted by Overseerr, but we handle it explicitly above
        
        # Pagination - configurable page size (default 200, max 200)
        try:
            page = int(request.args.get('page', 1))
            if page < 1 or page > 10000:  # Reasonable max
                page = 1
        except (ValueError, TypeError):
            page = 1
        
        try:
            requested_page_size = int(request.args.get('page_size', 200))
            # Limit to valid options: 50, 100, 150, or 200
            valid_page_sizes = [50, 100, 150, 200]
            page_size = requested_page_size if requested_page_size in valid_page_sizes else 200
        except (ValueError, TypeError):
            page_size = 200
        total_items = len(items)
        total_pages = (total_items + page_size - 1) // page_size  # Ceiling division
        
        # Get items for current page
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]
        
        return jsonify({
            'status': 'success', 
            'items': paginated_items,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_items': total_items,
                'total_pages': total_pages
            }
        })
        
    except Exception as e:
        _log_api_exception("get_requested_media", e)
        return jsonify({'status': 'error', 'message': str(e), 'items': []})

@api_bp.route('/api/media/movies')
@login_required
def get_movies():
    """Get movies from Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured', 'items': []})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        # Ensure base_url doesn't have /api in it (some users might have configured it that way)
        base_url = s.radarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]  # Remove /api if present
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]  # Remove /api/v3 if present
        
        r = requests.get(f"{base_url}/api/v3/movie", headers=headers, timeout=10)
        if r.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch movies', 'items': []})
        
        movies = r.json()
        
        # Ensure movies is a list
        if not isinstance(movies, list):
            return jsonify({'status': 'error', 'message': 'Invalid response from Radarr', 'items': []})
        
        # Debug: Log first movie structure to see what we're getting
        if movies and len(movies) > 0:
            try:
                first_movie = movies[0]
                # Log basic info to help diagnose ID issues
                write_log("info", "Radarr", f"First movie 'id': {first_movie.get('id')}, 'tmdbId': {first_movie.get('tmdbId')}, 'title': {first_movie.get('title')}")
            except Exception as e:
                write_log("warning", "Radarr", f"Error logging first movie: {e}")
        
        items = []
        
        # Track IDs to detect duplicates (for debugging)
        seen_ids = set()
        
        for idx, movie in enumerate(movies):
            # Get the Radarr internal ID - this should be the 'id' field
            # Radarr API returns the internal database ID in the 'id' field
            # However, if Radarr is returning incorrect IDs, we may need to use a different field
            movie_id = movie.get('id')
            
            # Check for alternative ID fields (in case Radarr uses a different field)
            # Some Radarr instances might use 'movieId' or other fields
            alt_id_fields = {
                'movieId': movie.get('movieId'),
                'radarrId': movie.get('radarrId'),
                'databaseId': movie.get('databaseId'),
            }
            
            if movie_id is None:
                # Try to find an alternative ID field
                for field_name, alt_id in alt_id_fields.items():
                    if alt_id is not None:
                        write_log("warning", "Radarr", f"Movie '{movie.get('title')}' has no 'id' field, using '{field_name}': {alt_id}")
                        movie_id = alt_id
                        break
                
                if movie_id is None:
                    continue  # Skip movies without any ID
            
            # Convert to int to ensure it's the correct type
            try:
                movie_id = int(movie_id)
            except (ValueError, TypeError):
                continue  # Skip if ID can't be converted to int
            
            # Check for duplicate IDs
            if movie_id in seen_ids:
                # Duplicate ID detected - this shouldn't happen
                # Skip this movie to avoid confusion
                continue
            seen_ids.add(movie_id)
            
            # Use the movie_id directly - it should be correct from the API
            # According to Radarr API docs, the 'id' field is the internal Radarr database ID
            # which should be used for web UI URLs like /movie/{id}
            final_movie_id = movie_id
            
            # Get TMDB ID for potential fallback/debugging
            tmdb_id = movie.get('tmdbId')
            # Convert to int if it exists
            if tmdb_id is not None:
                try:
                    tmdb_id = int(tmdb_id)
                except (ValueError, TypeError):
                    tmdb_id = None
            
            has_file = movie.get('hasFile', False)
            file_info = movie.get('movieFile', {})
            
            # Extract size
            size = None
            if file_info:
                size_val = file_info.get('size', 0)
                if size_val and size_val > 0:
                    size = size_val
            
            # Extract quality - Radarr API structure: movieFile.quality.quality.name
            quality = None
            if file_info and file_info.get('quality'):
                quality_obj = file_info.get('quality', {})
                if isinstance(quality_obj, dict):
                    # Try different possible paths for quality name
                    quality_name = (quality_obj.get('quality', {}).get('name') or 
                                   quality_obj.get('name'))
                    if quality_name:
                        quality = quality_name
                    # If no name, try to construct from resolution
                    elif quality_obj.get('resolution'):
                        quality = quality_obj.get('resolution')
            
            # Construct Radarr URL - Radarr web UI uses /movie/{id} format
            # According to Radarr docs, it should use the internal database ID
            # However, some Radarr instances or versions might use TMDB IDs in the web UI
            # If the ID is suspiciously low (like in 6000 range) and we have a TMDB ID,
            # try using TMDB ID instead as a workaround
            try:
                if tmdb_id is not None and final_movie_id < 10000 and tmdb_id != final_movie_id:
                    # The ID seems wrong (low number), try using TMDB ID for the web UI URL
                    # This is a workaround for Radarr instances that use TMDB IDs in web UI
                    radarr_url = f"{base_url}/movie/{tmdb_id}"
                else:
                    # Use the API ID as normal
                    radarr_url = f"{base_url}/movie/{final_movie_id}"
            except Exception as e:
                # Fallback to using the API ID if there's any error
                write_log("warning", "Radarr", f"Error constructing URL for movie '{movie.get('title')}': {e}")
                radarr_url = f"{base_url}/movie/{final_movie_id}"
            
            # Verify the movie ID matches what we expect
            # Sometimes Radarr API might return stale data, so we'll trust the API response
            # but include both the ID and URL for debugging
            
            # Extract poster URL from images array
            poster_url = None
            if movie.get('images'):
                for img in movie.get('images', []):
                    if img.get('coverType') == 'poster':
                        poster_url = img.get('url')
                        break
                # Fallback to first image if no poster found
                if not poster_url and len(movie.get('images', [])) > 0:
                    poster_url = movie.get('images', [{}])[0].get('url')
            
            # Convert relative URLs to absolute URLs
            if poster_url and not poster_url.startswith('http'):
                if poster_url.startswith('/'):
                    poster_url = f"{base_url}{poster_url}"
                else:
                    poster_url = f"{base_url}/{poster_url}"
            
            movie_data = {
                'id': final_movie_id,  # Use verified ID
                'title': movie.get('title', 'Unknown'),
                'year': movie.get('year'),
                'monitored': movie.get('monitored', False),
                'has_file': has_file,
                'quality': quality,
                'size': size,
                'radarrUrl': radarr_url,
                'added': movie.get('added', ''),
                'poster_url': poster_url
            }
            
            # Debug: Include raw data for first few movies to help diagnose ID issues
            if len(items) < 5:
                movie_data['_debug'] = {
                    'raw_id': movie.get('id'),
                    'final_id': final_movie_id,
                    'tmdb_id': movie.get('tmdbId'),
                    'imdb_id': movie.get('imdbId'),
                    'title': movie.get('title'),
                    'year': movie.get('year'),
                    'radarrUrl': radarr_url,
                    'base_url': base_url,
                    'note': 'If radarrUrl leads to 404, the ID might be incorrect. Check Radarr API response.'
                }
            
            items.append(movie_data)
        
        # Apply filters
        monitored_filter = request.args.get('monitored', '').lower()
        has_file_filter = request.args.get('has_file', '').lower()
        sort_by = request.args.get('sort', 'added_desc')
        
        if monitored_filter == 'monitored':
            items = [i for i in items if i['monitored']]
        elif monitored_filter == 'unmonitored':
            items = [i for i in items if not i['monitored']]
        
        if has_file_filter == 'has_file':
            items = [i for i in items if i['has_file']]
        elif has_file_filter == 'missing_file':
            items = [i for i in items if not i['has_file']]
        
        # Sort
        if sort_by == 'title_asc':
            items.sort(key=lambda x: (x.get('title') or '').lower())
        elif sort_by == 'year_desc':
            items.sort(key=lambda x: int(x.get('year')) if x.get('year') else 0, reverse=True)
        elif sort_by == 'size_desc':
            items.sort(key=lambda x: x.get('size') or 0, reverse=True)
        elif sort_by == 'added_desc':
            items.sort(key=lambda x: x.get('added') or '', reverse=True)
        
        # Pagination - configurable page size (default 200, max 200)
        page = int(request.args.get('page', 1))
        requested_page_size = int(request.args.get('page_size', 200))
        # Limit to valid options: 50, 100, 150, or 200
        valid_page_sizes = [50, 100, 150, 200]
        page_size = requested_page_size if requested_page_size in valid_page_sizes else 200
        total_items = len(items)
        total_pages = (total_items + page_size - 1) // page_size  # Ceiling division
        
        # Calculate slice indices
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]
        
        return jsonify({
            'status': 'success',
            'items': paginated_items,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_items': total_items,
                'total_pages': total_pages
            }
        })
        
    except Exception as e:
        _log_api_exception("get_movies", e)
        return jsonify({'status': 'error', 'message': str(e), 'items': []})

@api_bp.route('/api/media/tv')
@login_required
def get_tv_shows():
    """Get TV shows from Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured', 'items': []})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        r = requests.get(f"{base_url}/api/v3/series", headers=headers, timeout=10)
        if r.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch TV shows', 'items': []})
        
        series_list = r.json()
        items = []
        
        for series in series_list:
            try:
                # Get the Sonarr internal ID (should be the 'id' field)
                # Ensure it's an integer, not a string or other type
                series_id = series.get('id')
                if series_id is None:
                    continue  # Skip series without an ID
                
                # Convert to int to ensure it's the correct type
                try:
                    series_id = int(series_id)
                except (ValueError, TypeError):
                    continue  # Skip if ID can't be converted to int
                
                # Use sizeOnDisk from series object (faster, no need to fetch all episodes for list view)
                size_on_disk = series.get('sizeOnDisk', 0)
                has_file = size_on_disk > 0 if size_on_disk else False
                total_size = size_on_disk if size_on_disk and size_on_disk > 0 else None
                quality = None
                
                # Try to get quality from series statistics if available (some Sonarr versions provide this)
                # Otherwise, quality will be None for list view (can be fetched in detail view if needed)
                if series.get('statistics'):
                    stats = series.get('statistics', {})
                    if stats.get('qualityProfile'):
                        quality_profile = stats.get('qualityProfile', {})
                        if isinstance(quality_profile, dict):
                            quality = quality_profile.get('name')
                
                # Extract poster URL from images array
                poster_url = None
                if series.get('images'):
                    for img in series.get('images', []):
                        if img.get('coverType') == 'poster':
                            poster_url = img.get('url')
                            break
                    # Fallback to first image if no poster found
                    if not poster_url and len(series.get('images', [])) > 0:
                        poster_url = series.get('images', [{}])[0].get('url')
                
                # Convert relative URLs to absolute URLs
                if poster_url and not poster_url.startswith('http'):
                    if poster_url.startswith('/'):
                        poster_url = f"{base_url}{poster_url}"
                    else:
                        poster_url = f"{base_url}/{poster_url}"
                
                # Construct Sonarr URL - Sonarr uses titleSlug for web UI URLs (e.g., /series/free-bert)
                title_slug = series.get('titleSlug')
                sonarr_url = None
                try:
                    if title_slug:
                        # Use titleSlug if available (this is what Sonarr web UI uses)
                        sonarr_url = f"{base_url}/series/{title_slug}"
                    elif series_id:
                        # Fallback to series ID if no slug available
                        sonarr_url = f"{base_url}/series/{series_id}"
                except Exception as e:
                    # Fallback to using the API ID if there's any error
                    try:
                        write_log("warning", "Sonarr", f"Error constructing URL for series: {e}")
                    except:
                        pass  # don't fail if logging fails
                    sonarr_url = f"{base_url}/series/{series_id}" if series_id else None
                
                # Ensure sonarr_url is set (should never be None at this point, but be safe)
                if not sonarr_url and series_id:
                    sonarr_url = f"{base_url}/series/{series_id}"
                
                items.append({
                    'id': series_id,
                    'title': series.get('title', 'Unknown'),
                    'year': series.get('year'),
                    'monitored': series.get('monitored', False),
                    'has_file': has_file,
                    'quality': quality,
                    'size': total_size if total_size and total_size > 0 else None,
                    'sonarrUrl': sonarr_url,
                    'added': series.get('added', ''),
                    'poster_url': poster_url
                })
            except Exception as e:
                # Skip this series if there's an error processing it, but continue with others
                try:
                    write_log("warning", "Sonarr", f"Error processing series '{series.get('title', 'Unknown')}': {e}")
                except:
                    pass
                continue  # Skip to next series
        
        # Apply filters
        monitored_filter = request.args.get('monitored', '').lower()
        has_file_filter = request.args.get('has_file', '').lower()
        sort_by = request.args.get('sort', 'added_desc')
        
        if monitored_filter == 'monitored':
            items = [i for i in items if i['monitored']]
        elif monitored_filter == 'unmonitored':
            items = [i for i in items if not i['monitored']]
        
        if has_file_filter == 'has_file':
            items = [i for i in items if i['has_file']]
        elif has_file_filter == 'missing_file':
            items = [i for i in items if not i['has_file']]
        
        # Sort
        if sort_by == 'title_asc':
            items.sort(key=lambda x: (x.get('title') or '').lower())
        elif sort_by == 'year_desc':
            items.sort(key=lambda x: int(x.get('year')) if x.get('year') else 0, reverse=True)
        elif sort_by == 'size_desc':
            items.sort(key=lambda x: x.get('size') or 0, reverse=True)
        elif sort_by == 'added_desc':
            items.sort(key=lambda x: x.get('added') or '', reverse=True)
        
        # Pagination - configurable page size (default 200, max 200)
        try:
            page = int(request.args.get('page', 1))
            if page < 1 or page > 10000:  # Reasonable max
                page = 1
        except (ValueError, TypeError):
            page = 1
        
        try:
            requested_page_size = int(request.args.get('page_size', 200))
            # Limit to valid options: 50, 100, 150, or 200
            valid_page_sizes = [50, 100, 150, 200]
            page_size = requested_page_size if requested_page_size in valid_page_sizes else 200
        except (ValueError, TypeError):
            page_size = 200
        
        total_items = len(items)
        total_pages = (total_items + page_size - 1) // page_size  # Ceiling division
        
        # Get items for current page
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]
        
        return jsonify({
            'status': 'success', 
            'items': paginated_items,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_items': total_items,
                'total_pages': total_pages
            }
        })
        
    except Exception as e:
        _log_api_exception("get_tv_shows", e)
        return jsonify({'status': 'error', 'message': str(e), 'items': []})

# Old toggle endpoints removed - using the ones with URL parameters below (lines ~2038+)

# Media Management (Radarr/Sonarr/Overseerr)
@api_bp.route('/api/media/overview')
@login_required
def get_media_overview():
    """Fetch media from Overseerr, Radarr, and Sonarr."""
    s = current_user.settings
    media_type = request.args.get('type', 'all')  # all, requested, movies, shows
    sort_by = request.args.get('sort', 'added_desc')
    filters = {
        'monitored': request.args.get('monitored'),
        'status': request.args.getlist('status'),
        'has_file': request.args.get('has_file'),
        'source': request.args.get('source'),
        'year_min': request.args.get('year_min', type=int),
        'year_max': request.args.get('year_max', type=int),
        'size_min': request.args.get('size_min', type=int),
        'size_max': request.args.get('size_max', type=int),
    }
    
    result = {'requested': [], 'movies': [], 'shows': []}
    
    # Fetch Overseerr requests
    if media_type in ['all', 'requested'] and s.overseerr_url and s.overseerr_api_key:
        try:
            headers = {'X-Api-Key': s.overseerr_api_key}
            base_url = s.overseerr_url.rstrip('/')
            # Get recent requests
            req_url = f"{base_url}/api/v1/request?take=100&sort=added"
            req_resp = requests.get(req_url, headers=headers, timeout=10)
            if req_resp.status_code == 200:
                requests_data = req_resp.json().get('results', [])
                for req in requests_data:
                    media = req.get('media', {})
                    status_map = {1: 'Pending', 2: 'Approved', 3: 'Available', 4: 'Failed'}
                    requested_by = req.get('requestedBy', {}).get('displayName', 'Unknown')
                    # Normalize common service names
                    if requested_by and 'agregarr' in requested_by.lower():
                        requested_by = 'Agregarr'
                    
                    result['requested'].append({
                        'id': req.get('id'),
                        'tmdb_id': media.get('tmdbId'),
                        'tvdb_id': media.get('tvdbId'),
                        'title': media.get('title') or media.get('name'),
                        'year': media.get('releaseDate', '')[:4] if media.get('releaseDate') else (media.get('firstAirDate', '')[:4] if media.get('firstAirDate') else ''),
                        'media_type': 'movie' if media.get('mediaType') == 'movie' else 'tv',
                        'status': status_map.get(req.get('status', 0), 'Unknown'),
                        'requested_by': requested_by,
                        'requested_via': 'Overseerr',
                        'added': req.get('createdAt'),
                        'poster': media.get('posterPath'),
                    })
            # merge app requests (Radarr/Sonarr add from the app)
            try:
                app_requests = AppRequest.query.order_by(AppRequest.requested_at.desc()).limit(500).all()
                for ar in app_requests:
                    result['requested'].append({
                        'id': f"app-{ar.id}",
                        'tmdb_id': ar.tmdb_id,
                        'tvdb_id': None,
                        'title': ar.title or 'Unknown',
                        'year': '',
                        'media_type': ar.media_type or 'movie',
                        'status': 'Requested',
                        'requested_by': 'SeekAndWatch',
                        'requested_via': ar.requested_via or 'Radarr',
                        'added': ar.requested_at.isoformat() if ar.requested_at else '',
                        'poster': None,
                    })
            except Exception:
                pass
        except Exception as e:
            _log_api_exception("get_media_overview_overseerr", e)
    elif media_type in ['all', 'requested']:
        # no Overseerr configured - still show requests made from the app (Radarr/Sonarr)
        try:
            app_requests = AppRequest.query.order_by(AppRequest.requested_at.desc()).limit(500).all()
            for ar in app_requests:
                result['requested'].append({
                    'id': f"app-{ar.id}",
                    'tmdb_id': ar.tmdb_id,
                    'tvdb_id': None,
                    'title': ar.title or 'Unknown',
                    'year': '',
                    'media_type': ar.media_type or 'movie',
                    'status': 'Requested',
                    'requested_by': 'SeekAndWatch',
                    'requested_via': ar.requested_via or 'Radarr',
                    'added': ar.requested_at.isoformat() if ar.requested_at else '',
                    'poster': None,
                })
        except Exception:
            pass
    
    # Fetch Radarr movies
    if media_type in ['all', 'movies'] and s.radarr_url and s.radarr_api_key:
        try:
            headers = {'X-Api-Key': s.radarr_api_key}
            base_url = s.radarr_url.rstrip('/')
            movies_url = f"{base_url}/api/v3/movie"
            movies_resp = requests.get(movies_url, headers=headers, timeout=10)
            if movies_resp.status_code == 200:
                movies_data = movies_resp.json()
                for movie in movies_data:
                    file_info = movie.get('movieFile', {})
                    has_file = bool(file_info)
                    size = file_info.get('size', 0) if file_info else 0
                    quality = file_info.get('quality', {}).get('quality', {}).get('name', 'Unknown') if file_info else movie.get('qualityProfile', {}).get('name', 'Unknown')
                    
                    result['movies'].append({
                        'id': movie.get('id'),
                        'tmdb_id': movie.get('tmdbId'),
                        'title': movie.get('title'),
                        'year': movie.get('year', ''),
                        'status': 'Downloading' if movie.get('hasFile') == False and movie.get('monitored') else ('Imported' if has_file else 'Missing'),
                        'monitored': movie.get('monitored', False),
                        'has_file': has_file,
                        'quality': quality,
                        'size': size,
                        'added': movie.get('added'),
                        'tags': [t.get('label', '') for t in movie.get('tags', [])],
                        'poster': movie.get('images', [{}])[0].get('url') if movie.get('images') else None,
                    })
        except Exception as e:
            _log_api_exception("get_media_overview_radarr", e)
    
    # Fetch Sonarr shows
    if media_type in ['all', 'shows'] and s.sonarr_url and s.sonarr_api_key:
        try:
            headers = {'X-Api-Key': s.sonarr_api_key}
            base_url = s.sonarr_url.rstrip('/')
            series_url = f"{base_url}/api/v3/series"
            series_resp = requests.get(series_url, headers=headers, timeout=10)
            if series_resp.status_code == 200:
                series_data = series_resp.json()
                for show in series_data:
                    # Calculate total size from episodes
                    total_size = 0
                    has_episodes = False
                    try:
                        episodes_url = f"{base_url}/api/v3/episode?seriesId={show.get('id')}"
                        episodes_resp = requests.get(episodes_url, headers=headers, timeout=5)
                        if episodes_resp.status_code == 200:
                            episodes = episodes_resp.json()
                            for ep in episodes:
                                # treat as having file if hasFile, episodeFile present, or episodeFileId > 0 (some Sonarr versions omit episodeFile or set hasFile false)
                                ef_id = ep.get('episodeFileId')
                                has_file = ep.get('hasFile') or ep.get('episodeFile') or (ef_id is not None and int(ef_id) > 0)
                                if has_file:
                                    has_episodes = True
                                    file_info = ep.get('episodeFile') if isinstance(ep.get('episodeFile'), dict) else {}
                                    if file_info:
                                        total_size += file_info.get('size', 0)
                    except: pass
                    
                    result['shows'].append({
                        'id': show.get('id'),
                        'tvdb_id': show.get('tvdbId'),
                        'tmdb_id': show.get('tvMazeId'),  # Sonarr uses tvMazeId, not tmdbId directly
                        'title': show.get('title'),
                        'year': show.get('year', ''),
                        'status': 'Downloading' if not has_episodes and show.get('monitored') else ('Imported' if has_episodes else 'Missing'),
                        'monitored': show.get('monitored', False),
                        'has_file': has_episodes,
                        'quality': show.get('qualityProfile', {}).get('name', 'Unknown'),
                        'size': total_size,
                        'added': show.get('added'),
                        'tags': [t.get('label', '') for t in show.get('tags', [])],
                        'poster': show.get('images', [{}])[0].get('url') if show.get('images') else None,
                    })
        except Exception as e:
            _log_api_exception("get_media_overview_sonarr", e)
    
    # Apply filters and sorting
    def apply_filters_and_sort(items):
        filtered = items
        if filters['monitored']:
            monitored_val = filters['monitored'].lower() == 'true'
            filtered = [i for i in filtered if i.get('monitored') == monitored_val]
        if filters['status']:
            filtered = [i for i in filtered if i.get('status') in filters['status']]
        if filters['has_file']:
            has_file_val = filters['has_file'].lower() == 'true'
            filtered = [i for i in filtered if i.get('has_file') == has_file_val]
        if filters['source']:
            filtered = [i for i in filtered if i.get('requested_via') == filters['source']]
        if filters['year_min']:
            filtered = [i for i in filtered if i.get('year') and int(str(i.get('year', 0))) >= filters['year_min']]
        if filters['year_max']:
            filtered = [i for i in filtered if i.get('year') and int(str(i.get('year', 0))) <= filters['year_max']]
        if filters['size_min']:
            filtered = [i for i in filtered if i.get('size', 0) >= filters['size_min']]
        if filters['size_max']:
            filtered = [i for i in filtered if i.get('size', 0) <= filters['size_max']]
        
        # Sorting
        if sort_by == 'added_desc':
            filtered.sort(key=lambda x: x.get('added', ''), reverse=True)
        elif sort_by == 'added_asc':
            filtered.sort(key=lambda x: x.get('added', ''))
        elif sort_by == 'title_asc':
            filtered.sort(key=lambda x: x.get('title', '').lower())
        elif sort_by == 'title_desc':
            filtered.sort(key=lambda x: x.get('title', '').lower(), reverse=True)
        elif sort_by == 'size_desc':
            filtered.sort(key=lambda x: x.get('size', 0), reverse=True)
        elif sort_by == 'size_asc':
            filtered.sort(key=lambda x: x.get('size', 0))
        elif sort_by == 'year_desc':
            filtered.sort(key=lambda x: int(str(x.get('year', 0))), reverse=True)
        elif sort_by == 'year_asc':
            filtered.sort(key=lambda x: int(str(x.get('year', 0))))
        
        return filtered
    
    result['requested'] = apply_filters_and_sort(result['requested'])
    result['movies'] = apply_filters_and_sort(result['movies'])
    result['shows'] = apply_filters_and_sort(result['shows'])
    
    return jsonify({'status': 'success', 'data': result})

@api_bp.route('/api/radarr/add', methods=['POST'], endpoint='add_to_radarr')
@login_required
def add_to_radarr():
    """Add a movie to Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    data = request.json
    tmdb_id = data.get('tmdb_id')
    if not tmdb_id:
        return jsonify({'status': 'error', 'message': 'TMDB ID required'})
    
    # Check if movie is already owned before attempting to add
    try:
        owned_keys = get_plex_cache(s)
        # Fetch movie details from TMDB to check ownership
        if s.tmdb_key:
            tmdb_check_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={s.tmdb_key}"
            tmdb_check_resp = requests.get(tmdb_check_url, timeout=5)
            if tmdb_check_resp.status_code == 200:
                tmdb_item = tmdb_check_resp.json()
                if is_owned_item(tmdb_item, owned_keys, 'movie'):
                    movie_title = tmdb_item.get('title', 'This movie')
                    return jsonify({'status': 'error', 'message': f'{movie_title} is already in your library'})
    except Exception as e:
        # If ownership check fails, continue anyway (don't block the request)
        write_log("warning", "Radarr", f"Ownership check failed: {str(e)}")
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        
        # Get root folder and quality profile
        root_folders_url = f"{base_url}/api/v3/rootfolder"
        root_resp = requests.get(root_folders_url, headers=headers, timeout=5)
        if root_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch root folders'})
        root_folders_data = root_resp.json()
        # Handle both list and dict responses
        if isinstance(root_folders_data, dict):
            root_folders = root_folders_data.get('records', root_folders_data.get('data', []))
        else:
            root_folders = root_folders_data if isinstance(root_folders_data, list) else []
        
        # ensure root_folders is actually a list
        if not isinstance(root_folders, list):
            root_folders = []
        
        if not root_folders or len(root_folders) == 0:
            return jsonify({'status': 'error', 'message': 'No root folders configured'})
        
        # Get path from first folder (handle both dict and string formats)
        first_folder = root_folders[0]
        if isinstance(first_folder, dict):
            root_folder_path = first_folder.get('path')
        elif isinstance(first_folder, (list, tuple)) and len(first_folder) > 0:
            # nested list - try to extract path from first element
            nested_item = first_folder[0]
            root_folder_path = nested_item.get('path') if isinstance(nested_item, dict) else str(nested_item)
        else:
            root_folder_path = str(first_folder)
        
        if not root_folder_path:
            return jsonify({'status': 'error', 'message': 'Failed to extract root folder path'})
        
        # Get quality profile - use provided one or default to first available
        quality_profile_id = data.get('quality_profile_id')
        if not quality_profile_id:
            quality_profiles_url = f"{base_url}/api/v3/qualityprofile"
            quality_resp = requests.get(quality_profiles_url, headers=headers, timeout=5)
            if quality_resp.status_code != 200:
                return jsonify({'status': 'error', 'message': 'Failed to fetch quality profiles'})
            quality_profiles_data = quality_resp.json()
            
            # Handle both list and dict responses
            if isinstance(quality_profiles_data, dict):
                quality_profiles = quality_profiles_data.get('records', quality_profiles_data.get('data', []))
            else:
                quality_profiles = quality_profiles_data if isinstance(quality_profiles_data, list) else []
            
            if not quality_profiles or len(quality_profiles) == 0:
                return jsonify({'status': 'error', 'message': 'No quality profiles configured'})
            
            # Get id from first profile (handle both dict and other formats)
            first_profile = quality_profiles[0]
            
            if isinstance(first_profile, dict):
                quality_profile_id = first_profile.get('id')
            elif isinstance(first_profile, (int, str)):
                quality_profile_id = int(first_profile) if isinstance(first_profile, str) and first_profile.isdigit() else first_profile
            elif isinstance(first_profile, (list, tuple)):
                # Nested list - try to extract ID from first element
                if len(first_profile) > 0:
                    nested_item = first_profile[0]
                    if isinstance(nested_item, dict):
                        quality_profile_id = nested_item.get('id')
                    elif isinstance(nested_item, (int, str)):
                        quality_profile_id = int(nested_item) if isinstance(nested_item, str) and nested_item.isdigit() else nested_item
                    else:
                        quality_profile_id = None
                else:
                    quality_profile_id = None
            else:
                quality_profile_id = None
            
            if not quality_profile_id:
                return jsonify({'status': 'error', 'message': f'Failed to extract quality profile ID from response. Got: {type(first_profile)}'})
        
        # Get movie details from TMDB
        if not s.tmdb_key:
            return jsonify({'status': 'error', 'message': 'TMDB API key required'})
        tmdb_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={s.tmdb_key}"
        tmdb_resp = requests.get(tmdb_url, timeout=5)
        if tmdb_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch movie details'})
        tmdb_data = tmdb_resp.json()
        
        # Add to Radarr
        add_url = f"{base_url}/api/v3/movie"
        payload = {
            'title': tmdb_data.get('title'),
            'qualityProfileId': quality_profile_id,
            'titleSlug': tmdb_data.get('title', '').lower().replace(' ', '-'),
            'images': [],
            'tmdbId': tmdb_id,
            'year': int(tmdb_data.get('release_date', '')[:4]) if tmdb_data.get('release_date') else None,
            'rootFolderPath': root_folder_path,
            'monitored': True,
            'addOptions': {'searchForMovie': True}
        }
        
        add_resp = requests.post(add_url, json=payload, headers=headers, timeout=10)
        if add_resp.status_code in [200, 201]:
            title = tmdb_data.get('title') or 'Unknown'
            try:
                app_req = AppRequest(tmdb_id=int(tmdb_id), media_type='movie', title=title, requested_via='Radarr')
                db.session.add(app_req)
                db.session.commit()
            except Exception:
                db.session.rollback()
            write_log("info", "Radarr", f"Added {title} to Radarr")
            return jsonify({'status': 'success', 'message': f"Added {title} to Radarr"})
        else:
            # handle error response - could be dict or list
            try:
                error_data = add_resp.json()
                if isinstance(error_data, dict):
                    error_msg = error_data.get('message', 'Failed to add movie')
                elif isinstance(error_data, list) and len(error_data) > 0:
                    # if it's a list, try to get message from first item
                    first_error = error_data[0]
                    error_msg = first_error.get('message', 'Failed to add movie') if isinstance(first_error, dict) else str(first_error)
                else:
                    error_msg = add_resp.text[:200] if add_resp.text else 'Failed to add movie'
            except:
                error_msg = add_resp.text[:200] if add_resp.text else 'Failed to add movie'
            return jsonify({'status': 'error', 'message': error_msg})
    except Exception as e:
        _log_api_exception("add_to_radarr", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/quality-profiles', methods=['GET'])
@login_required
def get_radarr_quality_profiles():
    """grab quality profiles from radarr"""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured', 'profiles': []})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        quality_profiles_url = f"{base_url}/api/v3/qualityprofile"
        quality_resp = requests.get(quality_profiles_url, headers=headers, timeout=5)
        if quality_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch quality profiles', 'profiles': []})
        quality_profiles_data = quality_resp.json()
        
        # Handle both list and dict responses
        if isinstance(quality_profiles_data, dict):
            quality_profiles = quality_profiles_data.get('records', quality_profiles_data.get('data', []))
        else:
            quality_profiles = quality_profiles_data if isinstance(quality_profiles_data, list) else []
        
        # Safely extract profiles - only process dict items
        profiles = []
        for p in quality_profiles:
            if isinstance(p, dict):
                profile_id = p.get('id')
                profile_name = p.get('name', 'Unknown')
                if profile_id is not None:
                    profiles.append({'id': profile_id, 'name': profile_name})
        
        return jsonify({'status': 'success', 'profiles': profiles})
    except Exception as e:
        _log_api_exception("get_radarr_quality_profiles", e)
        return jsonify({'status': 'error', 'message': str(e), 'profiles': []})

@api_bp.route('/api/sonarr/quality-profiles', methods=['GET'])
@login_required
def get_sonarr_quality_profiles():
    """grab quality profiles from sonarr"""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured', 'profiles': []})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        quality_profiles_url = f"{base_url}/api/v3/qualityprofile"
        quality_resp = requests.get(quality_profiles_url, headers=headers, timeout=5)
        if quality_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch quality profiles', 'profiles': []})
        quality_profiles_data = quality_resp.json()
        
        # Handle both list and dict responses
        if isinstance(quality_profiles_data, dict):
            quality_profiles = quality_profiles_data.get('records', quality_profiles_data.get('data', []))
        else:
            quality_profiles = quality_profiles_data if isinstance(quality_profiles_data, list) else []
        
        # Safely extract profiles - only process dict items
        profiles = []
        for p in quality_profiles:
            if isinstance(p, dict):
                profile_id = p.get('id')
                profile_name = p.get('name', 'Unknown')
                if profile_id is not None:
                    profiles.append({'id': profile_id, 'name': profile_name})
        
        return jsonify({'status': 'success', 'profiles': profiles})
    except Exception as e:
        _log_api_exception("get_sonarr_quality_profiles", e)
        return jsonify({'status': 'error', 'message': str(e), 'profiles': []})

@api_bp.route('/api/sonarr/add', methods=['POST'])
@login_required
def add_to_sonarr():
    """Add a TV show to Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    data = request.json
    tmdb_id = data.get('tmdb_id')
    if not tmdb_id:
        return jsonify({'status': 'error', 'message': 'TMDB ID required'})
    
    # Check if TV show is already owned before attempting to add
    try:
        owned_keys = get_plex_cache(s)
        # Fetch TV show details from TMDB to check ownership
        if s.tmdb_key:
            tmdb_check_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={s.tmdb_key}"
            tmdb_check_resp = requests.get(tmdb_check_url, timeout=5)
            if tmdb_check_resp.status_code == 200:
                tmdb_item = tmdb_check_resp.json()
                if is_owned_item(tmdb_item, owned_keys, 'tv'):
                    show_title = tmdb_item.get('name', 'This TV show')
                    return jsonify({'status': 'error', 'message': f'{show_title} is already in your library'})
    except Exception as e:
        # If ownership check fails, continue anyway (don't block the request)
        write_log("warning", "Sonarr", f"Ownership check failed: {str(e)}")
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        # Get root folder and quality profile
        root_folders_url = f"{base_url}/api/v3/rootfolder"
        root_resp = requests.get(root_folders_url, headers=headers, timeout=5)
        if root_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch root folders'})
        root_folders = root_resp.json()
        if not root_folders:
            return jsonify({'status': 'error', 'message': 'No root folders configured'})
        root_folder_path = root_folders[0].get('path')
        
        # Get quality profile - use provided one or default to first available
        quality_profile_id = data.get('quality_profile_id')
        if not quality_profile_id:
            quality_profiles_url = f"{base_url}/api/v3/qualityprofile"
            quality_resp = requests.get(quality_profiles_url, headers=headers, timeout=5)
            if quality_resp.status_code != 200:
                return jsonify({'status': 'error', 'message': 'Failed to fetch quality profiles'})
            quality_profiles = quality_resp.json()
            if not quality_profiles:
                return jsonify({'status': 'error', 'message': 'No quality profiles configured'})
            quality_profile_id = quality_profiles[0].get('id')
        
        # Get TV show details from TMDB
        if not s.tmdb_key:
            return jsonify({'status': 'error', 'message': 'TMDB API key required'})
        tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={s.tmdb_key}"
        tmdb_resp = requests.get(tmdb_url, timeout=5)
        if tmdb_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch TV show details'})
        tmdb_data = tmdb_resp.json()
        
        # Sonarr lookup: try TMDB ID first, then TVDB ID (from TMDB external_ids), then by title
        # (Sonarr/SkyHook sometimes returns empty for tmdb: so fallbacks help)
        lookup_url = f"{base_url}/api/v3/series/lookup?term=tmdb:{tmdb_id}"
        lookup_resp = requests.get(lookup_url, headers=headers, timeout=10)
        series_list = lookup_resp.json() if lookup_resp.status_code == 200 else []

        if not series_list:
            # try TVDB ID from TMDB external_ids
            ext_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/external_ids?api_key={s.tmdb_key}"
            ext_resp = requests.get(ext_url, timeout=5)
            if ext_resp.status_code == 200:
                ext = ext_resp.json()
                tvdb_id = ext.get('tvdb_id') or ext.get('tvdbId')
                if tvdb_id:
                    lookup_url = f"{base_url}/api/v3/series/lookup?term=tvdb:{tvdb_id}"
                    lookup_resp = requests.get(lookup_url, headers=headers, timeout=10)
                    series_list = lookup_resp.json() if lookup_resp.status_code == 200 else []
            if not series_list:
                # last resort: lookup by title (might return multiple; pick match by tmdb_id)
                title = tmdb_data.get('name') or tmdb_data.get('original_name') or ''
                if title:
                    lookup_url = f"{base_url}/api/v3/series/lookup?term={quote_plus(title)}"
                    lookup_resp = requests.get(lookup_url, headers=headers, timeout=10)
                    candidates = lookup_resp.json() if lookup_resp.status_code == 200 else []
                    for c in candidates:
                        if isinstance(c, dict) and str(c.get('tmdbId')) == str(tmdb_id):
                            series_list = [c]
                            break
                    if not series_list and candidates:
                        series_list = [candidates[0]]
        if not series_list:
            return jsonify({'status': 'error', 'message': 'Show not found in Sonarr lookup'})

        series_data = series_list[0]
        
        # Add to Sonarr
        add_url = f"{base_url}/api/v3/series"
        payload = {
            'title': series_data.get('title'),
            'qualityProfileId': quality_profile_id,
            'titleSlug': series_data.get('titleSlug'),
            'images': series_data.get('images', []),
            'tvdbId': series_data.get('tvdbId'),
            'tmdbId': tmdb_id,
            'year': series_data.get('year'),
            'rootFolderPath': root_folder_path,
            'monitored': True,
            'addOptions': {'searchForMissingEpisodes': True, 'monitor': 'all'}
        }
        
        add_resp = requests.post(add_url, json=payload, headers=headers, timeout=10)
        if add_resp.status_code in [200, 201]:
            title = series_data.get('title') or 'Unknown'
            try:
                app_req = AppRequest(tmdb_id=int(tmdb_id), media_type='tv', title=title, requested_via='Sonarr')
                db.session.add(app_req)
                db.session.commit()
            except Exception:
                db.session.rollback()
            write_log("info", "Sonarr", f"Added {title} to Sonarr")
            return jsonify({'status': 'success', 'message': f"Added {title} to Sonarr"})
        else:
            error_msg = add_resp.json().get('message', 'Failed to add show')
            return jsonify({'status': 'error', 'message': error_msg})
    except Exception as e:
        _log_api_exception("add_to_sonarr", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/toggle_monitored/<int:movie_id>', methods=['POST'])
@login_required
def toggle_radarr_monitored(movie_id):
    """Toggle monitored status for a Radarr movie."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        
        # Get current movie
        movie_url = f"{base_url}/api/v3/movie/{movie_id}"
        movie_resp = requests.get(movie_url, headers=headers, timeout=5)
        if movie_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Movie not found'})
        
        movie_data = movie_resp.json()
        movie_data['monitored'] = not movie_data.get('monitored', False)
        
        # Update movie
        update_resp = requests.put(movie_url, json=movie_data, headers=headers, timeout=5)
        if update_resp.status_code in [200, 202]:
            return jsonify({'status': 'success', 'monitored': movie_data['monitored']})
        return jsonify({'status': 'error', 'message': 'Failed to update'})
    except Exception as e:
        _log_api_exception("toggle_radarr_monitored", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/toggle_monitored/<int:series_id>', methods=['POST'])
@login_required
def toggle_sonarr_monitored(series_id):
    """Toggle monitored status for a Sonarr series."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        # Get current series
        series_url = f"{base_url}/api/v3/series/{series_id}"
        series_resp = requests.get(series_url, headers=headers, timeout=5)
        if series_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Series not found'})
        
        series_data = series_resp.json()
        series_data['monitored'] = not series_data.get('monitored', False)
        
        # Update series
        update_resp = requests.put(series_url, json=series_data, headers=headers, timeout=5)
        if update_resp.status_code in [200, 202]:
            return jsonify({'status': 'success', 'monitored': series_data['monitored']})
        return jsonify({'status': 'error', 'message': 'Failed to update'})
    except Exception as e:
        _log_api_exception("toggle_sonarr_monitored", e)
        return jsonify({'status': 'error', 'message': str(e)})

def _safe_get_nested_rating_value(movie, rating_type):
    """Safely extract nested rating value, handling cases where structure might be different."""
    try:
        ratings = movie.get('ratings', {})
        if not isinstance(ratings, dict):
            return 0
        rating_obj = ratings.get(rating_type, {})
        if isinstance(rating_obj, dict):
            return rating_obj.get('value', 0)
        elif isinstance(rating_obj, (int, float)):
            return rating_obj
        return 0
    except (AttributeError, TypeError):
        return 0

@api_bp.route('/api/radarr/movie/<int:movie_id>', methods=['GET'])
@login_required
def get_radarr_movie_detail(movie_id):
    """Get detailed movie information from Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Get movie details
        movie_url = f"{base_url}/api/v3/movie/{movie_id}"
        movie_resp = requests.get(movie_url, headers=headers, timeout=10)
        if movie_resp.status_code == 404:
            return jsonify({'status': 'error', 'message': 'Movie not found - it may have been deleted from Radarr', 'deleted': True})
        if movie_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': f'Failed to fetch movie (Status: {movie_resp.status_code})'})
        
        movie = movie_resp.json()
        
        # Get queue to check for paused/active downloads
        queue_info = None
        try:
            queue_url = f"{base_url}/api/v3/queue"
            queue_resp = requests.get(queue_url, headers=headers, timeout=5)
            if queue_resp.status_code == 200:
                queue_data = queue_resp.json()
                # Handle both paginated and non-paginated responses
                queue_records = queue_data.get('records', []) if isinstance(queue_data, dict) else queue_data
                if isinstance(queue_records, list):
                    for item in queue_records:
                        # Radarr queue can have movieId directly or nested in movie object
                        item_movie_id = item.get('movieId')
                        if not item_movie_id and item.get('movie'):
                            movie_obj = item.get('movie')
                            if isinstance(movie_obj, dict):
                                item_movie_id = movie_obj.get('id')
                        
                        # Check if this queue item matches our movie
                        if item_movie_id == movie_id:
                            # Check if paused or downloading
                            status = item.get('status', '').lower()
                            tracked_state = item.get('trackedDownloadState', '').lower()
                            tracked_status = item.get('trackedDownloadStatus', '').lower()
                            
                            # Determine if paused
                            is_paused = (
                                'paused' in status or 
                                'paused' in tracked_state or 
                                'paused' in tracked_status or
                                tracked_state == 'paused'
                            )
                            
                            # Determine if downloading
                            is_downloading = (
                                'downloading' in status or 
                                'downloading' in tracked_state or
                                tracked_state == 'downloading'
                            )
                            
                            queue_info = {
                                'paused': is_paused,
                                'downloading': is_downloading,
                                'status': item.get('status', ''),
                                'trackedDownloadState': item.get('trackedDownloadState', ''),
                                'title': item.get('title', ''),
                                'size': item.get('size', 0),
                                'sizeleft': item.get('sizeleft', 0)
                            }
                            break  # Found the queue item for this movie
        except Exception as e:
            # Don't fail if queue check fails, just log it
            try:
                write_log("warning", "Radarr", f"Failed to check queue: {e}")
            except:
                pass
        
        # Get movie files
        files = []
        if movie.get('movieFile'):
            movie_file = movie['movieFile']
            # Safely extract quality - handle cases where quality might be a string or nested dict
            quality_name = 'Unknown'
            if movie_file.get('quality'):
                quality_obj = movie_file.get('quality')
                if isinstance(quality_obj, dict):
                    quality_inner = quality_obj.get('quality', {})
                    if isinstance(quality_inner, dict):
                        quality_name = quality_inner.get('name', 'Unknown')
                    elif isinstance(quality_inner, str):
                        quality_name = quality_inner
                elif isinstance(quality_obj, str):
                    quality_name = quality_obj
            
            # Safely extract mediaInfo
            media_info = {}
            if movie_file.get('mediaInfo'):
                media_info_obj = movie_file.get('mediaInfo')
                if isinstance(media_info_obj, dict):
                    media_info = {
                        'videoCodec': media_info_obj.get('videoCodec', ''),
                        'audioCodec': media_info_obj.get('audioCodec', ''),
                        'audioChannels': media_info_obj.get('audioChannels', ''),
                        'resolution': media_info_obj.get('resolution', ''),
                    }
            
            # Safely extract languages
            languages = []
            if movie_file.get('languages'):
                langs = movie_file.get('languages')
                if isinstance(langs, list):
                    languages = [lang.get('name', '') if isinstance(lang, dict) else str(lang) for lang in langs]
                elif isinstance(langs, str):
                    languages = [langs]
            
            # Extract custom formats (for scoring/profile matching)
            custom_formats = []
            custom_format_score = 0
            
            # try to get custom formats from embedded movieFile first
            # check multiple possible field names (radarr versions vary)
            cf_list = (movie_file.get('customFormats') or 
                      movie_file.get('customFormat') or 
                      movie_file.get('custom_formats') or 
                      movie_file.get('custom_format') or 
                      movie_file.get('formats') or 
                      [])
            
            if cf_list:
                if isinstance(cf_list, list):
                    # Extract format names - handle both dict format {name: "...", score: X} and string format
                    for cf in cf_list:
                        if cf:
                            if isinstance(cf, dict):
                                # try different possible field names
                                cf_name = (cf.get('name') or cf.get('label') or cf.get('title') or 
                                          cf.get('id') or cf.get('format') or '')
                                if cf_name:
                                    custom_formats.append(str(cf_name))
                                
                                # also check if score is stored per-format (some radarr versions)
                                if cf.get('score') is not None:
                                    try:
                                        format_score = int(cf.get('score', 0))
                                        if format_score > 0:
                                            # sum up per-format scores if they exist
                                            if custom_format_score == 0:
                                                custom_format_score = format_score
                                            else:
                                                custom_format_score += format_score
                                    except (ValueError, TypeError):
                                        pass
                            elif isinstance(cf, str):
                                if cf:
                                    custom_formats.append(cf)
            
            # try fetching the file separately to get complete custom format data
            # (some radarr versions don't include full custom format data/score in the movie response)
            if movie_file.get('id'):
                try:
                    movie_file_id = movie_file.get('id')
                    movie_file_url = f"{base_url}/api/v3/moviefile/{movie_file_id}"
                    movie_file_resp = requests.get(movie_file_url, headers=headers, timeout=10)
                    if movie_file_resp.status_code == 200:
                        full_movie_file = movie_file_resp.json()
                        # extract formats from the full movie file response - check multiple field names
                        cf_list = (full_movie_file.get('customFormats') or 
                                  full_movie_file.get('customFormat') or 
                                  full_movie_file.get('custom_formats') or 
                                  full_movie_file.get('custom_format') or 
                                  full_movie_file.get('formats') or 
                                  [])
                        if cf_list and isinstance(cf_list, list):
                            # use formats from separately fetched file if we found any (more complete)
                            if len(cf_list) > 0:
                                custom_formats = []  # reset and use the separately fetched ones
                                for cf in cf_list:
                                    if cf:
                                        if isinstance(cf, dict):
                                            cf_name = (cf.get('name') or cf.get('label') or cf.get('title') or 
                                                      cf.get('id') or cf.get('format') or '')
                                            if cf_name:
                                                custom_formats.append(str(cf_name))
                                            
                                            # also check if score is stored per-format
                                            if cf.get('score') is not None:
                                                try:
                                                    format_score = int(cf.get('score', 0))
                                                    if format_score > 0:
                                                        if custom_format_score == 0:
                                                            custom_format_score = format_score
                                                        else:
                                                            custom_format_score += format_score
                                                except (ValueError, TypeError):
                                                    pass
                                        elif isinstance(cf, str):
                                            if cf:
                                                custom_formats.append(cf)
                        
                        # also extract score from separately fetched file - check multiple field names
                        score_fields = ['customFormatScore', 'custom_format_score', 'formatScore', 'score']
                        for field in score_fields:
                            if field in full_movie_file:
                                try:
                                    fetched_score = int(full_movie_file.get(field, 0))
                                    custom_format_score = fetched_score
                                    break
                                except (ValueError, TypeError):
                                    pass
                except Exception as e:
                    write_log("warning", "Radarr", f"Failed to fetch movieFile separately: {e}")
            
            # Get custom format score - check multiple possible locations and field names
            score_fields = ['customFormatScore', 'custom_format_score', 'formatScore', 'score']
            custom_format_score = 0
            for field in score_fields:
                if field in movie_file and movie_file.get(field) is not None:
                    try:
                        custom_format_score = int(movie_file.get(field))
                        break
                    except (ValueError, TypeError):
                        pass
            if custom_format_score == 0:
                for field in score_fields:
                    if field in movie and movie.get(field) is not None:
                        try:
                            custom_format_score = int(movie.get(field))
                            break
                        except (ValueError, TypeError):
                            pass
            
            files.append({
                'path': movie_file.get('relativePath', '') if isinstance(movie_file.get('relativePath'), str) else '',
                'size': movie_file.get('size', 0) if isinstance(movie_file.get('size'), (int, float)) else 0,
                'dateAdded': movie_file.get('dateAdded', '') if isinstance(movie_file.get('dateAdded'), str) else '',
                'quality': quality_name,
                'mediaInfo': media_info,
                'languages': languages,
                'releaseGroup': movie_file.get('releaseGroup', '') if isinstance(movie_file.get('releaseGroup'), str) else '',
                'edition': movie_file.get('edition', '') if isinstance(movie_file.get('edition'), str) else '',
                'customFormats': custom_formats,
                'customFormatScore': custom_format_score,
            })
        
        # Extract images - safely handle images array
        poster_url = None
        fanart_url = None
        if movie.get('images'):
            images = movie.get('images', [])
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict):
                        cover_type = img.get('coverType')
                        url = img.get('url')
                        if cover_type == 'poster' and url and not poster_url:
                            poster_url = url
                        elif cover_type == 'fanart' and url and not fanart_url:
                            fanart_url = url
        
        # Convert relative URLs to absolute URLs
        if poster_url and not poster_url.startswith('http'):
            if poster_url.startswith('/'):
                poster_url = f"{base_url}{poster_url}"
            else:
                poster_url = f"{base_url}/{poster_url}"
        if fanart_url and not fanart_url.startswith('http'):
            if fanart_url.startswith('/'):
                fanart_url = f"{base_url}{fanart_url}"
            else:
                fanart_url = f"{base_url}/{fanart_url}"
        
        # Get cast and crew from TMDB if available
        cast = []
        crew = []
        if s.tmdb_key and movie.get('tmdbId'):
            try:
                tmdb_url = f"https://api.themoviedb.org/3/movie/{movie['tmdbId']}?api_key={s.tmdb_key}&append_to_response=credits"
                tmdb_resp = requests.get(tmdb_url, timeout=5)
                if tmdb_resp.status_code == 200:
                    tmdb_data = tmdb_resp.json()
                    credits = tmdb_data.get('credits', {})
                    if isinstance(credits, dict):
                        cast_list = credits.get('cast', [])
                        if isinstance(cast_list, list):
                            cast = [{
                                'name': c.get('name', '') if isinstance(c, dict) else '',
                                'character': c.get('character', '') if isinstance(c, dict) else '',
                                'profile_path': c.get('profile_path', '') if isinstance(c, dict) else ''
                            } for c in cast_list[:20] if isinstance(c, dict)]
                        crew_list = credits.get('crew', [])
                        if isinstance(crew_list, list):
                            crew = [{
                                'name': c.get('name', '') if isinstance(c, dict) else '',
                                'job': c.get('job', '') if isinstance(c, dict) else '',
                                'department': c.get('department', '') if isinstance(c, dict) else '',
                                'profile_path': c.get('profile_path', '') if isinstance(c, dict) else ''
                            } for c in crew_list[:30] if isinstance(c, dict)]
            except Exception as e:
                write_log("warning", "Radarr", f"Failed to fetch TMDB credits: {e}")
        
        # Alternative titles - safely handle list
        alternative_titles = []
        if movie.get('alternateTitles'):
            alt_titles = movie.get('alternateTitles', [])
            if isinstance(alt_titles, list):
                alternative_titles = [{
                    'title': alt.get('title', '') if isinstance(alt, dict) else str(alt),
                    'sourceType': alt.get('sourceType', '') if isinstance(alt, dict) else ''
                } for alt in alt_titles if alt]
        
        import time
        # Construct Radarr URL - use same logic as list endpoint
        # Get the actual movie ID from the response (not the parameter)
        actual_movie_id = movie.get('id')
        tmdb_id = movie.get('tmdbId')
        
        # Use same logic as list endpoint: if ID seems wrong (low number), try TMDB ID
        try:
            if tmdb_id is not None and actual_movie_id and actual_movie_id < 10000 and tmdb_id != actual_movie_id:
                # The ID seems wrong (low number), try using TMDB ID for the web UI URL
                radarr_url = f"{base_url}/movie/{tmdb_id}"
            else:
                # Use the actual movie ID from the response
                radarr_url = f"{base_url}/movie/{actual_movie_id}"
        except Exception as e:
            # Fallback to using the API ID if there's any error
            write_log("warning", "Radarr", f"Error constructing URL for movie '{movie.get('title')}': {e}")
            radarr_url = f"{base_url}/movie/{actual_movie_id}"
        
        # also check movie-level custom formats (some radarr versions store them here)
        movie_level_formats = []
        movie_level_score = 0
        
        # check multiple possible field names for movie-level formats
        movie_cf_list = (movie.get('customFormats') or 
                         movie.get('customFormat') or 
                         movie.get('custom_formats') or 
                         movie.get('custom_format') or 
                         movie.get('formats') or 
                         [])
        
        if movie_cf_list and isinstance(movie_cf_list, list):
            for cf in movie_cf_list:
                if cf:
                    if isinstance(cf, dict):
                        cf_name = (cf.get('name') or cf.get('label') or cf.get('title') or 
                                  cf.get('id') or cf.get('format') or '')
                        if cf_name:
                            movie_level_formats.append(str(cf_name))
                    elif isinstance(cf, str):
                        if cf:
                            movie_level_formats.append(cf)
        
        # check multiple possible field names for movie-level score
        score_fields = ['customFormatScore', 'custom_format_score', 'formatScore', 'score']
        for field in score_fields:
            if movie.get(field) is not None:
                try:
                    movie_level_score = int(movie.get(field, 0))
                    break
                except (ValueError, TypeError):
                    pass
        
        
        # Build result dictionary first
        result = {
            'status': 'success',
            'movie': {
                'id': actual_movie_id,
                'title': movie.get('title'),
                'year': movie.get('year'),
                'overview': movie.get('overview'),
                'runtime': movie.get('runtime'),
                'certification': movie.get('certification'),
                'genres': [g.get('name', '') if isinstance(g, dict) else str(g) for g in movie.get('genres', []) if g],
                'studio': movie.get('studio', ''),
                'path': movie.get('path', ''),
                'monitored': movie.get('monitored', False),
                'hasFile': movie.get('hasFile', False),
                'tmdbId': tmdb_id,
                'imdbId': movie.get('imdbId'),
                'added': movie.get('added'),
                'posterUrl': poster_url,
                'fanartUrl': fanart_url,
                'files': files,
                'cast': cast,
                'crew': crew,
                'alternativeTitles': alternative_titles,
                'ratings': {
                    'tmdb': _safe_get_nested_rating_value(movie, 'tmdb'),
                    'imdb': _safe_get_nested_rating_value(movie, 'imdb'),
                    'rottenTomatoes': _safe_get_nested_rating_value(movie, 'rottenTomatoes'),
                },
                'radarrUrl': radarr_url,
                'customFormats': movie_level_formats,  # include movie-level formats
                'customFormatScore': movie_level_score,  # include movie-level score
                'queueStatus': None,  # Will be set if in queue
                '_fetchedAt': int(time.time())  # Timestamp for cache validation
            }
        }
        
        # Add queue status if movie is in queue
        if queue_info:
            if queue_info.get('paused'):
                result['movie']['queueStatus'] = 'paused'
            elif queue_info.get('downloading'):
                result['movie']['queueStatus'] = 'downloading'
            else:
                result['movie']['queueStatus'] = 'queued'
            result['movie']['queueTitle'] = queue_info.get('title', '')
            result['movie']['queueSize'] = queue_info.get('size', 0)
            result['movie']['queueSizeLeft'] = queue_info.get('sizeleft', 0)
        
        return jsonify(result)
    except Exception as e:
        _log_api_exception("get_radarr_movie_detail", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/series/<int:series_id>', methods=['GET'])
@login_required
def get_sonarr_series_detail(series_id):
    """Get detailed TV series information from Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Get series details
        series_url = f"{base_url}/api/v3/series/{series_id}"
        series_resp = requests.get(series_url, headers=headers, timeout=10)
        if series_resp.status_code == 404:
            return jsonify({'status': 'error', 'message': 'Series not found - it may have been deleted from Sonarr', 'deleted': True})
        if series_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': f'Failed to fetch series (Status: {series_resp.status_code})'})
        
        series = series_resp.json()
        
        # Get queue to check for paused/active downloads
        queue_items_by_episode = {}  # episodeId -> queue item
        try:
            queue_url = f"{base_url}/api/v3/queue"
            queue_resp = requests.get(queue_url, headers=headers, timeout=5)
            if queue_resp.status_code == 200:
                queue_data = queue_resp.json()
                # Handle both paginated and non-paginated responses
                queue_records = queue_data.get('records', []) if isinstance(queue_data, dict) else queue_data
                if isinstance(queue_records, list):
                    for item in queue_records:
                        # Sonarr queue can have episodeId directly or nested in episode object
                        episode_id = item.get('episodeId')
                        if not episode_id and item.get('episode'):
                            episode_obj = item.get('episode')
                            if isinstance(episode_obj, dict):
                                episode_id = episode_obj.get('id')
                        
                        if episode_id:
                            # Check if paused or downloading
                            status = item.get('status', '').lower()
                            tracked_state = item.get('trackedDownloadState', '').lower()
                            tracked_status = item.get('trackedDownloadStatus', '').lower()
                            
                            # Determine if paused
                            is_paused = (
                                'paused' in status or 
                                'paused' in tracked_state or 
                                'paused' in tracked_status or
                                tracked_state == 'paused'
                            )
                            
                            # Determine if downloading
                            is_downloading = (
                                'downloading' in status or 
                                'downloading' in tracked_state or
                                tracked_state == 'downloading'
                            )
                            
                            queue_items_by_episode[episode_id] = {
                                'paused': is_paused,
                                'downloading': is_downloading,
                                'status': item.get('status', ''),
                                'trackedDownloadState': item.get('trackedDownloadState', ''),
                                'title': item.get('title', ''),
                                'size': item.get('size', 0),
                                'sizeleft': item.get('sizeleft', 0)
                            }
        except Exception as e:
            # Don't fail if queue check fails, just log it
            try:
                write_log("warning", "Sonarr", f"Failed to check queue: {e}")
            except:
                pass
        
        # Get episodes - safely handle response and extract file details
        episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
        episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
        episodes = []
        if episodes_resp.status_code == 200:
            episodes_data = episodes_resp.json()
            if isinstance(episodes_data, list):
                for ep in episodes_data:
                    if not isinstance(ep, dict):
                        continue
                    
                    episode_id = ep.get('id')
                    queue_info = queue_items_by_episode.get(episode_id)
                    
                    # treat as has file if Sonarr says so, episodeFile is present, or episodeFileId > 0 (some Sonarr versions omit episodeFile or set hasFile false)
                    ep_file_id = ep.get('episodeFileId')
                    ep_has_file = ep.get('hasFile', False) or bool(ep.get('episodeFile')) or (ep_file_id is not None and int(ep_file_id) > 0)
                    episode_data = {
                        'id': episode_id,
                        'seasonNumber': ep.get('seasonNumber'),
                        'episodeNumber': ep.get('episodeNumber'),
                        'title': ep.get('title', ''),
                        'overview': ep.get('overview', ''),
                        'airDate': ep.get('airDate', ''),
                        'hasFile': ep_has_file,
                        'monitored': ep.get('monitored', False),
                        'file': None,
                        'queueStatus': None  # Will be set if in queue
                    }
                    
                    # Add queue status if episode is in queue
                    if queue_info:
                        if queue_info.get('paused'):
                            episode_data['queueStatus'] = 'paused'
                        elif queue_info.get('downloading'):
                            episode_data['queueStatus'] = 'downloading'
                        else:
                            episode_data['queueStatus'] = 'queued'
                        episode_data['queueTitle'] = queue_info.get('title', '')
                        episode_data['queueSize'] = queue_info.get('size', 0)
                        episode_data['queueSizeLeft'] = queue_info.get('sizeleft', 0)
                    
                    # Extract detailed file information if episode has a file
                    if ep_has_file and ep.get('episodeFile'):
                        episode_file = ep.get('episodeFile', {})
                        if isinstance(episode_file, dict):
                            # Extract quality
                            quality_name = 'Unknown'
                            if episode_file.get('quality'):
                                quality_obj = episode_file.get('quality')
                                if isinstance(quality_obj, dict):
                                    quality_inner = quality_obj.get('quality', {})
                                    if isinstance(quality_inner, dict):
                                        quality_name = quality_inner.get('name', 'Unknown')
                                    elif isinstance(quality_inner, str):
                                        quality_name = quality_inner
                                elif isinstance(quality_obj, str):
                                    quality_name = quality_obj
                            
                            # Extract mediaInfo
                            media_info = {}
                            if episode_file.get('mediaInfo'):
                                media_info_obj = episode_file.get('mediaInfo')
                                if isinstance(media_info_obj, dict):
                                    media_info = {
                                        'videoCodec': media_info_obj.get('videoCodec', ''),
                                        'audioCodec': media_info_obj.get('audioCodec', ''),
                                        'audioChannels': media_info_obj.get('audioChannels', ''),
                                        'resolution': media_info_obj.get('resolution', ''),
                                    }
                            
                            # Extract languages
                            languages = []
                            if episode_file.get('languages'):
                                langs = episode_file.get('languages')
                                if isinstance(langs, list):
                                    languages = [lang.get('name', '') if isinstance(lang, dict) else str(lang) for lang in langs]
                                elif isinstance(langs, str):
                                    languages = [langs]
                            
                            # Extract custom formats
                            custom_formats = []
                            custom_format_score = 0
                            if episode_file.get('customFormats'):
                                cf_list = episode_file.get('customFormats', [])
                                if isinstance(cf_list, list):
                                    for cf in cf_list:
                                        if cf:
                                            if isinstance(cf, dict):
                                                # try different possible field names
                                                cf_name = (cf.get('name') or cf.get('label') or cf.get('title') or '')
                                                if cf_name:
                                                    custom_formats.append(str(cf_name))
                                            elif isinstance(cf, str):
                                                if cf:
                                                    custom_formats.append(cf)
                            if episode_file.get('customFormatScore') is not None:
                                try:
                                    custom_format_score = int(episode_file.get('customFormatScore', 0))
                                except (ValueError, TypeError):
                                    custom_format_score = 0
                            
                            episode_data['file'] = {
                                'path': episode_file.get('relativePath', '') if isinstance(episode_file.get('relativePath'), str) else '',
                                'size': episode_file.get('size', 0) if isinstance(episode_file.get('size'), (int, float)) else 0,
                                'dateAdded': episode_file.get('dateAdded', '') if isinstance(episode_file.get('dateAdded'), str) else '',
                                'quality': quality_name,
                                'mediaInfo': media_info,
                                'languages': languages,
                                'releaseGroup': episode_file.get('releaseGroup', '') if isinstance(episode_file.get('releaseGroup'), str) else '',
                                'customFormats': custom_formats,
                                'customFormatScore': custom_format_score,
                            }
                    
                    episodes.append(episode_data)
        
        # Extract images - safely handle images array
        poster_url = None
        fanart_url = None
        if series.get('images'):
            images = series.get('images', [])
            if isinstance(images, list):
                for img in images:
                    if isinstance(img, dict):
                        cover_type = img.get('coverType')
                        url = img.get('url')
                        if cover_type == 'poster' and url and not poster_url:
                            poster_url = url
                        elif cover_type == 'fanart' and url and not fanart_url:
                            fanart_url = url
        
        # Convert relative URLs to absolute URLs
        if poster_url and not poster_url.startswith('http'):
            if poster_url.startswith('/'):
                poster_url = f"{base_url}{poster_url}"
            else:
                poster_url = f"{base_url}/{poster_url}"
        if fanart_url and not fanart_url.startswith('http'):
            if fanart_url.startswith('/'):
                fanart_url = f"{base_url}{fanart_url}"
            else:
                fanart_url = f"{base_url}/{fanart_url}"
        
        # Get cast and crew from TMDB if available
        cast = []
        crew = []
        if s.tmdb_key and series.get('tvdbId'):
            try:
                # Sonarr uses TVDB ID, but TMDB API can use it too
                tmdb_url = f"https://api.themoviedb.org/3/find/{series['tvdbId']}?api_key={s.tmdb_key}&external_source=tvdb_id"
                find_resp = requests.get(tmdb_url, timeout=5)
                if find_resp.status_code == 200:
                    find_data = find_resp.json()
                    tv_results = find_data.get('tv_results', [])
                    if tv_results:
                        tmdb_id = tv_results[0].get('id')
                        tmdb_series_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={s.tmdb_key}&append_to_response=credits"
                        tmdb_resp = requests.get(tmdb_series_url, timeout=5)
                        if tmdb_resp.status_code == 200:
                            tmdb_data = tmdb_resp.json()
                            credits = tmdb_data.get('credits', {})
                            cast_list = credits.get('cast', [])
                            if isinstance(cast_list, list):
                                cast = [{
                                    'name': c.get('name', '') if isinstance(c, dict) else '',
                                    'character': c.get('character', '') if isinstance(c, dict) else '',
                                    'profile_path': c.get('profile_path', '') if isinstance(c, dict) else ''
                                } for c in cast_list[:20] if isinstance(c, dict)]
                            crew_list = credits.get('crew', [])
                            if isinstance(crew_list, list):
                                crew = [{
                                    'name': c.get('name', '') if isinstance(c, dict) else '',
                                    'job': c.get('job', '') if isinstance(c, dict) else '',
                                    'department': c.get('department', '') if isinstance(c, dict) else '',
                                    'profile_path': c.get('profile_path', '') if isinstance(c, dict) else ''
                                } for c in crew_list[:30] if isinstance(c, dict)]
            except Exception as e:
                write_log("warning", "Sonarr", f"Failed to fetch TMDB credits: {e}")
        
        # Alternative titles
        alternative_titles = []
        if series.get('alternateTitles'):
            alternative_titles = [{
                'title': alt.get('title', ''),
                'sourceType': alt.get('sourceType', '')
            } for alt in series.get('alternateTitles', [])]
        
        # Construct Sonarr URL - Sonarr uses titleSlug for web UI URLs (e.g., /series/free-bert)
        title_slug = series.get('titleSlug')
        actual_series_id = series.get('id')
        sonarr_url = None
        try:
            if title_slug:
                # Use titleSlug if available (this is what Sonarr web UI uses)
                sonarr_url = f"{base_url}/series/{title_slug}"
            elif actual_series_id:
                # Fallback to series ID if no slug available
                sonarr_url = f"{base_url}/series/{actual_series_id}"
        except Exception as e:
            # Fallback to using the API ID if there's any error
            try:
                write_log("warning", "Sonarr", f"Error constructing URL for series: {e}")
            except:
                pass  # don't fail if logging fails
            sonarr_url = f"{base_url}/series/{actual_series_id}" if actual_series_id else None
        
        import time
        return jsonify({
            'status': 'success',
            'series': {
                'id': series.get('id'),
                'title': series.get('title'),
                'year': series.get('year'),
                'yearEnd': series.get('yearEnd'),  # End year for series
                'status': series.get('status', ''),  # Series status (e.g., 'ended', 'continuing')
                'overview': series.get('overview'),
                'runtime': series.get('runtime'),
                'network': series.get('network', ''),
                'genres': [g.get('name', '') if isinstance(g, dict) else str(g) for g in series.get('genres', []) if g],
                'path': series.get('path', ''),
                'monitored': series.get('monitored', False),
                'hasFile': series.get('hasFile', False),
                'tvdbId': series.get('tvdbId'),
                'imdbId': series.get('imdbId'),
                'added': series.get('added'),
                'tags': series.get('tags', []),  # Series tags
                'posterUrl': poster_url,
                'fanartUrl': fanart_url,
                'episodes': episodes,
                'cast': cast,
                'crew': crew,
                'alternativeTitles': alternative_titles,
                'ratings': {
                    'tmdb': _safe_get_nested_rating_value(series, 'tmdb'),
                    'imdb': _safe_get_nested_rating_value(series, 'imdb'),
                },
                'sonarrUrl': sonarr_url,
                '_fetchedAt': int(time.time())  # Timestamp for cache validation
            }
        })
    except Exception as e:
        _log_api_exception("get_sonarr_series_detail", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/search', methods=['POST'])
@login_required
def radarr_search():
    """Search for a movie in Radarr (auto search or interactive)."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'})
    
    movie_id = data.get('movie_id')
    search_type = data.get('type', 'auto')  # 'auto' or 'interactive'
    
    # Validate movie_id
    if not movie_id:
        return jsonify({'status': 'error', 'message': 'Movie ID required'})
    try:
        movie_id = int(movie_id)
        if movie_id <= 0 or movie_id > 2147483647:  # Max 32-bit int
            return jsonify({'status': 'error', 'message': 'Invalid movie ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid movie ID format'})
    
    # Validate search_type
    if search_type not in ['auto', 'interactive']:
        return jsonify({'status': 'error', 'message': 'Invalid search type'})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        
        if search_type == 'auto':
            # Auto search using command
            command_url = f"{base_url}/api/v3/command"
            payload = {
                'name': 'MoviesSearch',
                'movieIds': [movie_id]
            }
            resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
            if resp.status_code in [200, 201]:
                return jsonify({'status': 'success', 'message': 'Search started'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to start search'})
        
        elif search_type == 'interactive':
            # Get releases for interactive search
            releases_url = f"{base_url}/api/v3/release?movieId={movie_id}"
            resp = requests.get(releases_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                releases = resp.json()
                # Log first release to debug downloadAllowed field
                if releases and len(releases) > 0:
                    write_log("info", "Radarr", f"Fetched {len(releases)} release(s) for movie")
                return jsonify({'status': 'success', 'releases': releases})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to fetch releases'})
        
        return jsonify({'status': 'error', 'message': 'Invalid search type'})
    except Exception as e:
        _log_api_exception("radarr_search", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/refresh/<int:movie_id>', methods=['POST'])
@login_required
def radarr_refresh_scan(movie_id):
    """Refresh and scan a movie in Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Command to refresh and scan
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'RefreshMovie',
            'movieIds': [movie_id]
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            return jsonify({'status': 'success', 'message': 'Refresh and scan started'})
        return jsonify({'status': 'error', 'message': 'Failed to start refresh'})
    except Exception as e:
        _log_api_exception("radarr_refresh_scan", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/search-scan/<int:movie_id>', methods=['POST'])
@login_required
def radarr_search_scan(movie_id):
    """Search and scan a movie in Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Command to search and scan
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'MoviesSearch',
            'movieIds': [movie_id]
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            # Also trigger refresh
            refresh_payload = {
                'name': 'RefreshMovie',
                'movieIds': [movie_id]
            }
            requests.post(command_url, json=refresh_payload, headers=headers, timeout=10)
            return jsonify({'status': 'success', 'message': 'Search and scan started'})
        return jsonify({'status': 'error', 'message': 'Failed to start search'})
    except Exception as e:
        _log_api_exception("radarr_search_scan", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/refresh/<int:series_id>', methods=['POST'])
@login_required
def sonarr_refresh_scan(series_id):
    """Refresh and scan a series in Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Command to refresh and scan
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'RefreshSeries',
            'seriesId': series_id
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            return jsonify({'status': 'success', 'message': 'Refresh and scan started'})
        return jsonify({'status': 'error', 'message': 'Failed to start refresh'})
    except Exception as e:
        _log_api_exception("sonarr_refresh_scan", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/search-scan/<int:series_id>', methods=['POST'])
@login_required
def sonarr_search_scan(series_id):
    """Search and scan a series in Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Command to search and scan
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'SeriesSearch',
            'seriesId': series_id
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            # Also trigger refresh
            refresh_payload = {
                'name': 'RefreshSeries',
                'seriesId': series_id
            }
            requests.post(command_url, json=refresh_payload, headers=headers, timeout=10)
            return jsonify({'status': 'success', 'message': 'Search and scan started'})
        return jsonify({'status': 'error', 'message': 'Failed to start search'})
    except Exception as e:
        _log_api_exception("sonarr_search_scan", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/search-season/<int:series_id>/<int:season_number>', methods=['POST'])
@login_required
def sonarr_search_season(series_id, season_number):
    """Search for all monitored episodes in a season."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Get episodes for the season
        episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
        episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
        if episodes_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch episodes'})
        
        episodes = episodes_resp.json()
        season_episodes = [ep.get('id') for ep in episodes if ep.get('seasonNumber') == season_number and ep.get('monitored', False)]
        
        if not season_episodes:
            return jsonify({'status': 'success', 'message': 'No monitored episodes in this season'})
        
        # Search for episodes
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'EpisodeSearch',
            'episodeIds': season_episodes
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            return jsonify({'status': 'success', 'message': f'Search started for {len(season_episodes)} episode(s)'})
        return jsonify({'status': 'error', 'message': 'Failed to start search'})
    except Exception as e:
        _log_api_exception("sonarr_search_season", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/refresh-season/<int:series_id>/<int:season_number>', methods=['POST'])
@login_required
def sonarr_refresh_season(series_id, season_number):
    """Refresh all episodes in a season."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Get episodes for the season
        episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
        episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
        if episodes_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Failed to fetch episodes'})
        
        episodes = episodes_resp.json()
        season_episodes = [ep.get('id') for ep in episodes if ep.get('seasonNumber') == season_number]
        
        if not season_episodes:
            return jsonify({'status': 'success', 'message': 'No episodes in this season'})
        
        # Refresh episodes
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'EpisodeSearch',
            'episodeIds': season_episodes
        }
        # First trigger refresh for the series
        refresh_payload = {
            'name': 'RefreshSeries',
            'seriesId': series_id
        }
        requests.post(command_url, json=refresh_payload, headers=headers, timeout=10)
        
        return jsonify({'status': 'success', 'message': f'Refresh started for season {season_number}'})
    except Exception as e:
        _log_api_exception("sonarr_refresh_season", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/search-episode/<int:episode_id>', methods=['POST'])
@login_required
def sonarr_search_episode(episode_id):
    """Search for a specific episode."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Search for episode
        command_url = f"{base_url}/api/v3/command"
        payload = {
            'name': 'EpisodeSearch',
            'episodeIds': [episode_id]
        }
        resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            return jsonify({'status': 'success', 'message': 'Search started for episode'})
        return jsonify({'status': 'error', 'message': 'Failed to start search'})
    except Exception as e:
        _log_api_exception("sonarr_search_episode", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/refresh-episode/<int:episode_id>', methods=['POST'])
@login_required
def sonarr_refresh_episode(episode_id):
    """Refresh a specific episode."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        if base_url.endswith('/api'):
            base_url = base_url[:-4]
        if base_url.endswith('/api/v3'):
            base_url = base_url[:-7]
        
        # Get episode to find series ID
        episode_url = f"{base_url}/api/v3/episode/{episode_id}"
        episode_resp = requests.get(episode_url, headers=headers, timeout=10)
        if episode_resp.status_code != 200:
            return jsonify({'status': 'error', 'message': 'Episode not found'})
        
        episode = episode_resp.json()
        series_id = episode.get('seriesId')
        
        if not series_id:
            return jsonify({'status': 'error', 'message': 'Invalid episode data'})
        
        # Refresh the series (which will refresh all episodes)
        command_url = f"{base_url}/api/v3/command"
        refresh_payload = {
            'name': 'RefreshSeries',
            'seriesId': series_id
        }
        resp = requests.post(command_url, json=refresh_payload, headers=headers, timeout=10)
        if resp.status_code in [200, 201]:
            return jsonify({'status': 'success', 'message': 'Refresh started for episode'})
        return jsonify({'status': 'error', 'message': 'Failed to start refresh'})
    except Exception as e:
        _log_api_exception("sonarr_refresh_episode", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/radarr/download', methods=['POST'])
@login_required
@rate_limit_decorator("20 per minute")
def radarr_download():
    """Download a specific release in Radarr."""
    s = current_user.settings
    if not s.radarr_url or not s.radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr not configured'})
    
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'})
    
    guid = data.get('guid')
    indexer_id = data.get('indexerId')
    movie_id = data.get('movieId')
    release_data = data.get('releaseData')  # Full release object if provided
    override = data.get('override', False)  # Override flag for forced downloads
    
    # Validate guid
    if not guid:
        return jsonify({'status': 'error', 'message': 'Release GUID required'})
    if not isinstance(guid, str) or len(guid) > 2000:  # Reasonable limit
        return jsonify({'status': 'error', 'message': 'Invalid GUID format'})
    
    # Validate indexer_id
    if indexer_id is None:
        return jsonify({'status': 'error', 'message': 'Indexer ID required'})
    try:
        indexer_id = int(indexer_id)
        if indexer_id < 0 or indexer_id > 2147483647:
            return jsonify({'status': 'error', 'message': 'Invalid indexer ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid indexer ID format'})
    
    # Validate movie_id
    if not movie_id:
        return jsonify({'status': 'error', 'message': 'Movie ID required'})
    try:
        movie_id = int(movie_id)
        if movie_id <= 0 or movie_id > 2147483647:
            return jsonify({'status': 'error', 'message': 'Invalid movie ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid movie ID format'})
    
    # Validate release_data structure if provided
    if release_data is not None:
        if not isinstance(release_data, dict):
            return jsonify({'status': 'error', 'message': 'Invalid release data format'})
        # Limit size of release_data to prevent DoS
        import json
        if len(json.dumps(release_data)) > 50000:  # 50KB limit
            return jsonify({'status': 'error', 'message': 'Release data too large'})
    
    # Use mappedMovieId from release_data if available (Radarr sets this to match release to movie)
    # Otherwise use the movieId from the request
    if release_data and isinstance(release_data, dict) and release_data.get('mappedMovieId'):
        try:
            mapped_id = int(release_data.get('mappedMovieId'))
            if mapped_id > 0 and mapped_id <= 2147483647:
                movie_id = mapped_id
        except (ValueError, TypeError):
            pass  # Use original movie_id if mappedMovieId is invalid
    
    try:
        headers = {'X-Api-Key': s.radarr_api_key}
        base_url = s.radarr_url.rstrip('/')
        
        download_url = f"{base_url}/api/v3/release"
        
        # Build payload - Radarr API expects specific fields
        # Based on Radarr API docs, the release endpoint needs: guid, indexerId, movieId
        # Optional: downloadClientId, downloadUrl, magnetUrl
        # We should NOT send fields that Radarr sets internally (approved, rejected, quality, protocol, etc.)
        # Radarr will determine these from the guid/indexerId
        if release_data and isinstance(release_data, dict):
            # Start with required fields only
            payload = {
                'guid': guid,
                'indexerId': indexer_id,
                'movieId': movie_id
            }
            
            # Include downloadUrl if available (Radarr needs this to download)
            if release_data.get('downloadUrl'):
                payload['downloadUrl'] = release_data['downloadUrl']
            
            # Include magnetUrl if downloadUrl is not available
            if not payload.get('downloadUrl') and release_data.get('magnetUrl'):
                payload['magnetUrl'] = release_data['magnetUrl']
            
            # Include downloadClientId if specified (Radarr can use this to route to specific client)
            if release_data.get('downloadClientId') is not None:
                payload['downloadClientId'] = release_data['downloadClientId']
            
            # Note: We intentionally do NOT send:
            # - quality (Radarr determines this from guid/indexerId)
            # - protocol (Radarr determines this from the release)
            # - approved (Radarr sets this internally)
            # - infoHash (not needed for download endpoint)
            
            write_log("info", "Radarr", f"Download requested for movie (movieId: {movie_id})")
        else:
            # Fallback to minimal payload
            payload = {
                'guid': guid,
                'indexerId': indexer_id,
                'movieId': movie_id
            }
            write_log("info", "Radarr", f"Download requested for movie (movieId: {movie_id}, minimal payload)")
        
        resp = requests.post(download_url, json=payload, headers=headers, timeout=10)
        
        resp_text_raw = resp.text if resp.text else 'No response body'
        try:
            resp_data = resp.json() if resp.content else {}
        except Exception as parse_err:
            write_log("warning", "Radarr", "Could not parse download response")
            resp_data = {}
        
        if resp.status_code in [200, 201]:
            # Radarr can return 200 OK but with error messages in the response body
            # Check for various error indicators
            error_msg = None
            
            if isinstance(resp_data, dict):
                # Check for error messages in various possible fields
                error_msg = (resp_data.get('message') or 
                           resp_data.get('errorMessage') or 
                           resp_data.get('error') or
                           resp_data.get('errorMessage'))
                
                # Check for errors array
                if not error_msg and resp_data.get('errors'):
                    errors = resp_data['errors']
                    if isinstance(errors, list) and len(errors) > 0:
                        first_error = errors[0]
                        if isinstance(first_error, dict):
                            error_msg = first_error.get('errorMessage') or first_error.get('message')
                    elif isinstance(errors, dict):
                        error_msg = errors.get('errorMessage') or errors.get('message')
                
                # Check if response indicates failure
                if resp_data.get('success') is False:
                    error_msg = error_msg or resp_data.get('message') or 'Download failed'
                
                # Check for rejection reasons
                if resp_data.get('rejected') is True:
                    rejections = resp_data.get('rejections', [])
                    if rejections:
                        error_msg = error_msg or '; '.join(rejections) if isinstance(rejections, list) else str(rejections)
                    else:
                        error_msg = error_msg or 'Release was rejected'
            
            # Also check if it's an array with error objects
            elif isinstance(resp_data, list) and len(resp_data) > 0:
                first_item = resp_data[0]
                if isinstance(first_item, dict):
                    error_msg = first_item.get('message') or first_item.get('errorMessage')
            
            if error_msg:
                write_log("error", "Radarr", f"Download failed: {error_msg}")
                # Provide more helpful error message
                if 'download client' in error_msg.lower() or 'failed to add' in error_msg.lower():
                    enhanced_msg = f"{error_msg}\n\nThis usually means:\n- Radarr's download client configuration is incorrect\n- Download client is offline or unreachable\n- Check Radarr Settings → Download Clients"
                else:
                    enhanced_msg = error_msg
                
                # Include the full response in the error message for debugging
                return jsonify({
                    'status': 'error', 
                    'message': enhanced_msg,
                    'radarr_response': resp_data  # Include full response for debugging
                })
            
            if not resp_data or (isinstance(resp_data, dict) and len(resp_data) == 0):
                write_log("warning", "Radarr", "Download returned empty response")
            
            write_log("info", "Radarr", "Download started successfully")
            return jsonify({'status': 'success', 'message': 'Download started'})
        else:
            # Try to get detailed error message from Radarr
            try:
                error_data = resp.json()
                # Radarr error responses can have different structures
                error_msg = (error_data.get('message') or 
                           error_data.get('errorMessage') or 
                           error_data.get('error') or
                           (error_data.get('errors') and isinstance(error_data['errors'], list) and len(error_data['errors']) > 0 and error_data['errors'][0].get('errorMessage')) or
                           str(error_data) if error_data else 'Failed to start download')
                write_log("error", "Radarr", f"Download failed: {error_msg}")
            except Exception as parse_error:
                error_msg = f'Failed to start download (status {resp.status_code})'
                write_log("error", "Radarr", f"Download failed: {error_msg}")
            return jsonify({'status': 'error', 'message': error_msg})
    except Exception as e:
        _log_api_exception("radarr_download", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/search', methods=['POST'])
@login_required
@rate_limit_decorator("30 per minute")
def sonarr_search():
    """Search for episodes in Sonarr (auto search or interactive)."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'})
    
    series_id = data.get('series_id')
    episode_ids = data.get('episode_ids', [])  # For specific episodes
    search_type = data.get('type', 'auto')  # 'auto' or 'interactive'
    
    # Validate series_id
    if not series_id:
        return jsonify({'status': 'error', 'message': 'Series ID required'})
    try:
        series_id = int(series_id)
        if series_id <= 0 or series_id > 2147483647:
            return jsonify({'status': 'error', 'message': 'Invalid series ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid series ID format'})
    
    # Validate episode_ids if provided
    if episode_ids:
        if not isinstance(episode_ids, list) or len(episode_ids) > 100:  # Reasonable limit
            return jsonify({'status': 'error', 'message': 'Invalid episode IDs'})
        try:
            episode_ids = [int(eid) for eid in episode_ids if int(eid) > 0 and int(eid) <= 2147483647]
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Invalid episode ID format'})
    
    # Validate search_type
    if search_type not in ['auto', 'interactive']:
        return jsonify({'status': 'error', 'message': 'Invalid search type'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        if search_type == 'auto':
            # If no episode IDs provided, search for all missing episodes
            if not episode_ids:
                # Get all missing episodes for the series
                episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
                episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
                if episodes_resp.status_code == 200:
                    episodes = episodes_resp.json()
                    def _has_file(ep):
                        if ep.get('hasFile') or ep.get('episodeFile'): return True
                        eid = ep.get('episodeFileId')
                        return eid is not None and int(eid) > 0
                    episode_ids = [ep.get('id') for ep in episodes if not _has_file(ep)]
            
            if not episode_ids:
                return jsonify({'status': 'success', 'message': 'No missing episodes to search'})
            
            # Auto search using command
            command_url = f"{base_url}/api/v3/command"
            payload = {
                'name': 'EpisodeSearch',
                'episodeIds': episode_ids
            }
            resp = requests.post(command_url, json=payload, headers=headers, timeout=10)
            if resp.status_code in [200, 201]:
                return jsonify({'status': 'success', 'message': f'Search started for {len(episode_ids)} episode(s)'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to start search'})
        
        elif search_type == 'interactive':
            # Get episodes first
            episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
            episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
            if episodes_resp.status_code != 200:
                return jsonify({'status': 'error', 'message': 'Failed to fetch episodes'})
            
            episodes = episodes_resp.json()
            def _ep_has_f(ep):
                if ep.get('hasFile') or ep.get('episodeFile'): return True
                eid = ep.get('episodeFileId')
                return eid is not None and int(eid) > 0
            missing_episodes = [ep for ep in episodes if not _ep_has_f(ep)]
            
            if not missing_episodes:
                return jsonify({'status': 'error', 'message': 'No missing episodes found'})
            
            # Get releases for first missing episode (or user can specify)
            episode_id = episode_ids[0] if episode_ids else missing_episodes[0].get('id')
            releases_url = f"{base_url}/api/v3/release?episodeId={episode_id}"
            resp = requests.get(releases_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                releases = resp.json()
                return jsonify({'status': 'success', 'releases': releases, 'episode': missing_episodes[0]})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to fetch releases'})
        
        return jsonify({'status': 'error', 'message': 'Invalid search type'})
    except Exception as e:
        _log_api_exception("sonarr_search", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/download', methods=['POST'])
@login_required
@rate_limit_decorator("20 per minute")
def sonarr_download():
    """Download a specific release in Sonarr."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured'})
    
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No data provided'})
    
    guid = data.get('guid')
    indexer_id = data.get('indexerId')
    episode_id = data.get('episodeId')
    
    # Validate guid
    if not guid:
        return jsonify({'status': 'error', 'message': 'Release GUID required'})
    if not isinstance(guid, str) or len(guid) > 2000:
        return jsonify({'status': 'error', 'message': 'Invalid GUID format'})
    
    # Validate indexer_id
    if indexer_id is None:
        return jsonify({'status': 'error', 'message': 'Indexer ID required'})
    try:
        indexer_id = int(indexer_id)
        if indexer_id < 0 or indexer_id > 2147483647:
            return jsonify({'status': 'error', 'message': 'Invalid indexer ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid indexer ID format'})
    
    # Validate episode_id
    if not episode_id:
        return jsonify({'status': 'error', 'message': 'Episode ID required'})
    try:
        episode_id = int(episode_id)
        if episode_id <= 0 or episode_id > 2147483647:
            return jsonify({'status': 'error', 'message': 'Invalid episode ID'})
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid episode ID format'})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        download_url = f"{base_url}/api/v3/release"
        payload = {
            'guid': guid,
            'indexerId': indexer_id,
            'episodeId': episode_id
        }
        resp = requests.post(download_url, json=payload, headers=headers, timeout=10)
        
        if resp.status_code in [200, 201]:
            # Check response content for errors (Sonarr might return 200 with error in body)
            resp_data = None
            if resp.content:
                try:
                    resp_data = resp.json()
                except:
                    pass
            
            # Check for error messages in response
            error_msg = None
            if resp_data:
                if isinstance(resp_data, dict):
                    error_msg = (resp_data.get('message') or 
                               resp_data.get('errorMessage') or 
                               resp_data.get('error'))
                # Also check if it's an array with error objects
                elif isinstance(resp_data, list) and len(resp_data) > 0:
                    first_item = resp_data[0]
                    if isinstance(first_item, dict):
                        error_msg = first_item.get('message') or first_item.get('errorMessage')
            
            if error_msg:
                write_log("error", "Sonarr", f"Download failed: {error_msg}")
                # Provide more helpful error message
                if 'download client' in error_msg.lower() or 'failed to add' in error_msg.lower():
                    enhanced_msg = f"{error_msg}\n\nThis usually means:\n- Sonarr's download client configuration is incorrect\n- Download client is offline or unreachable\n- Check Sonarr Settings → Download Clients"
                else:
                    enhanced_msg = error_msg
                
                # Include the full response in the error message for debugging
                return jsonify({
                    'status': 'error', 
                    'message': enhanced_msg,
                    'sonarr_response': resp_data  # Include full response for debugging
                })
            
            if not resp_data or (isinstance(resp_data, dict) and len(resp_data) == 0):
                write_log("warning", "Sonarr", "Download returned empty response")
            
            return jsonify({'status': 'success', 'message': 'Download started'})
        else:
            try:
                error_data = resp.json()
                error_msg = (error_data.get('message') or 
                           error_data.get('errorMessage') or 
                           error_data.get('error') or
                           (error_data.get('errors') and isinstance(error_data['errors'], list) and len(error_data['errors']) > 0 and error_data['errors'][0].get('errorMessage')) or
                           str(error_data) if error_data else 'Failed to start download')
                write_log("error", "Sonarr", f"Download failed: {error_msg}")
            except Exception as parse_error:
                error_msg = f'Failed to start download (status {resp.status_code})'
                write_log("error", "Sonarr", f"Download failed: {error_msg}")
            return jsonify({'status': 'error', 'message': error_msg})
    except Exception as e:
        _log_api_exception("sonarr_download", e)
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/api/sonarr/missing-episodes', methods=['GET'])
@login_required
def sonarr_missing_episodes():
    """Get missing episodes for a series."""
    s = current_user.settings
    if not s.sonarr_url or not s.sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr not configured', 'episodes': []})
    
    series_id = request.args.get('series_id')
    if not series_id:
        return jsonify({'status': 'error', 'message': 'Series ID required', 'episodes': []})
    
    try:
        headers = {'X-Api-Key': s.sonarr_api_key}
        base_url = s.sonarr_url.rstrip('/')
        
        episodes_url = f"{base_url}/api/v3/episode?seriesId={series_id}"
        episodes_resp = requests.get(episodes_url, headers=headers, timeout=10)
        if episodes_resp.status_code == 200:
            episodes = episodes_resp.json()
            # missing = no file: not (hasFile or episodeFile or episodeFileId > 0)
            def _ep_has_file(ep):
                h = ep.get('hasFile') or ep.get('episodeFile')
                if h: return True
                eid = ep.get('episodeFileId')
                return eid is not None and int(eid) > 0
            missing = [{
                'id': ep.get('id'),
                'seasonNumber': ep.get('seasonNumber'),
                'episodeNumber': ep.get('episodeNumber'),
                'title': ep.get('title'),
                'airDate': ep.get('airDate'),
                'airDateUtc': ep.get('airDateUtc')
            } for ep in episodes if not _ep_has_file(ep)]
            return jsonify({'status': 'success', 'episodes': missing})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to fetch episodes', 'episodes': []})
    except Exception as e:
        _log_api_exception("sonarr_missing_episodes", e)
        return jsonify({'status': 'error', 'message': str(e), 'episodes': []})