import time
import os
import re
import requests
import random
import json
import datetime
import threading
import sqlalchemy
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_apscheduler import APScheduler
from plexapi.server import PlexServer
from models import db, User, Settings, Blocklist, CollectionSchedule, SystemLog, TmdbAlias
from presets import PLAYLIST_PRESETS
from utils import normalize_title, is_duplicate, check_for_updates, fetch_omdb_ratings, send_overseerr_request, handle_lucky_mode, run_collection_logic, create_backup, prune_backups, refresh_plex_cache, CACHE_FILE, is_system_locked, get_lock_status, write_log, sync_remote_aliases

# ==================================================================================
# 1. APPLICATION CONFIGURATION
# ==================================================================================

VERSION = "1.0.0"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/softerfish/seekandwatch/main/app.py"

import time
import os
import re
import requests
import random
import json
import datetime
import threading
import socket
import hashlib
import sqlalchemy
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_apscheduler import APScheduler
from plexapi.server import PlexServer
from models import db, User, Settings, Blocklist, CollectionSchedule, SystemLog, TmdbAlias
from presets import PLAYLIST_PRESETS
from utils import normalize_title, is_duplicate, check_for_updates, fetch_omdb_ratings, send_overseerr_request, handle_lucky_mode, run_collection_logic, create_backup, prune_backups, refresh_plex_cache, CACHE_FILE, is_system_locked, get_lock_status, write_log, sync_remote_aliases

# ==================================================================================
# 1. APPLICATION CONFIGURATION
# ==================================================================================

VERSION = "1.0.1"
GITHUB_RAW_URL = "https://gitlab.com/catchthis/seekandwatch/-/raw/main/app.py"

def get_stable_secret_key():
    """
    Generates a secure key based on the container's unique identity.
    This guarantees all workers match without needing to write files.
    """
    # 1. Allow override via Env Var (just in case)
    if os.environ.get('SECRET_KEY'):
        return os.environ.get('SECRET_KEY')
    
    # 2. Generate a stable key from the container's hostname
    # In Docker, hostname is the container ID (e.g., 'a1b2c3d4e5f6')
    # This is identical for all workers and persists until container destruction.
    try:
        container_id = socket.gethostname()
        secret_src = f"{container_id}-seekandwatch-secure-salt"
        return hashlib.sha256(secret_src.encode()).hexdigest()
    except Exception:
        # Absolute fallback if system calls fail
        return 'fallback-static-key-ensure-login-works'

class Config:
    SECRET_KEY = get_stable_secret_key()
    SQLALCHEMY_DATABASE_URI = 'sqlite:////config/site.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SCHEDULER_API_ENABLED = True
    # Ensure cookies work over HTTP (since most users use local IP)
    SESSION_COOKIE_SECURE = False 
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

app = Flask(__name__)
app.config.from_object(Config())

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# --- CONSTANTS ---
TMDB_GENRES = {
    'movie': [{'id': 28, 'name': 'Action'}, {'id': 12, 'name': 'Adventure'}, {'id': 16, 'name': 'Animation'}, {'id': 35, 'name': 'Comedy'}, {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'}, {'id': 18, 'name': 'Drama'}, {'id': 10751, 'name': 'Family'}, {'id': 14, 'name': 'Fantasy'}, {'id': 36, 'name': 'History'}, {'id': 27, 'name': 'Horror'}, {'id': 10402, 'name': 'Music'}, {'id': 9648, 'name': 'Mystery'}, {'id': 10749, 'name': 'Romance'}, {'id': 878, 'name': 'Science Fiction'}, {'id': 10770, 'name': 'TV Movie'}, {'id': 53, 'name': 'Thriller'}, {'id': 10752, 'name': 'War'}, {'id': 37, 'name': 'Western'}],
    'tv': [{'id': 10759, 'name': 'Action & Adventure'}, {'id': 16, 'name': 'Animation'}, {'id': 35, 'name': 'Comedy'}, {'id': 80, 'name': 'Crime'}, {'id': 99, 'name': 'Documentary'}, {'id': 18, 'name': 'Drama'}, {'id': 10751, 'name': 'Family'}, {'id': 10762, 'name': 'Kids'}, {'id': 9648, 'name': 'Mystery'}, {'id': 10763, 'name': 'News'}, {'id': 10764, 'name': 'Reality'}, {'id': 10765, 'name': 'Sci-Fi & Fantasy'}, {'id': 10766, 'name': 'Soap'}, {'id': 10767, 'name': 'Talk'}, {'id': 10768, 'name': 'War & Politics'}, {'id': 37, 'name': 'Western'}]
}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_version():
    return dict(app_version=VERSION)

@scheduler.task('interval', id='scheduled_updates', hours=1)
def scheduled_update_checker():
    with app.app_context():
        user_settings = Settings.query.first() 
        if not user_settings or not user_settings.plex_url: return
        for job in CollectionSchedule.query.all():
            if job.frequency == 'manual': continue
            hours_threshold = 24 if job.frequency == 'daily' else 168
            last = job.last_run or datetime.datetime.min
            if (datetime.datetime.now() - last).total_seconds() > (hours_threshold * 3600):
                run_collection_logic(job.preset_key, user_settings)
                job.last_run = datetime.datetime.now()
                db.session.commit()

# --- BACKUP SCHEDULER ---
@scheduler.task('interval', id='scheduled_backups', hours=24)
def scheduled_backup_task():
    with app.app_context():
        user_settings = Settings.query.first()
        if not user_settings: return
        from utils import BACKUP_DIR
        import os
        interval_days = user_settings.backup_interval or 2
        retention_days = user_settings.backup_retention or 7
        should_backup = False
        if not os.path.exists(BACKUP_DIR) or not os.listdir(BACKUP_DIR):
            should_backup = True
        else:
            files = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.endswith('.zip')]
            if files:
                newest = max(files, key=os.path.getmtime)
                days_since = (time.time() - os.path.getmtime(newest)) / 86400
                if days_since >= interval_days: should_backup = True
            else: should_backup = True
        if should_backup:
            create_backup()
            prune_backups(retention_days)

# --- ALIAS SYNC SCHEDULER (NEW) ---
@scheduler.task('interval', id='scheduled_alias_update', hours=24)
def scheduled_alias_update():
    with app.app_context():
        sync_remote_aliases()

# --- PLEX CACHE SCHEDULER ---
@scheduler.task('interval', id='refresh_cache_job', minutes=30)
def scheduled_cache_check():
    with app.app_context():
        settings = Settings.query.first()
        if not settings or not settings.plex_url: return
        interval_hours = settings.cache_interval or 24
        
        # Check if already running via file lock
        if is_system_locked(): return

        should_run = False
        if not os.path.exists(CACHE_FILE): should_run = True
        else:
            try:
                with open(CACHE_FILE, 'r') as f:
                    data = json.load(f)
                    if (time.time() - data.get('timestamp', 0)) > (interval_hours * 3600):
                        should_run = True
            except: should_run = True
        if should_run:
            refresh_plex_cache(settings)

# ==================================================================================
# CACHE STATUS ENDPOINTS
# ==================================================================================

def run_threaded_cache(app_obj, user_id):
    """Refreshes cache inside an app context so logging works."""
    with app_obj.app_context():
        user = User.query.get(user_id)
        if user and user.settings:
            refresh_plex_cache(user.settings)

@app.route('/save_cache_settings', methods=['POST'])
@login_required
def save_cache_settings():
    try:
        data = request.get_json()
        current_user.settings.cache_interval = int(data.get('interval', 24))
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Cache interval saved!'})
    except Exception as e: return jsonify({'status': 'error', 'message': str(e)})

@app.route('/force_cache_refresh', methods=['POST'])
@login_required
def force_cache_refresh_route():
    if is_system_locked():
        return jsonify({'status': 'error', 'message': 'Scan already in progress.'})
    
    user_id = current_user.id
    thread = threading.Thread(target=run_threaded_cache, args=(app, user_id))
    thread.start()
    
    return jsonify({'status': 'success', 'message': 'Background scan started. Controls locked until complete.'})

@app.route('/get_cache_status')
@login_required
def get_cache_status_route():
    locked = is_system_locked()
    progress = get_lock_status() if locked else "Idle"
    return jsonify({'running': locked, 'progress': progress})

# ==================================================================================
# ALIAS & LOGGING ENDPOINTS
# ==================================================================================

# NOTE: manual_alias_sync is now in api.py to prevent duplicates

@app.route('/logs')
@login_required
def logs():
    # Fetch logs, newest first
    log_entries = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(200).all()
    return render_template('logs.html', logs=log_entries, settings=current_user.settings)

@app.route('/toggle_logging', methods=['POST'])
@login_required
def toggle_logging():
    try:
        data = request.get_json()
        current_user.settings.logging_enabled = data.get('enabled', True)
        db.session.commit()
        state = "Enabled" if current_user.settings.logging_enabled else "Disabled"
        write_log("INFO", "System", f"Logging {state} by user.")
        return jsonify({'status': 'success', 'message': f'Logging {state}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/clear_logs', methods=['POST'])
@login_required
def clear_logs():
    try:
        db.session.query(SystemLog).delete()
        db.session.commit()
        write_log("INFO", "System", "Logs cleared by user.")
        return jsonify({'status': 'success', 'message': 'Logs cleared.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ==================================================================================
# 3. ROUTES
# ==================================================================================

@app.route('/')
@login_required
def dashboard():
    recent_media = []
    if current_user.settings and current_user.settings.plex_url and current_user.settings.plex_token:
        try:
            blocked_titles = {normalize_title(b.title) for b in Blocklist.query.filter_by(user_id=current_user.id).all()}
            plex = PlexServer(current_user.settings.plex_url, current_user.settings.plex_token)
            
            for item in plex.library.recentlyAdded()[:30]:
                if len(recent_media) >= 10: break
                thumb = f"{current_user.settings.plex_url}{item.thumb}?X-Plex-Token={current_user.settings.plex_token}" if item.thumb else ""
                
                year = None
                if getattr(item, 'originallyAvailableAt', None): year = item.originallyAvailableAt.year
                if not year and item.type in ['season', 'episode']:
                    try:
                        full_item = plex.fetchItem(item.ratingKey)
                        if getattr(full_item, 'originallyAvailableAt', None): year = full_item.originallyAvailableAt.year
                        elif getattr(full_item, 'year', None): year = full_item.year
                        elif getattr(full_item, 'parentYear', None): year = full_item.parentYear
                    except: pass
                if not year:
                    if getattr(item, 'parentYear', None): year = item.parentYear
                    elif getattr(item, 'grandparentYear', None): year = item.grandparentYear
                if not year and getattr(item, 'year', None): year = item.year
                if not year and getattr(item, 'addedAt', None): year = item.addedAt.year
                
                main_title, sub_title = item.title, None
                if item.type == 'season': main_title, sub_title = item.parentTitle, item.title
                elif item.type == 'episode': main_title, sub_title = item.grandparentTitle, item.title

                if normalize_title(main_title) in blocked_titles: continue
                recent_media.append({'title': main_title, 'sub_title': sub_title, 'type': item.type, 'year': str(year or ''), 'thumb': thumb})
        except: pass
    new_version = check_for_updates(VERSION, GITHUB_RAW_URL)
    has_omdb = bool(current_user.settings and current_user.settings.omdb_key)
    return render_template('dashboard.html', recent_media=recent_media, new_version=new_version, has_omdb=has_omdb)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username')).first()
        if u and check_password_hash(u.password_hash, request.form.get('password')):
            login_user(u)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user_settings = Settings.query.filter_by(user_id=current_user.id).first() or Settings(user_id=current_user.id)
    if not user_settings.id: db.session.add(user_settings); db.session.commit()

    if request.method == 'POST':
        try:
            user_settings.plex_url = (request.form.get('plex_url') or '').rstrip('/')
            user_settings.plex_token = request.form.get('plex_token')
            user_settings.tmdb_key = request.form.get('tmdb_key')
            user_settings.tmdb_region = request.form.get('tmdb_region', 'US').upper()
            user_settings.omdb_key = request.form.get('omdb_key')
            user_settings.overseerr_url = (request.form.get('overseerr_url') or '').rstrip('/')
            user_settings.overseerr_api_key = request.form.get('overseerr_api_key')
            user_settings.tautulli_url = (request.form.get('tautulli_url') or '').rstrip('/')
            user_settings.tautulli_api_key = request.form.get('tautulli_api_key')
            try:
                user_settings.backup_interval = int(request.form.get('backup_interval', 2))
                user_settings.backup_retention = int(request.form.get('backup_retention', 7))
                user_settings.max_log_size = int(request.form.get('max_log_size', 5))
            except: pass
            user_settings.ignored_users = ",".join(request.form.getlist('ignored_plex_users'))
            db.session.commit()
            return jsonify({'status': 'success', 'message': 'Configuration Saved Successfully!'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'status': 'error', 'message': f"Save Error: {str(e)}"})

    plex_users = []
    if user_settings.plex_url and user_settings.plex_token:
        try:
            p = PlexServer(user_settings.plex_url, user_settings.plex_token)
            account = p.myPlexAccount()
            plex_users = sorted([u.title for u in account.users()] + ([account.username] if account.username else []))
        except: pass
    current_ignored = (user_settings.ignored_users or "").split(",")
    
    # PASS COUNT TO TEMPLATE
    alias_count = TmdbAlias.query.count()
    return render_template('settings.html', settings=user_settings, plex_users=plex_users, current_ignored=current_ignored, alias_count=alias_count)

@app.route('/review_history', methods=['POST'])
@login_required
def review_history():
    s = current_user.settings
    media_type = request.form.get('media_type', 'movie')
    manual = request.form.get('manual_query')
    session['critic_filter'] = request.form.get('critic_filter')
    history_limit = int(request.form.get('history_limit', 20))
    review_list = []
    providers = []
    try:
        raw_reg = s.tmdb_region or 'US'
        regions = [r.strip().upper() for r in raw_reg.split(',')]
        all_providers = {}
        for reg in regions:
            if not reg: continue
            try:
                p_url = f"https://api.themoviedb.org/3/watch/providers/{media_type}?api_key={s.tmdb_key}&watch_region={reg}"
                p_data = requests.get(p_url).json().get('results', [])
                for p in p_data: all_providers[p['provider_id']] = p
            except: pass
        providers = sorted(all_providers.values(), key=lambda x: x.get('display_priority', 999))[:40] 
    except Exception as e: print(f"Provider Fetch Error: {e}")

    if manual:
        ep = 'search/tv' if media_type == 'tv' else 'search/movie'
        try:
            res = requests.get(f"https://api.themoviedb.org/3/{ep}?query={manual}&api_key={s.tmdb_key}").json().get('results', [])[:5]
            for i in res:
                d = i.get('first_air_date') if media_type == 'tv' else i.get('release_date')
                review_list.append({'title': i.get('name') if media_type == 'tv' else i.get('title'), 'year': (d or '')[:4], 'poster_path': i.get('poster_path'), 'id': i['id']})
        except Exception as e: flash(f"Error searching TMDB: {e}", "error")
    else:
        try:
            plex = PlexServer(s.plex_url, s.plex_token)
            h = plex.history(maxresults=500)
            seen = set()
            ignored = (s.ignored_users or "").split(",")
            for x in h:
                if len(review_list) >= history_limit: break
                user_name = None
                try:
                    if hasattr(x, 'user') and x.user: user_name = getattr(x.user, 'title', None) or getattr(x.user, 'username', None) or str(x.user)
                    elif hasattr(x, 'userName'): user_name = x.userName
                except Exception: pass 
                if user_name and ignored and any(ign.strip() == user_name for ign in ignored if ign.strip()): continue
                target_type = 'episode' if media_type == 'tv' else 'movie'
                if x.type != target_type: continue
                t = x.grandparentTitle if media_type == 'tv' else x.title
                if t in seen: continue
                seen.add(t)
                poster_path = None
                try:
                    q_type = 'tv' if media_type == 'tv' else 'movie'
                    tmdb_res = requests.get(f"https://api.themoviedb.org/3/search/{q_type}?query={t}&api_key={s.tmdb_key}").json()
                    if tmdb_res.get('results'): poster_path = tmdb_res['results'][0].get('poster_path')
                except: pass
                review_list.append({'title': t, 'year': getattr(x, 'year', ''), 'poster_path': poster_path})
            if not review_list: flash("No history found matching your criteria.", "error")
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
    use_critic_filter = request.form.get('critic_filter') == 'on'
    session['critic_threshold'] = int(request.form.get('critic_threshold', 70))
    if request.form.get('lucky_mode') == 'true': return handle_lucky_mode(current_user.settings)
    return render_template('results.html', use_critic_filter=use_critic_filter)

@app.route('/builder')
@login_required
def builder(): return render_template('builder.html', genres=TMDB_GENRES['movie'])

@app.route('/playlists')
@login_required
def playlists():
    schedules = {s.preset_key: s.frequency for s in CollectionSchedule.query.all()}
    custom_entries = CollectionSchedule.query.filter(CollectionSchedule.preset_key.like('custom_%')).all()
    custom_presets = {}
    for job in custom_entries:
        if job.configuration:
            config = json.loads(job.configuration)
            custom_presets[job.preset_key] = {'title': config['title'], 'icon': '🛠️', 'media_type': config['media_type'], 'description': f"Custom {config['media_type']} collection targeting {config.get('year_start', 'Any')} - {config.get('year_end', 'Any')}."}
    
    cache_age = "Never"
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                ts = data.get('timestamp', 0)
                dur = data.get('duration', 0)
                diff = int((time.time() - ts) / 60)
                time_str = f"{diff} mins ago" if diff < 60 else f"{int(diff/60)} hours ago"
                if dur > 0: cache_age = f"{time_str} (took {dur}s)"
                else: cache_age = time_str
        except: pass

    # PASS COUNT TO TEMPLATE
    alias_count = TmdbAlias.query.count()
    return render_template('playlists.html', presets=PLAYLIST_PRESETS, custom_presets=custom_presets, schedules=schedules, settings=current_user.settings, cache_age=cache_age, alias_count=alias_count)

@app.route('/manage_blocklist')
@login_required
def manage_blocklist():
    return render_template('blocklist.html', blocks=Blocklist.query.filter_by(user_id=current_user.id).all())

@app.route('/stats')
@login_required
def stats():
    s = current_user.settings
    has_tautulli = bool(s.tautulli_url and s.tautulli_api_key)
    return render_template('stats.html', has_tautulli=has_tautulli, tautulli_active=has_tautulli)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not User.query.filter_by(username=request.form.get('username')).first():
            db.session.add(User(username=request.form.get('username'), password_hash=generate_password_hash(request.form.get('password'))))
            db.session.commit()
            return redirect(url_for('login'))
    return render_template('login.html', is_register=True)

@app.route('/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    try:
        user = current_user
        if user.settings: db.session.delete(user.settings)
        db.session.delete(user)
        db.session.commit()
        logout_user()
        flash('Your profile has been permanently deleted.', 'info')
        return redirect(url_for('login'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting account: {e}', 'error')
        return redirect(url_for('settings'))

def check_and_migrate_db():
    with app.app_context():
        try:
            inspector = sqlalchemy.inspect(db.engine)
            columns_settings = [c['name'] for c in inspector.get_columns('settings')]
            
            if 'omdb_key' not in columns_settings:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN omdb_key VARCHAR(200)'))
                        con.commit()
                except: pass

            if 'cache_interval' not in columns_settings:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN cache_interval INTEGER DEFAULT 24'))
                        con.commit()
                except: pass
            
            if 'logging_enabled' not in columns_settings:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN logging_enabled BOOLEAN DEFAULT 1'))
                        con.commit()
                except: pass

            if 'max_log_size' not in columns_settings:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN max_log_size INTEGER DEFAULT 5'))
                        con.commit()
                except: pass

            columns_schedule = [c['name'] for c in inspector.get_columns('collection_schedule')]
            if 'configuration' not in columns_schedule:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE collection_schedule ADD COLUMN configuration TEXT'))
                        con.commit()
                except: pass

            if 'backup_interval' not in columns_settings:
                try:
                    with db.engine.connect() as con:
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN backup_interval INTEGER DEFAULT 2'))
                        con.execute(sqlalchemy.text('ALTER TABLE settings ADD COLUMN backup_retention INTEGER DEFAULT 7'))
                        con.commit()
                except: pass
            
            if not inspector.has_table("tmdb_alias"):
                try:
                    db.create_all()
                except: pass

        except Exception as e:
            print(f"Migration check skipped: {e}")

with app.app_context():
    try:
        db.create_all() 
    except: pass
    check_and_migrate_db() 
        
from api import *

if __name__ == '__main__':
    # 👇 UPDATED: Disable debug mode for production safety
    app.run(debug=False, host='0.0.0.0', port=5000)