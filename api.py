import time
import json
import random
import requests
import datetime
import re
import os
import threading
from flask import Blueprint, request, jsonify, session, send_from_directory
from flask_login import login_required, current_user
from plexapi.server import PlexServer
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User
from utils import (normalize_title, is_duplicate, fetch_omdb_ratings, send_overseerr_request, 
                   run_collection_logic, create_backup, list_backups, restore_backup, 
                   prune_backups, BACKUP_DIR, sync_remote_aliases, get_tmdb_aliases, 
                   refresh_plex_cache, get_plex_cache, get_lock_status, is_system_locked,
                   write_scanner_log, read_scanner_log, prefetch_keywords_parallel,
                   item_matches_keywords, RESULTS_CACHE, get_session_filters, validate_url, 
                   prefetch_tv_states_parallel, prefetch_ratings_parallel)
from presets import PLAYLIST_PRESETS

# setup blueprint
api_bp = Blueprint('api', __name__)

# --- GENERATION & FILTERS ---

@api_bp.route('/load_more_recs')
@login_required
def load_more_recs():
    # bail if we don't have results cached
    if current_user.id not in RESULTS_CACHE: return jsonify([])
    
    cache = RESULTS_CACHE[current_user.id]
    candidates = cache.get('candidates', [])
    start_idx = cache.get('next_index', 0)
    
    s = current_user.settings
    min_year, min_rating, genre_filter, critic_enabled, threshold = get_session_filters()
    
    # grab allowed ratings (G, PG, etc) from session
    allowed_ratings = session.get('rating_filter', [])
    # if empty or 'all', just ignore the filter
    if not allowed_ratings or 'all' in allowed_ratings: allowed_ratings = None
    
    # parse keywords from the pipe-separated string
    raw_keywords = session.get('keywords', '')
    target_keywords = [k.strip() for k in raw_keywords.split('|') if k.strip()]
    
    batch_end = min(start_idx + 100, len(candidates))
    
    batch_items = candidates[start_idx:batch_end]
    # prefetch ratings now so UI doesn't lag
    prefetch_ratings_parallel(batch_items, s.tmdb_key)
    
    if target_keywords:
        prefetch_keywords_parallel(batch_items, s.tmdb_key)
    else:
        # keywords not needed immediately, do it async
        from flask import current_app
        def async_prefetch(app_obj, items, key):
            with app_obj.app_context():
                prefetch_keywords_parallel(items, key)
                
        threading.Thread(target=async_prefetch, 
                         args=(current_app._get_current_object(), batch_items, s.tmdb_key)).start()
    
    final_list = []
    idx = start_idx
    
    # keep going until we have 30 or run out
    while len(final_list) < 30 and idx < len(candidates):
        item = candidates[idx]
        idx += 1
        
        # basic filters first
        if item['year'] < min_year: continue
        if item.get('vote_average', 0) < min_rating: continue
        
        # content rating check (kid mode stuff)
        if allowed_ratings:
            c_rate = item.get('content_rating', 'NR')
            if str(c_rate) not in allowed_ratings: continue
            
        if genre_filter and genre_filter != 'all':
            try:
                # handle old format where it was a single int vs list
                allowed_ids = [int(g) for g in genre_filter] if isinstance(genre_filter, list) else [int(genre_filter)]
                item_genres = item.get('genre_ids', [])
                if not any(gid in allowed_ids for gid in item_genres): 
                    continue
            except: pass
            
        if target_keywords:
            if not item_matches_keywords(item, target_keywords):
                continue

        # check RT score if omdb key exists
        item['rt_score'] = None
        if s.omdb_key:
            ratings = fetch_omdb_ratings(item.get('title', item.get('name')), item['year'], s.omdb_key)
            rt_score = 0
            for r in (ratings or []):
                if r['Source'] == 'Rotten Tomatoes':
                    rt_score = int(r['Value'].replace('%',''))
                    break
            
            if rt_score > 0: item['rt_score'] = rt_score
            if critic_enabled and rt_score < threshold: continue
            
        final_list.append(item)

    # TV shows need status (ended/returning) for display
    if final_list and final_list[0].get('media_type') == 'tv':
        prefetch_tv_states_parallel(final_list, s.tmdb_key)
        
    RESULTS_CACHE[current_user.id]['next_index'] = idx
    return jsonify(final_list)

@api_bp.route('/api/update_filters', methods=['POST'])
@login_required
def update_filters():
    data = request.json
    try: session['min_year'] = int(data.get('min_year', 0))
    except: session['min_year'] = 0
        
    try: session['min_rating'] = float(data.get('min_rating', 0))
    except: session['min_rating'] = 0
        
    session['genre_filter'] = data.get('genre_filter')
    session['keywords'] = data.get('keywords', '')
    session['rating_filter'] = data.get('rating_filter', [])
    
    # reset pagination when filters change
    if current_user.id in RESULTS_CACHE:
        RESULTS_CACHE[current_user.id]['next_index'] = 0
        
    return jsonify({'status': 'success'})

@api_bp.route('/tmdb_search_proxy')
@login_required
def tmdb_search_proxy():
    s = current_user.settings
    q = request.args.get('query')
    search_type = request.args.get('type')
    if not q: return {'results': []}
    
    if search_type == 'keyword':
        url = f"https://api.themoviedb.org/3/search/keyword?query={q}&api_key={s.tmdb_key}"
        try:
            res = requests.get(url, timeout=5).json().get('results', [])[:10]
            return {'results': [{'id': k['id'], 'name': k['name']} for k in res]}
        except: return {'results': []}
        
    ep = 'search/tv' if search_type == 'tv' else 'search/movie'
    res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={q}&api_key={s.tmdb_key}", timeout=5).json().get('results', [])[:5]
    
    # normalize response format for frontend
    return {'results': [{'title': i.get('name') if request.args.get('type') == 'tv' else i.get('title'), 'year': (i.get('first_air_date') or i.get('release_date') or '')[:4], 'poster': i.get('poster_path')} for i in res]}

# --- METADATA & ACTIONS ---

@api_bp.route('/get_metadata/<media_type>/<int:tmdb_id>')
@login_required
def get_metadata(media_type, tmdb_id):
    s = current_user.settings
    try:
        # get everything in one call
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}&append_to_response=credits,videos,watch/providers"
        data = requests.get(url, timeout=5).json()
        
        # top 5 cast is enough
        cast = [c['name'] for c in data.get('credits', {}).get('cast', [])[:5]]
        
        # find trailer - prefer official ones
        trailer = None
        for v in data.get('videos', {}).get('results', []):
            if v['type'] == 'Trailer' and v['site'] == 'YouTube':
                trailer = v['key']
                break
        
        # fallback to any youtube video
        if not trailer:
             for v in data.get('videos', {}).get('results', []):
                if v['site'] == 'YouTube':
                    trailer = v['key']
                    break
                
        # streaming providers - default to US
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
        return jsonify({'error': str(e)})

@api_bp.route('/get_trailer/<media_type>/<int:tmdb_id>')
@login_required
def get_trailer(media_type, tmdb_id):
    s = current_user.settings
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/videos?api_key={s.tmdb_key}&language=en-US"
        results = requests.get(url, timeout=5).json().get('results', [])
        
        # official trailers first
        for vid in results:
            if vid['site'] == 'YouTube' and vid['type'] == 'Trailer':
                return jsonify({'status': 'success', 'key': vid['key']})
        
        # any youtube video works
        for vid in results:
            if vid['site'] == 'YouTube':
                return jsonify({'status': 'success', 'key': vid['key']})
                
        return jsonify({'status': 'error', 'message': 'No trailer found'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/request_media', methods=['POST'])
@login_required
def request_media():
    s = current_user.settings
    data = request.json
    try:
        # bulk mode from import lists
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
        
        # single request
        else:
             success, msg = send_overseerr_request(s, data['media_type'], data['tmdb_id'])
             if success:
                 return jsonify({'status': 'success'})
             else:
                 return jsonify({'status': 'error', 'message': msg})

    except Exception as e: 
        return jsonify({'status': 'error', 'message': str(e)})
        
@api_bp.route('/block_movie', methods=['POST'])
@login_required
def block_movie():
    title = request.json['title']
    media_type = request.json.get('media_type', 'movie')
    
    # avoid duplicates
    exists = Blocklist.query.filter_by(user_id=current_user.id, title=title, media_type=media_type).first()
    if not exists:
        db.session.add(Blocklist(user_id=current_user.id, title=title, media_type=media_type))
        db.session.commit()
    return {'status': 'success'}

@api_bp.route('/unblock_movie/<int:id>', methods=['POST'])
@login_required
def unblock_movie(id):
    # make sure user can only delete their own blocks
    Blocklist.query.filter_by(id=id, user_id=current_user.id).delete()
    db.session.commit()
    return {'status': 'success'}

# --- IMPORT LISTS & COLLECTIONS ---

@api_bp.route('/get_plex_libraries')
@login_required
def get_plex_libraries():
    s = current_user.settings
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        # only video libraries
        libs = [{'title': sec.title, 'type': sec.type, 'name': sec.title} for sec in plex.library.sections() if sec.type in ['movie', 'show']]
        return jsonify({'status': 'success', 'libraries': libs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
        
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
                    # use first item's poster if collection doesn't have one
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
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/match_bulk_titles', methods=['POST'])
@login_required
def match_bulk_titles():
    # paste a list of titles and match them to plex
    s = current_user.settings
    data = request.json
    raw_text = data.get('titles', '')
    target_library = data.get('target_library')
    
    # split on newlines, commas, pipes
    titles = [x.strip() for x in re.split(r'[\n,|]', raw_text) if x.strip()]
    if not titles: return jsonify({'status': 'error', 'message': 'No titles found.'})
    
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        lib = plex.library.section(target_library)
        
        results = []
        # limit to 100 so it doesn't hang
        for t in titles[:100]:
            found = False
            key = None
            final_title = t
            
            try:
                # TODO: fuzzy matching would be better here
                hits = lib.search(t)
                if hits:
                    found = True
                    key = hits[0].ratingKey
                    final_title = hits[0].title
            except: pass
            
            results.append({'query': t, 'title': final_title, 'found': found, 'key': key})
            
        return jsonify({'status': 'success', 'results': results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

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
        
        # create collection from first item
        first = lib.fetchItem(keys[0])
        col = first.addCollection(data['collection_title'])
        
        # add remaining items
        for k in keys[1:]:
            try: lib.fetchItem(k).addCollection(data['collection_title'])
            except: pass
            
        # save as custom preset so it shows in UI
        key = f"custom_import_{int(time.time())}"
        config = {'title': data['collection_title'], 'description': f"Imported Static List ({len(keys)} items)", 'media_type': 'movie', 'icon': '📋'}
        
        db.session.add(CollectionSchedule(preset_key=key, frequency='manual', configuration=json.dumps(config)))
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': 'Collection Created'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

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
        
        # show first 12
        for i in r.get('results', [])[:12]:
            t = normalize_title(i.get('title', i.get('name')))
            is_owned = t in owned_keys
            
            # fallback to alias check if title match failed
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
        return jsonify({'status': 'error', 'message': str(e)})

@api_bp.route('/create_collection/<key>', methods=['POST'])
@login_required
def create_collection(key):
    s = current_user.settings
    
    if key.startswith('custom_'):
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        preset = json.loads(job.configuration)
    else:
        preset = PLAYLIST_PRESETS.get(key, {}).copy()
        
        # check for user overrides (sync mode, etc)
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
        # update last run time
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
    frequency = request.form.get('frequency') # manual, daily, weekly
    sync_mode = request.form.get('sync_mode', 'append')

    job = CollectionSchedule.query.filter_by(preset_key=preset_key).first()
    if not job:
        job = CollectionSchedule(preset_key=preset_key)
        db.session.add(job)
    
    # keep existing config, just update what changed
    current_config = {}
    if job.configuration:
        try: current_config = json.loads(job.configuration)
        except: current_config = {}
            
    current_config['sync_mode'] = sync_mode
    
    job.frequency = frequency
    job.configuration = json.dumps(current_config)
    
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Schedule updated.'})

# --- CUSTOM BUILDER ---

@api_bp.route('/preview_custom_collection', methods=['POST'])
@login_required
def preview_custom_collection():
    # test filters before saving
    s = current_user.settings
    data = request.json
    
    # map UI fields to TMDB params
    params = {
        'api_key': s.tmdb_key,
        'sort_by': data['sort_by'],
        'vote_average.gte': data['min_rating'],
        'with_genres': data['with_genres'],
        'with_keywords': data.get('with_keywords', '')
    }
    
    # date fields differ for movies vs TV
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
        
        # try alias match if title didn't work
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
    CollectionSchedule.query.filter_by(preset_key=key).delete()
    db.session.commit()
    return jsonify({'status': 'success'})

# --- SYSTEM & SETTINGS ---

@api_bp.route('/test_connection', methods=['POST'])
@login_required
def test_connection():
    data = request.json
    service = data.get('service')
    
    # SSRF protection
    if 'url' in data and data['url']:
        is_safe, msg = validate_url(data['url'])
        if not is_safe:
            return jsonify({'status': 'error', 'message': f"Security Block: {msg}", 'msg': f"Security Block: {msg}"})

    try:
        # test logic for each service type
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
        return jsonify({'status': 'error', 'message': str(e), 'msg': str(e)})
        
        
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

@api_bp.route('/api/tautulli_data')
@login_required
def tautulli_data():
    s = current_user.settings
    if not s.tautulli_url or not s.tautulli_api_key: return jsonify({'error': 'Not Configured'})
    
    days = request.args.get('days', 30)
    stat_type = request.args.get('type', '0')
    
    try:
        base_url = s.tautulli_url.rstrip('/')
        url = f"{base_url}/api/v2?apikey={s.tautulli_api_key}&cmd=get_home_stats&time_range={days}&stats_type={stat_type}"
        
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200: return jsonify({"error": f"Tautulli Error {resp.status_code}"})
        
        try: data = resp.json()
        except: return jsonify({"error": "Invalid JSON response"})
        
        if data.get('response', {}).get('result') == 'success': return jsonify(data['response']['data'])
        return jsonify({"error": f"Tautulli Error: {data.get('response', {}).get('message')}"})
        
    except Exception as e: return jsonify({"error": f"Connection Failed: {str(e)}"})

# --- BACKUPS ---

@api_bp.route('/api/backups')
@login_required
def get_backups_api(): return jsonify(list_backups())

@api_bp.route('/api/backup/create', methods=['POST'])
@login_required
def trigger_backup():
    success, msg = create_backup()
    return jsonify({'status': 'success', 'message': msg}) if success else jsonify({'status': 'error', 'message': msg})

@api_bp.route('/api/backup/download/<filename>')
@login_required
def download_backup(filename):
    # basic path traversal check
    if '..' in filename or '/' in filename: return "Invalid", 400
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

@api_bp.route('/api/backup/delete/<filename>', methods=['DELETE'])
@login_required
def delete_backup_api(filename):
    if '..' in filename or '/' in filename: return jsonify({'status': 'error'})
    path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(path): os.remove(path)
    return jsonify({'status': 'success'})

@api_bp.route('/api/backup/restore/<filename>', methods=['POST'])
@login_required
def run_restore(filename):
    # be extra careful with paths
    if '..' in filename or '/' in filename or '\\' in filename: 
        return jsonify({'status': 'error', 'message': 'Invalid filename'})
        
    success, msg = restore_backup(filename)
    return jsonify({'status': 'success' if success else 'error', 'message': msg})

# --- CACHE & SCANNER ---

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
    # run in background thread so the UI doesn't hang
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
    # wipe everything and start over
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
def save_kometa_config():
    s = current_user.settings
    data = request.json
    s.kometa_config = json.dumps(data)
    
    # sync these settings with main config if user changed them here
    if data.get('plex_url'): s.plex_url = data['plex_url']
    if data.get('plex_token'): s.plex_token = data['plex_token']
    if data.get('tmdb_key'): s.tmdb_key = data['tmdb_key']
    
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/sync_aliases', methods=['POST'])
@login_required
def manual_alias_sync():
    # legacy button, probably not used much anymore
    success, msg = sync_remote_aliases()
    status = 'success' if success else 'error'
    try: total = TmdbAlias.query.count()
    except: total = 0
    return jsonify({'status': status, 'message': msg, 'count': total})
    
# --- ADMIN USER MANAGEMENT ---

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
@login_required
def admin_delete_user():
    if not current_user.is_admin:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
        
    data = request.json
    target_id = data.get('user_id')
    
    if target_id == current_user.id:
        return jsonify({'status': 'error', 'message': 'Cannot delete yourself.'})
        
    user = User.query.get(target_id)
    if user:
        # Cascade delete settings/blocklists to avoid orphaned rows
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
    
    # quick validation
    if ':' in new_time and len(new_time) == 5:
        s.schedule_time = new_time
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Global Run Time set to {new_time}'})
    return jsonify({'status': 'error', 'message': 'Invalid time format'})