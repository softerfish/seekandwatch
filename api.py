"""API endpoints for async stuff - AJAX calls, background tasks, etc."""

import datetime
import json
import os
import random
import re
import threading
import time
import tempfile
import zipfile
from datetime import timedelta

import requests
import socket
from urllib.parse import urlparse, quote
from flask import Blueprint, request, jsonify, session, send_from_directory, current_app
from flask_login import login_required, current_user
from flask_limiter.util import get_remote_address
from plexapi.server import PlexServer
from markupsafe import escape
from werkzeug.utils import secure_filename
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User
from utils import (
    normalize_title,
    is_duplicate,
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
        write_log("ERROR", "API", f"{context}: {exc}")
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
    if candidates and not cache.get('sorted'):
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
    
    # keep filtering until we have 30 items or run out
    while len(final_list) < 30 and idx < len(candidates):
        item = candidates[idx]
        idx += 1
        
        # basic filters
        if item['year'] < min_year: continue
        if item.get('vote_average', 0) < min_rating: continue
        
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
        return {'results': []}
    if len(q) > 100:
        return {'results': []}
    if search_type not in ['movie', 'tv', 'keyword']:
        return {'results': []}
    
    if search_type == 'keyword':
        # URL encode query to prevent injection
        safe_query = quote(q[:100])  # Limit length and encode
        url = f"https://api.themoviedb.org/3/search/keyword?query={safe_query}&api_key={s.tmdb_key}"
        try:
            res = requests.get(url, timeout=5).json().get('results', [])[:10]
            return {'results': [{'id': k['id'], 'name': k['name']} for k in res]}
        except: return {'results': []}
        
    ep = 'search/tv' if search_type == 'tv' else 'search/movie'
    # URL encode query to prevent injection
    safe_query = quote(q[:100])  # Limit length and encode
    res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={safe_query}&api_key={s.tmdb_key}", timeout=5).json().get('results', [])[:5]
    
    # Normalize response format for frontend (validate search_type to prevent XSS)
    safe_type = 'tv' if search_type == 'tv' else 'movie'
    return {'results': [{'title': i.get('name') if safe_type == 'tv' else i.get('title'), 'year': (i.get('first_air_date') or i.get('release_date') or '')[:4], 'poster': i.get('poster_path')} for i in res]}

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
        r = requests.get(url, params=params).json()
        
        owned_keys = get_plex_cache(s)
        items = []
        
        # Show first 12.
        for i in r.get('results', [])[:12]:
            t = normalize_title(i.get('title', i.get('name')))
            is_owned = t in owned_keys
            
            # Fall back to alias check if title match failed.
            if not is_owned:
                if TmdbAlias.query.filter_by(tmdb_id=i['id']).first(): is_owned = True
            
            items.append({
                'title': i.get('title', i.get('name')),
                'year': (i.get('release_date') or i.get('first_air_date') or '')[:4],
                'poster_path': i.get('poster_path'),
                'owned': is_owned
            })
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

@api_bp.route('/api/scanner/reset', methods=['POST'])
@login_required
def reset_scanner():
    # nuke the alias database and start fresh
    TmdbAlias.query.delete()
    s = current_user.settings
    s.last_alias_scan = 0
    db.session.commit()
    
    write_scanner_log("Database Wiped by User.")
    write_log("INFO", "Scanner", "Alias Database wiped by user.")
    
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
        
    except Exception:
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
    except (socket.gaierror, socket.herror, OSError):
        return jsonify({'status': 'error', 'message': 'Could not resolve hostname'}), 400
    
    # Fetch the file with security measures
    try:
        response = requests.get(
            url,
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
        
    except Timeout:
        return jsonify({'status': 'error', 'message': 'Request timed out'}), 408
    except RequestException:
        return jsonify({'status': 'error', 'message': 'Failed to fetch URL'}), 400
    except Exception:
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