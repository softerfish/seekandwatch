import time
import os
import re
import requests
import random
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from plexapi.server import PlexServer
from models import db, User, Settings, Blocklist

# ==================================================================================
# 1. APPLICATION CONFIGURATION
# ==================================================================================

# --- UPDATE CHECK CONFIGURATION ---
VERSION = "1.0.0"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/softerfish/seekandwatch/main/app.py"
# ----------------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = 'debug_secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////config/site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ==================================================================================
# 2. CONSTANTS & GENRE MAPPING
# ==================================================================================

TMDB_GENRES = {
    'movie': [{'id': 28, 'name': 'Action'}, {'id': 12, 'name': 'Adventure'}, {'id': 16, 'name': 'Animation'}, {'id': 35, 'name': 'Comedy'}, {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'}, {'id': 18, 'name': 'Drama'}, {'id': 10751, 'name': 'Family'}, {'id': 14, 'name': 'Fantasy'}, {'id': 36, 'name': 'History'}, {'id': 27, 'name': 'Horror'}, {'id': 10402, 'name': 'Music'}, {'id': 9648, 'name': 'Mystery'}, {'id': 10749, 'name': 'Romance'}, {'id': 878, 'name': 'Science Fiction'}, {'id': 10770, 'name': 'TV Movie'}, {'id': 53, 'name': 'Thriller'}, {'id': 10752, 'name': 'War'}, {'id': 37, 'name': 'Western'}],
    'tv': [{'id': 10759, 'name': 'Action & Adventure'}, {'id': 16, 'name': 'Animation'}, {'id': 35, 'name': 'Comedy'}, {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'}, {'id': 18, 'name': 'Drama'}, {'id': 10751, 'name': 'Family'}, {'id': 10762, 'name': 'Kids'}, {'id': 9648, 'name': 'Mystery'}, {'id': 10763, 'name': 'News'}, {'id': 10764, 'name': 'Reality'}, {'id': 10765, 'name': 'Sci-Fi & Fantasy'}, {'id': 10766, 'name': 'Soap'}, {'id': 10767, 'name': 'Talk'}, {'id': 10768, 'name': 'War & Politics'}, {'id': 37, 'name': 'Western'}]
}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def normalize_title(title):
    if not title: return ""
    return re.sub(r'[^a-z0-9]', '', str(title).lower())

def send_overseerr_request(settings, media_type, tmdb_id, user_id):
    headers = {'X-Api-Key': settings.overseerr_api_key, 'Content-Type': 'application/json'}
    payload = {"mediaType": media_type, "mediaId": int(tmdb_id), "userId": user_id}
    
    if media_type == 'tv':
        try:
            tmdb_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={settings.tmdb_key}"
            data = requests.get(tmdb_url).json()
            payload["seasons"] = [i for i in range(1, data.get('number_of_seasons', 1) + 1)]
        except: payload["seasons"] = [1]
            
    try:
        resp = requests.post(f"{settings.overseerr_url}/api/v1/request", json=payload, headers=headers)
        return resp.status_code in [200, 201, 409]
    except: return False

def check_for_updates():
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=2)
        if response.status_code == 200:
            # Look for VERSION = "x.x.x" in the raw text
            match = re.search(r'VERSION\s*=\s*"([\d\.]+)"', response.text)
            if match:
                remote_version = match.group(1)
                if remote_version != VERSION:
                    return remote_version
    except:
        pass 
    return None

# ==================================================================================
# 3. ROUTES
# ==================================================================================

@app.route('/')
@login_required
def dashboard():
    recent_media = []
    if current_user.settings and current_user.settings.plex_url and current_user.settings.plex_token:
        try:
            plex = PlexServer(current_user.settings.plex_url, current_user.settings.plex_token)
            for item in plex.library.recentlyAdded()[:10]:
                thumb = f"{current_user.settings.plex_url}{item.thumb}?X-Plex-Token={current_user.settings.plex_token}" if item.thumb else ""
                recent_media.append({'title': item.title, 'type': item.type, 'year': item.year, 'thumb': thumb})
        except Exception as e:
            print(f"Dashboard Plex Error: {e}", flush=True)

    # Check for update
    new_version = check_for_updates()

    return render_template('dashboard.html', recent_media=recent_media, new_version=new_version)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_settings = Settings.query.filter_by(user_id=current_user.id).first() or Settings(user_id=current_user.id)
    if not user_settings.id:
        db.session.add(user_settings)
        db.session.commit()

    if request.method == 'POST':
        user_settings.plex_url = (request.form.get('plex_url') or '').rstrip('/')
        user_settings.plex_token = request.form.get('plex_token')
        user_settings.tmdb_key = request.form.get('tmdb_key')
        user_settings.tmdb_region = request.form.get('tmdb_region', 'US').upper()
        user_settings.overseerr_url = (request.form.get('overseerr_url') or '').rstrip('/')
        user_settings.overseerr_api_key = request.form.get('overseerr_api_key')
        user_settings.tautulli_url = (request.form.get('tautulli_url') or '').rstrip('/')
        user_settings.tautulli_api_key = request.form.get('tautulli_api_key')
        user_settings.ignored_users = ",".join(request.form.getlist('ignored_plex_users'))
        db.session.commit()
        flash('Settings Updated!', 'success')
        return redirect(url_for('dashboard'))

    plex_users = []
    if user_settings.plex_url and user_settings.plex_token:
        try:
            p = PlexServer(user_settings.plex_url, user_settings.plex_token)
            # Fetch users safely
            account = p.myPlexAccount()
            plex_users = sorted([u.title for u in account.users()] + ([account.username] if account.username else []))
        except: pass

    current_ignored = (user_settings.ignored_users or "").split(",")
    return render_template('settings.html', settings=user_settings, plex_users=plex_users, current_ignored=current_ignored)

@app.route('/stats')
@login_required
def stats_page():
    if not current_user.settings:
        db.session.add(Settings(user_id=current_user.id))
        db.session.commit()
        return redirect(url_for('stats_page'))
    s = current_user.settings
    has_tautulli = bool(s.tautulli_url and s.tautulli_api_key)
    return render_template('stats.html', has_tautulli=has_tautulli)

@app.route('/api/tautulli_data')
@login_required
def tautulli_data():
    s = current_user.settings
    if not s or not s.tautulli_url or not s.tautulli_api_key:
        return jsonify({"error": "Tautulli not configured"})
    days = request.args.get('days', '30')
    stat_type = request.args.get('type', '0')
    try:
        url = f"{s.tautulli_url}/api/v2?apikey={s.tautulli_api_key}&cmd=get_home_stats&time_range={days}&stats_type={stat_type}"
        resp = requests.get(url, timeout=10).json()
        if resp.get('response', {}).get('result') == 'success':
            return jsonify(resp['response']['data'])
        return jsonify({"error": f"Tautulli says: {resp.get('response', {}).get('message', 'Unknown Error')}"})
    except Exception as e:
        return jsonify({"error": "Connection Failed. Check URL/Logs."})

@app.route('/review_history', methods=['POST'])
@login_required
def review_history():
    s = current_user.settings
    if not s or not s.plex_url: 
        flash("Please configure Plex settings first.", "error")
        return redirect(url_for('settings'))
    
    media_type = request.form.get('media_type', 'movie')
    manual = request.form.get('manual_query')
    
    # 1. Safe Integer Parsing
    try:
        raw_limit = request.form.get('history_limit')
        history_limit = int(raw_limit) if raw_limit else 20
    except ValueError:
        history_limit = 20

    review_list = []
    providers = []
    
    # TMDB Provider Logic
    try:
        reg = s.tmdb_region or 'US'
        p_url = f"https://api.themoviedb.org/3/watch/providers/{media_type}?api_key={s.tmdb_key}&watch_region={reg}"
        p_data = requests.get(p_url).json().get('results', [])
        providers = sorted(p_data, key=lambda x: x.get('display_priority', 999))[:20]
    except: pass

    if manual:
        ep = 'search/tv' if media_type == 'tv' else 'search/movie'
        try:
            res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={manual}&api_key={s.tmdb_key}").json().get('results', [])[:5]
            for i in res:
                d = i.get('first_air_date') if media_type == 'tv' else i.get('release_date')
                review_list.append({'title': i.get('name') if media_type == 'tv' else i.get('title'), 'year': (d or '')[:4], 'poster_path': i.get('poster_path'), 'id': i['id']})
        except Exception as e:
            flash(f"Error searching TMDB: {e}", "error")
    else:
        try:
            plex = PlexServer(s.plex_url, s.plex_token)
            h = plex.history(maxresults=500)
            seen = set()
            ignored = (s.ignored_users or "").split(",")
            
            for x in h:
                if len(review_list) >= history_limit: break
                
                # --- FIX START: ROBUST USER CHECKING ---
                user_name = None
                try:
                    if hasattr(x, 'user') and x.user:
                         user_name = getattr(x.user, 'title', None) or getattr(x.user, 'username', None) or str(x.user)
                    elif hasattr(x, 'userName'):
                         user_name = x.userName
                except Exception:
                    pass # If we can't identify the user, we just ignore the filter and include the item
                
                if user_name and ignored and any(ign.strip() == user_name for ign in ignored if ign.strip()):
                    continue
                # --- FIX END ---
                
                # Media Type Filter
                target_type = 'episode' if media_type == 'tv' else 'movie'
                if x.type != target_type: continue
                
                t = x.grandparentTitle if media_type == 'tv' else x.title
                if t in seen: continue
                seen.add(t)
                
                # Fetch Poster
                poster_path = None
                try:
                    q_type = 'tv' if media_type == 'tv' else 'movie'
                    tmdb_res = requests.get(f"https://api.themoviedb.org/3/search/{q_type}?query={t}&api_key={s.tmdb_key}").json()
                    if tmdb_res.get('results'):
                        poster_path = tmdb_res['results'][0].get('poster_path')
                except: pass

                review_list.append({'title': t, 'year': getattr(x, 'year', ''), 'poster_path': poster_path})
            
            if not review_list:
                flash("No history found matching your criteria. Try increasing the history limit or watching more content!", "error")
                
        except Exception as e:
            print(f"Plex Error: {e}")
            flash(f"Could not connect to Plex: {str(e)}", "error")
    
    return render_template('review.html', movies=review_list, media_type=media_type, genres=TMDB_GENRES[media_type], providers=providers)

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    session['seed_titles'] = request.form.getlist('selected_movies')
    session['media_type'] = request.form.get('media_type')
    session['genre_filter'] = request.form.get('genre_filter')
    session['min_rating'] = float(request.form.get('min_rating', 0))
    session['provider_filter'] = request.form.getlist('provider_filter')
    
    if request.form.get('lucky_mode') == 'true': return handle_lucky_mode(current_user.settings)
    return render_template('results.html')

def handle_lucky_mode(s):
    seeds = session.get('seed_titles', [])[:3]
    m_type = session.get('media_type')
    final = []
    for t in seeds:
        try:
            q = requests.get(f"https://api.themoviedb.org/3/search/{'tv' if m_type=='tv' else 'movie'}?query={t}&api_key={s.tmdb_key}").json()['results'][0]['id']
            recs = requests.get(f"https://api.themoviedb.org/3/{'tv' if m_type=='tv' else 'movie'}/{q}/recommendations?api_key={s.tmdb_key}").json()['results']
            for r in recs:
                if r.get('vote_average', 0) >= session['min_rating']: final.append(r)
        except: continue
    
    if final:
        w = random.choice(final)
        try:
            uid = requests.get(f"{s.overseerr_url}/api/v1/auth/me", headers={'X-Api-Key': s.overseerr_api_key}).json()['id']
            send_overseerr_request(s, m_type, w['id'], uid)
            flash(f"🍀 Lucky! Requested: {w.get('title') or w.get('name')}", 'success')
        except: flash("Lucky mode failed (Overseerr error)", 'error')
    else: flash("No lucky match found", 'error')
    return redirect(url_for('dashboard'))

@app.route('/load_more_recs')
@login_required
def load_more_recs():
    s = current_user.settings
    page = int(request.args.get('page', 1))
    seeds = session.get('seed_titles', [])
    m_type = session.get('media_type', 'movie')
    provider_filter = session.get('provider_filter', [])
    recs = {}
    
    try:
        p = PlexServer(s.plex_url, s.plex_token)
        lib_name = 'TV Shows' if m_type == 'tv' else 'Movies'
        lib = {normalize_title(x.title) for x in p.library.section(lib_name).all()}
    except: lib = set()

    if provider_filter:
        try:
            g_str = session.get('genre_filter') or ""
            p_str = "|".join(provider_filter)
            discover_url = f"https://api.themoviedb.org/3/discover/{'tv' if m_type=='tv' else 'movie'}?api_key={s.tmdb_key}&with_watch_providers={p_str}&watch_region={s.tmdb_region}&with_genres={g_str}&sort_by=popularity.desc&page={page}&vote_average.gte={session.get('min_rating', 0)}"
            res = requests.get(discover_url).json().get('results', [])
            for r in res:
                title = r.get('name') if m_type == 'tv' else r.get('title')
                if normalize_title(title) not in lib:
                     date = r.get('first_air_date') if m_type == 'tv' else r.get('release_date')
                     recs[r['id']] = {'title': title, 'overview': r['overview'], 'poster_path': r['poster_path'], 'tmdb_id': r['id'], 'media_type': m_type, 'rating': r.get('vote_average'), 'date': (date or '')[:4]}
        except: pass
    else:
        for t in seeds:
            try:
                tid = requests.get(f"https://api.themoviedb.org/3/search/{'tv' if m_type=='tv' else 'movie'}?query={t}&api_key={s.tmdb_key}").json()['results'][0]['id']
                res = requests.get(f"https://api.themoviedb.org/3/{'tv' if m_type=='tv' else 'movie'}/{tid}/recommendations?api_key={s.tmdb_key}&page={page}").json().get('results', [])
                for r in res:
                    if session.get('genre_filter') and int(session['genre_filter']) not in r['genre_ids']: continue
                    if r.get('vote_average', 0) < session.get('min_rating', 0): continue
                    title = r.get('name') if m_type == 'tv' else r.get('title')
                    if normalize_title(title) not in lib and r['id'] not in recs:
                        date = r.get('first_air_date') if m_type == 'tv' else r.get('release_date')
                        recs[r['id']] = {'title': title, 'overview': r['overview'], 'poster_path': r['poster_path'], 'tmdb_id': r['id'], 'media_type': m_type, 'rating': r.get('vote_average'), 'date': (date or '')[:4]}
            except: continue

    return jsonify(list(recs.values()))

@app.route('/get_metadata/<media_type>/<int:tmdb_id>')
@login_required
def get_metadata(media_type, tmdb_id):
    s = current_user.settings
    try:
        cast = [c['name'] for c in requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/credits?api_key={s.tmdb_key}").json().get('cast', [])[:3]]
        prov = requests.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={s.tmdb_key}").json().get('results', {}).get((s.tmdb_region or 'US').upper(), {}).get('flatrate', [])
        return jsonify({'cast': cast, 'providers': [{'name': p['provider_name'], 'logo': p['logo_path']} for p in prov]})
    except: return jsonify({'cast': [], 'providers': []})

@app.route('/manage_blocklist')
@login_required
def manage_blocklist():
    return render_template('blocklist.html', blocks=Blocklist.query.filter_by(user_id=current_user.id).all())

@app.route('/block_movie', methods=['POST'])
@login_required
def block_movie():
    db.session.add(Blocklist(user_id=current_user.id, title=request.json['title'], media_type=request.json.get('media_type', 'movie')))
    db.session.commit()
    return {'status': 'success'}

@app.route('/unblock_movie', methods=['POST'])
@login_required
def unblock_movie():
    Blocklist.query.filter_by(id=request.json['id']).delete()
    db.session.commit()
    return {'status': 'success'}

@app.route('/tmdb_search_proxy')
@login_required
def tmdb_search_proxy():
    s = current_user.settings
    q = request.args.get('query')
    if not q: return {'results': []}
    ep = 'search/tv' if request.args.get('type') == 'tv' else 'search/movie'
    res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={q}&api_key={s.tmdb_key}").json().get('results', [])[:5]
    return {'results': [{'title': i.get('name') if request.args.get('type') == 'tv' else i.get('title'), 'year': (i.get('first_air_date') or i.get('release_date') or '')[:4], 'poster': i.get('poster_path')} for i in res]}

@app.route('/request_media', methods=['POST'])
@login_required
def request_media():
    s = current_user.settings
    data = request.json
    try:
        uid = requests.get(f"{s.overseerr_url}/api/v1/auth/me", headers={'X-Api-Key': s.overseerr_api_key}).json()['id']
        items = data.get('items', [{'tmdb_id': data.get('tmdb_id'), 'media_type': data.get('media_type')}])
        count = sum(1 for i in items if send_overseerr_request(s, i['media_type'], i['tmdb_id'], uid))
        return {'status': 'success', 'count': count}
    except Exception as e: return {'status': 'error', 'message': str(e)}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username')).first()
        if u and check_password_hash(u.password_hash, request.form.get('password')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not User.query.filter_by(username=request.form.get('username')).first():
            db.session.add(User(username=request.form.get('username'), password_hash=generate_password_hash(request.form.get('password'))))
            db.session.commit()
            return redirect(url_for('login'))
    return render_template('login.html', is_register=True)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)