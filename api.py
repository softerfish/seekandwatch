import time
import json
import random
import requests
import datetime
import re
import os
from flask import request, jsonify, session, send_from_directory
from flask_login import login_required, current_user
from plexapi.server import PlexServer
from app import app
from models import db, Blocklist, CollectionSchedule, TmdbAlias
# We import backup utils here
from utils import normalize_title, is_duplicate, fetch_omdb_ratings, send_overseerr_request, run_collection_logic, create_backup, list_backups, restore_backup, prune_backups, BACKUP_DIR, sync_remote_aliases
from presets import PLAYLIST_PRESETS

# --- HELPER: GET PLEX LIBRARY NAMES ---
@app.route('/get_plex_libraries')
@login_required
def get_plex_libraries():
    s = current_user.settings
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        # Return list of tuples: (Title, Type)
        libs = [{'title': sec.title, 'type': sec.type} for sec in plex.library.sections() if sec.type in ['movie', 'show']]
        return jsonify({'status': 'success', 'libraries': libs})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# --- RECOMMENDATION ENGINE ---
@app.route('/load_more_recs')
@login_required
def load_more_recs():
    start_time = time.time()
    s = current_user.settings
    page = int(request.args.get('page', 1))
    seeds = session.get('seed_titles', [])
    m_type = session.get('media_type', 'movie')
    use_critic_filter = request.args.get('critic_filter') == 'true'
    critic_threshold = session.get('critic_threshold', 70)
    recs = {}
    
    raw_reg = s.tmdb_region or 'US'
    reg_code = raw_reg.split(',')[0].strip().upper()

    try:
        p = PlexServer(s.plex_url, s.plex_token)
        lib_name = 'TV Shows' if m_type == 'tv' else 'Movies'
        section = None
        try:
            section = p.library.section(lib_name)
        except:
            for sec in p.library.sections():
                if (m_type == 'movie' and sec.type == 'movie') or (m_type == 'tv' and sec.type == 'show'):
                    section = sec
                    break
        
        lib = {normalize_title(x.title) for x in section.all()} if section else set()
    except Exception as e: 
        print(f"DEBUG: Plex Library Error: {e}", flush=True)
        lib = set()

    if seeds: random.shuffle(seeds)

    for t in seeds:
        if time.time() - start_time > 25: break
        try:
            tid = requests.get(f"https://api.themoviedb.org/3/search/{'tv' if m_type=='tv' else 'movie'}?query={t}&api_key={s.tmdb_key}", timeout=5).json()['results'][0]['id']
            endpoint = 'similar' if random.random() > 0.5 else 'recommendations'
            rand_page = random.choice([1, 2])
            discover_url = f"https://api.themoviedb.org/3/{'tv' if m_type=='tv' else 'movie'}/{tid}/{endpoint}?api_key={s.tmdb_key}&page={rand_page}"
            
            if session.get('provider_filter'):
                p_str = "|".join(session.get('provider_filter'))
                g_str = session.get('genre_filter') or ""
                discover_url = f"https://api.themoviedb.org/3/discover/{'tv' if m_type=='tv' else 'movie'}?api_key={s.tmdb_key}&with_watch_providers={p_str}&watch_region={reg_code}&with_genres={g_str}&sort_by=popularity.desc&page={page}&vote_average.gte={session.get('min_rating', 0)}"

            res = requests.get(discover_url, timeout=5).json().get('results', [])
            
            for r in res:
                if time.time() - start_time > 25: break
                if r['id'] in recs: continue
                title = r.get('name') if m_type == 'tv' else r.get('title')
                
                if is_duplicate(title, lib): continue
                if session.get('genre_filter') and int(session['genre_filter']) not in r['genre_ids']: continue
                if r.get('vote_average', 0) < session.get('min_rating', 0): continue
                
                streaming_text = None
                try:
                    prov_url = f"https://api.themoviedb.org/3/{m_type}/{r['id']}/watch/providers?api_key={s.tmdb_key}"
                    prov_data = requests.get(prov_url, timeout=3).json()
                    if 'results' in prov_data and reg_code in prov_data['results']:
                        flatrate = prov_data['results'][reg_code].get('flatrate', [])
                        if flatrate: streaming_text = ", ".join([p['provider_name'] for p in flatrate[:2]])
                except: pass

                critic_data = None
                if s.omdb_key:
                    should_fetch = use_critic_filter or (len(recs) < 12)
                    if should_fetch:
                        critic_data = fetch_omdb_ratings(r['id'], m_type, s)
                        if use_critic_filter:
                            if not critic_data: continue 
                            rt_score = critic_data.get('rt', '0%').replace('%', '')
                            if not rt_score.isdigit() or int(rt_score) < critic_threshold: continue

                date = r.get('first_air_date') if m_type == 'tv' else r.get('release_date')
                recs[r['id']] = {
                    'title': title,
                    'overview': r['overview'],
                    'poster_path': r['poster_path'],
                    'tmdb_id': r['id'],
                    'media_type': m_type,
                    'rating': r.get('vote_average'),
                    'date': (date or '')[:4],
                    'critic_ratings': critic_data,
                    'is_seed': True,                
                    'streaming_info': streaming_text 
                }
                if len(recs) >= 12: break
        except: continue
        if len(recs) >= 12: break

    return jsonify(list(recs.values()))

# --- BULK IMPORT API ---
@app.route('/match_bulk_titles', methods=['POST'])
@login_required
def match_bulk_titles():
    s = current_user.settings
    data = request.json
    raw_text = data.get('titles', '')
    target_library = data.get('target_library')
    
    search_queries = [x.strip() for x in re.split(r'[\n,|]', raw_text) if x.strip()]
    if not search_queries: return jsonify({'status': 'error', 'message': 'No titles found.'})
    
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        if target_library:
            plex_section = plex.library.section(target_library)
        else:
            media_type = data.get('media_type', 'movie')
            lib_name = 'TV Shows' if media_type == 'tv' else 'Movies'
            plex_section = plex.library.section(lib_name)
            
        tmdb_type = 'tv' if plex_section.type == 'show' else 'movie'
        
        plex_map = {}
        for item in plex_section.all():
            norm = normalize_title(item.title)
            if norm not in plex_map: plex_map[norm] = []
            plex_map[norm].append(item)
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Plex Error: {str(e)}"})

    results = []
    
    for query in search_queries[:50]: 
        match_found = False
        plex_rating_key = None
        match_title = None
        match_year = None
        
        clean_query = re.sub(r'\(\d{4}\)', '', query).strip()
        clean_query = re.sub(r'\d{4}$', '', clean_query).strip()

        norm_q = normalize_title(clean_query)
        if norm_q in plex_map:
            match_found = True
            item = plex_map[norm_q][0]
            match_title = item.title
            match_year = item.year
            plex_rating_key = item.ratingKey
        else:
            try:
                tmdb_url = f"https://api.themoviedb.org/3/search/{tmdb_type}?query={clean_query}&api_key={s.tmdb_key}"
                tmdb_res = requests.get(tmdb_url, timeout=3).json().get('results', [])
                
                if tmdb_res:
                    top_hit = tmdb_res[0]
                    t_title = top_hit.get('name') if tmdb_type == 'tv' else top_hit.get('title')
                    t_date = top_hit.get('first_air_date') if tmdb_type == 'tv' else top_hit.get('release_date')
                    t_year = int(t_date[:4]) if t_date else 0
                    
                    norm_t = normalize_title(t_title)
                    if norm_t in plex_map:
                        match_found = True
                        item = plex_map[norm_t][0]
                        match_title = item.title
                        match_year = item.year
                        plex_rating_key = item.ratingKey
                    else:
                        match_title = f"{t_title} ({t_year})"
                        match_found = False
            except: pass

        results.append({
            'query': query,
            'found': match_found,
            'title': match_title or "No Match Found",
            'year': match_year,
            'key': plex_rating_key
        })

    return jsonify({'status': 'success', 'results': results})

@app.route('/create_bulk_collection', methods=['POST'])
@login_required
def create_bulk_collection():
    s = current_user.settings
    data = request.json
    title = data.get('collection_title')
    keys = data.get('rating_keys', [])
    target_library = data.get('target_library')
    
    if not title or not keys: return jsonify({'status': 'error', 'message': 'Missing data'})
    
    try:
        plex = PlexServer(s.plex_url, s.plex_token)
        
        if target_library:
            section = plex.library.section(target_library)
        else:
            media_type = data.get('media_type', 'movie')
            lib_name = 'TV Shows' if media_type == 'tv' else 'Movies'
            section = plex.library.section(lib_name)

        # Fetch actual items first
        real_items = [section.fetchItem(int(k)) for k in keys]
        existing = [c for c in section.collections() if c.title == title]
        
        # 1. Create/Update in Plex
        if existing:
            col = existing[0]
            col.addItems(real_items)
            msg = f"Added {len(keys)} items to existing collection '{title}' in {section.title}."
        else:
            col = section.createCollection(title=title, items=real_items)
            msg = f"Created '{title}' with {len(keys)} items in {section.title}."
            
        # 2. SAVE TO DATABASE
        timestamp = int(time.time())
        preset_key = f"custom_import_{timestamp}"
        
        media_type = 'tv' if section.type == 'show' else 'movie'
        
        config = {
            'title': title,
            'media_type': media_type,
            'year_start': 'Imported', 
            'year_end': 'List',       
            'description': f"Imported list containing {len(keys)} items from {section.title}."
        }
        
        new_job = CollectionSchedule(
            preset_key=preset_key, 
            frequency='manual', 
            configuration=json.dumps(config),
            last_run=datetime.datetime.now()
        )
        db.session.add(new_job)
        db.session.commit()
            
        return jsonify({'status': 'success', 'message': msg})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})

# --- PREVIEW PRESET ROUTE ---
@app.route('/preview_preset_items/<key>', methods=['GET'])
@login_required
def preview_preset_items(key):
    s = current_user.settings
    preset = {}
    
    # 1. Check if it's a Custom Builder (DB) or Built-in (presets.py)
    if key.startswith('custom_'):
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        if job and job.configuration:
            config = json.loads(job.configuration)
            # Reconstruct params from config
            tmdb_params = {'sort_by': config.get('sort_by', 'popularity.desc')}
            if float(config.get('min_rating', 0)) > 0: tmdb_params['vote_average.gte'] = float(config.get('min_rating'))
            if config.get('with_genres'): tmdb_params['with_genres'] = config['with_genres']
            if config.get('with_keywords'): tmdb_params['with_keywords'] = str(config['with_keywords']).replace(',', '|')
            
            # Handle Dates
            date_key = 'primary_release_date' if config.get('media_type', 'movie') == 'movie' else 'first_air_date'
            if config.get('year_start') and config['year_start'] != 'Imported': 
                tmdb_params[f'{date_key}.gte'] = f"{config['year_start']}-01-01"
            if config.get('year_end') and config['year_end'] != 'List': 
                tmdb_params[f'{date_key}.lte'] = f"{config['year_end']}-12-31"
            
            preset = {'media_type': config.get('media_type', 'movie'), 'tmdb_params': tmdb_params}
    else:
        # Built-in Preset
        preset = PLAYLIST_PRESETS.get(key)

    if not preset:
        return jsonify({'status': 'error', 'message': 'Preset not found or is a static import.'})

    # 2. Fetch from TMDB
    try:
        media_type = preset.get('media_type', 'movie')
        params = preset.get('tmdb_params', {}).copy()
        params['api_key'] = s.tmdb_key
        
        # Determine Library Name for "Owned" check
        plex = PlexServer(s.plex_url, s.plex_token)
        lib_name = 'TV Shows' if media_type == 'tv' else 'Movies'
        try:
            library_titles = {normalize_title(x.title) for x in plex.library.section(lib_name).all()}
        except:
            library_titles = set()
        
        url = f"https://api.themoviedb.org/3/discover/{media_type}"
        resp = requests.get(url, params=params, timeout=5).json()
        results = resp.get('results', [])[:12] # Top 12 items
        
        preview_items = []
        for r in results:
            title = r.get('name') if media_type == 'tv' else r.get('title')
            date = r.get('first_air_date') if media_type == 'tv' else r.get('release_date')
            preview_items.append({
                'title': title, 
                'year': (date or '')[:4],
                'poster_path': r.get('poster_path'),
                'owned': normalize_title(title) in library_titles,
                'tmdb_id': r['id'],
                'media_type': media_type
            })
            
        return jsonify({'status': 'success', 'items': preview_items})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# --- METADATA & UTILS ---
@app.route('/get_metadata/<media_type>/<int:tmdb_id>')
@login_required
def get_metadata(media_type, tmdb_id):
    s = current_user.settings
    try:
        cast = [c['name'] for c in requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits?api_key={s.tmdb_key}", timeout=5).json().get('cast', [])[:3]]
        raw_reg = s.tmdb_region or 'US'
        reg = raw_reg.split(',')[0].strip().upper()
        prov = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={s.tmdb_key}", timeout=5).json().get('results', {}).get(reg, {}).get('flatrate', [])
        return jsonify({'cast': cast, 'providers': [{'name': p['provider_name'], 'logo': p['logo_path']} for p in prov]})
    except: return jsonify({'cast': [], 'providers': []})

@app.route('/get_trailer/<media_type>/<int:tmdb_id>')
@login_required
def get_trailer(media_type, tmdb_id):
    s = current_user.settings
    try:
        url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/videos?api_key={s.tmdb_key}&language=en-US"
        results = requests.get(url, timeout=5).json().get('results', [])
        for vid in results:
            if vid['site'] == 'YouTube' and vid['type'] == 'Trailer':
                return jsonify({'status': 'success', 'key': vid['key']})
        for vid in results:
            if vid['site'] == 'YouTube':
                return jsonify({'status': 'success', 'key': vid['key']})
        return jsonify({'status': 'error', 'message': 'No trailer found'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/tmdb_search_proxy')
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
    return {'results': [{'title': i.get('name') if request.args.get('type') == 'tv' else i.get('title'), 'year': (i.get('first_air_date') or i.get('release_date') or '')[:4], 'poster': i.get('poster_path')} for i in res]}

@app.route('/request_media', methods=['POST'])
@login_required
def request_media():
    s = current_user.settings
    data = request.json
    try:
        uid_resp = requests.get(f"{s.overseerr_url}/api/v1/auth/me", headers={'X-Api-Key': s.overseerr_api_key}, timeout=5)
        uid = uid_resp.json()['id']
        items = data.get('items', [data])
        success_count = 0
        for item in items:
            if send_overseerr_request(s, item['media_type'], item['tmdb_id'], uid): success_count += 1
        return jsonify({'status': 'success', 'count': success_count})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)})

# --- FIX: Prevent Duplicate Blocks ---
@app.route('/block_movie', methods=['POST'])
@login_required
def block_movie():
    title = request.json['title']
    media_type = request.json.get('media_type', 'movie')
    
    # Check if exists before adding
    exists = Blocklist.query.filter_by(user_id=current_user.id, title=title, media_type=media_type).first()
    if not exists:
        db.session.add(Blocklist(user_id=current_user.id, title=title, media_type=media_type))
        db.session.commit()
        
    return {'status': 'success'}

@app.route('/unblock_movie', methods=['POST'])
@login_required
def unblock_movie():
    Blocklist.query.filter_by(id=request.json['id']).delete()
    db.session.commit()
    return {'status': 'success'}

@app.route('/api/tautulli_data')
@login_required
def tautulli_data():
    s = current_user.settings
    if not s or not s.tautulli_url or not s.tautulli_api_key: return jsonify({"error": "Tautulli not configured"})
    days = request.args.get('days', '30')
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

@app.route('/preview_custom_collection', methods=['POST'])
@login_required
def preview_custom_collection():
    data = request.json
    s = current_user.settings
    media_type = data.get('media_type', 'movie')
    params = {'api_key': s.tmdb_key, 'sort_by': data.get('sort_by', 'popularity.desc'), 'with_genres': data.get('with_genres', ''), 'with_keywords': str(data.get('with_keywords', '')).replace(',', '|')}
    if float(data.get('min_rating', 0)) > 0: params['vote_average.gte'] = data.get('min_rating')
    date_key = 'primary_release_date' if media_type == 'movie' else 'first_air_date'
    if data.get('year_start'): params[f'{date_key}.gte'] = f"{data['year_start']}-01-01"
    if data.get('year_end'): params[f'{date_key}.lte'] = f"{data['year_end']}-12-31"
    try:
        if not any([data.get('with_genres'), data.get('with_keywords'), data.get('year_start'), data.get('year_end')]):
            return jsonify({'status': 'success', 'items': [], 'message': 'Add filters to preview.'})
        plex = PlexServer(s.plex_url, s.plex_token)
        lib_name = 'TV Shows' if media_type == 'tv' else 'Movies'
        library_titles = {normalize_title(x.title) for x in plex.library.section(lib_name).all()}
        url = f"https://api.themoviedb.org/3/discover/{media_type}"
        resp = requests.get(url, params=params, timeout=5).json()
        results = resp.get('results', [])[:10] 
        preview_items = []
        for r in results:
            title = r.get('name') if media_type == 'tv' else r.get('title')
            date = r.get('first_air_date') if media_type == 'tv' else r.get('release_date')
            preview_items.append({'title': title, 'text': f"{title} ({(date or '')[:4]})", 'owned': normalize_title(title) in library_titles, 'tmdb_id': r['id'], 'media_type': media_type})
        return jsonify({'status': 'success', 'items': preview_items})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)})

@app.route('/save_custom_collection', methods=['POST'])
@login_required
def save_custom_collection():
    try:
        timestamp = int(time.time())
        preset_key = f"custom_{timestamp}"
        new_job = CollectionSchedule(preset_key=preset_key, frequency='manual', configuration=json.dumps(request.json))
        db.session.add(new_job)
        db.session.commit()
        return jsonify({'status': 'success', 'preset_key': preset_key})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/delete_custom_collection/<key>', methods=['POST'])
@login_required
def delete_custom_collection(key):
    if not key.startswith('custom_'): return jsonify({'status': 'error', 'message': 'Cannot delete standard presets.'})
    job = CollectionSchedule.query.filter_by(preset_key=key).first()
    if job:
        try:
            config = json.loads(job.configuration)
            s = current_user.settings
            p = PlexServer(s.plex_url, s.plex_token)
            lib = 'TV Shows' if config.get('media_type', 'movie') == 'tv' else 'Movies'
            [c.delete() for c in p.library.section(lib).collections() if c.title == config.get('title')]
        except: pass
        db.session.delete(job)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Deleted.'})
    return jsonify({'status': 'error', 'message': 'Not found.'})

@app.route('/save_schedule', methods=['POST'])
@login_required
def save_schedule():
    key = request.json.get('key')
    freq = request.json.get('frequency')
    job = CollectionSchedule.query.filter_by(preset_key=key).first()
    if not job: job = CollectionSchedule(preset_key=key)
    db.session.add(job)
    job.frequency = freq
    if freq != 'manual': job.last_run = None 
    db.session.commit()
    return {'status': 'success'}

@app.route('/create_collection/<key>', methods=['POST'])
@login_required
def create_collection(key):
    success, msg = run_collection_logic(key, current_user.settings)
    if success:
        job = CollectionSchedule.query.filter_by(preset_key=key).first()
        if not job: job = CollectionSchedule(preset_key=key)
        db.session.add(job)
        job.last_run = datetime.datetime.now()
        db.session.commit()
        return jsonify({'status': 'success', 'message': msg})
    else: return jsonify({'status': 'error', 'message': msg})

# --- BACKUP ROUTES ---

@app.route('/api/backups', methods=['GET'])
@login_required
def get_backups_api():
    return jsonify(list_backups())

@app.route('/api/backup/create', methods=['POST'])
@login_required
def trigger_backup():
    success, msg = create_backup()
    if success:
        # Run prune after creation to ensure we stay within limits
        s = current_user.settings
        if s.backup_retention:
            prune_backups(s.backup_retention)
        return jsonify({'status': 'success', 'filename': msg})
    return jsonify({'status': 'error', 'message': msg})

@app.route('/api/backup/restore/<filename>', methods=['POST'])
@login_required
def run_restore(filename):
    # Security check: prevent directory traversal
    if '..' in filename or '/' in filename:
        return jsonify({'status': 'error', 'message': 'Invalid filename'})
        
    success, msg = restore_backup(filename)
    if success:
        return jsonify({'status': 'success', 'message': 'Database restored. Please restart the container to ensure changes take effect.'})
    return jsonify({'status': 'error', 'message': msg})

@app.route('/api/backup/delete/<filename>', methods=['DELETE'])
@login_required
def delete_backup_api(filename):
    if '..' in filename or '/' in filename: return jsonify({'status': 'error'})
    path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Not found'})

@app.route('/api/backup/download/<filename>')
@login_required
def download_backup(filename):
    if '..' in filename or '/' in filename: return "Invalid filename", 400
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

# --- ALIAS SYNC API (UPDATED) ---
@app.route('/api/sync_aliases', methods=['POST'])
@login_required
def manual_alias_sync():
    success, msg = sync_remote_aliases()
    status = 'success' if success else 'error'
    
    # COUNT THE TOTAL IN DB
    try:
        total = TmdbAlias.query.count()
    except: 
        total = 0
        
    return jsonify({'status': status, 'message': msg, 'count': total})