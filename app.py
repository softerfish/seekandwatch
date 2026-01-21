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
import concurrent.futures
import secrets
from flask_wtf.csrf import CSRFProtect
from flask import Flask, Blueprint, request, jsonify, session, send_from_directory, render_template, redirect, url_for, flash
from flask_login import login_required, current_user, LoginManager, login_user, logout_user
from flask_apscheduler import APScheduler
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from plexapi.server import PlexServer
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User, TmdbKeywordCache
from utils import (normalize_title, is_duplicate, fetch_omdb_ratings, send_overseerr_request, 
                   run_collection_logic, create_backup, list_backups, restore_backup, 
                   prune_backups, BACKUP_DIR, CACHE_FILE, sync_remote_aliases, get_tmdb_aliases, 
                   refresh_plex_cache, get_plex_cache, get_lock_status, is_system_locked,
                   write_scanner_log, read_scanner_log, prefetch_keywords_parallel,
                   item_matches_keywords, RESULTS_CACHE, get_session_filters, write_log,
                   check_for_updates, handle_lucky_mode, run_alias_scan, reset_stuck_locks, prefetch_tv_states_parallel)
from presets import PLAYLIST_PRESETS

# ==================================================================================
# 1. APPLICATION CONFIGURATION
# ==================================================================================

VERSION = "1.2.0"

UPDATE_CACHE = {
    'version': None,
    'last_check': 0
}

def get_persistent_key():
    """
    Returns a secure key that persists across restarts.
    Priority:
    1. Docker Environment Variable (for advanced users)
    2. A file stored in /config (auto-generated)
    3. Random fallback (if filesystem is read-only)
    """
    # 1. Check Environment
    env_key = os.environ.get('SECRET_KEY')
    if env_key: 
        return env_key
    
    # 2. Check/Create File
    key_path = '/config/secret.key'
    try:
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                return f.read().strip()
        else:
            # Generate new key and save it
            new_key = secrets.token_hex(32)
            with open(key_path, 'w') as f:
                f.write(new_key)
            return new_key
    except:
        # 3. Fallback (If permissions fail)
        return secrets.token_hex(32)

app = Flask(__name__)
app.config['SECRET_KEY'] = get_persistent_key()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////config/seekandwatch.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
csrf = CSRFProtect(app)

# This protects the app from brute force and denial of service attacks.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["36000 per day", "1500 per hour"], 
    storage_uri="memory://"
)

# Initialize Scheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ==================================================================================
# 2. DATABASE MIGRATION & INIT
# ==================================================================================

def run_migrations():
    """Checks for missing columns, adds them, and fixes admin permissions."""
    with app.app_context():
        # 1. Create Tables if they don't exist
        try: db.create_all()
        except: pass
        
        # 2. Add Missing Columns (Schema Migration)
        try:
            inspector = sqlalchemy.inspect(db.engine)
            
            # Migrate User Table
            user_columns = [c['name'] for c in inspector.get_columns('user')]
            with db.engine.connect() as conn:
                if 'is_admin' not in user_columns:
                    print("--- [Migration] Adding 'is_admin' column to User table ---")
                    conn.execute(sqlalchemy.text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            
            # Migrate Settings Table
            settings_columns = [c['name'] for c in inspector.get_columns('settings')]
            with db.engine.connect() as conn:
                if 'tmdb_region' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN tmdb_region VARCHAR(10) DEFAULT 'US'"))
                if 'ignored_users' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN ignored_users VARCHAR(500)"))
                if 'omdb_key' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN omdb_key VARCHAR(200)"))
                if 'scanner_enabled' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN scanner_enabled BOOLEAN DEFAULT 0"))
                if 'scanner_interval' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN scanner_interval INTEGER DEFAULT 15"))
                if 'scanner_batch' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN scanner_batch INTEGER DEFAULT 50"))
                if 'last_alias_scan' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN last_alias_scan INTEGER DEFAULT 0"))
                if 'kometa_config' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN kometa_config TEXT"))
                if 'scanner_log_size' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN scanner_log_size INTEGER DEFAULT 10"))
                if 'keyword_cache_size' not in settings_columns:
                    conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN keyword_cache_size INTEGER DEFAULT 2000"))
                
                # --- NEW ADDITION HERE ---
                if 'schedule_time' not in settings_columns:
                     print("--- [Migration] Adding 'schedule_time' column ---")
                     conn.execute(sqlalchemy.text("ALTER TABLE settings ADD COLUMN schedule_time VARCHAR(10) DEFAULT '04:00'"))
                    
        except Exception as e:
            print(f"Migration Warning: {e}")

        # 3. FIRST USER ADMIN (Raw SQL Method)
        # This guarantees the fix works even if the ORM model isn't refreshed yet.
        try:
            with db.engine.connect() as conn:
                # Check if ANY admin exists
                result = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user WHERE is_admin = 1")).scalar()
                
                if result == 0:
                    # Check if ANY users exist
                    user_count = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user")).scalar()
                    
                    if user_count > 0:
                        # Promote the user with the lowest ID (The First User)
                        conn.execute(sqlalchemy.text("UPDATE user SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM user)"))
                        conn.commit()
                        print("--- [Startup] AUTO-FIX: No admins found. Promoted the first user to Admin. ---")
        except Exception as e:
            print(f"Admin Auto-Fix Error: {e}")

        # 4. Create Auxiliary Tables
        try: Blocklist.__table__.create(db.engine)
        except: pass
        try: CollectionSchedule.__table__.create(db.engine)
        except: pass
        try: TmdbAlias.__table__.create(db.engine)
        except: pass
        try: TmdbKeywordCache.__table__.create(db.engine)
        except: pass
        
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    
# Run migrations immediately on startup
run_migrations()

# --- BOOT SEQUENCE: CLEARING LOCKS ---
print("--- BOOT SEQUENCE: CLEARING LOCKS ---", flush=True)
try:
    reset_stuck_locks()
except Exception as e:
    print(f"Error resetting locks: {e}", flush=True)


# ==================================================================================
# 3. PAGE ROUTES (Frontend)
# ==================================================================================

@app.context_processor
def inject_version():
    return dict(version=VERSION)

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute") # Strict limit for login
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour") # Very strict limit for creating accounts
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(username=username, password_hash=hashed_pw)
            
            # Auto-Admin Logic (First user is King)
            if not User.query.first():
                new_user.is_admin = True
                
            db.session.add(new_user)
            db.session.commit()
            
            # Create default settings for the new user
            db.session.add(Settings(user_id=new_user.id))
            db.session.commit()
            
            login_user(new_user)
            return redirect(url_for('dashboard'))
            
    return render_template('login.html', register=True)
    
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # 1. USE GLOBAL SETTINGS (Fixes the "Blank Settings" issue for Admins)
    s = Settings.query.order_by(Settings.id.asc()).first()
    
    # 2. Check if cache is expired (4 hours) or empty
    now = time.time()
    if UPDATE_CACHE['version'] is None or (now - UPDATE_CACHE['last_check'] > 14400):
        try:
            # Check GitHub
            latest = check_for_updates(VERSION, "https://raw.githubusercontent.com/softerfish/seekandwatch/main/app.py")
            if latest:
                UPDATE_CACHE['version'] = latest
            UPDATE_CACHE['last_check'] = now
        except:
            pass # Keep old cache if GitHub fails

    # 3. SMARTER VERSION CHECK
    new_version = None
    if UPDATE_CACHE['version']:
        try:
            # Split "1.1.2" -> [1, 1, 2] so we compare numbers accurately
            local_v = [int(x) for x in VERSION.split('.')]
            remote_v = [int(x) for x in UPDATE_CACHE['version'].split('.')]
            
            # Only show update if GitHub is STRICTLY NEWER than us
            if remote_v > local_v:
                new_version = UPDATE_CACHE['version']
        except:
            # Fallback for weird version strings
            if UPDATE_CACHE['version'] != VERSION:
                new_version = UPDATE_CACHE['version']
       
    return render_template('dashboard.html', 
                           settings=s, 
                           new_version=new_version,
                           has_omdb=bool(s.omdb_key if s else False))

@app.route('/review_history', methods=['POST'])
@login_required
def review_history():
    """Gold Standard: Scans history using strict ID-to-Name mapping."""
    import sys 
    
    # USE GLOBAL SETTINGS
    s = Settings.query.order_by(Settings.id.asc()).first()
    
    media_type = request.form.get('media_type', 'movie')
    manual_query = request.form.get('manual_query')
    limit = int(request.form.get('history_limit', 20))
    
    # Session defaults
    session['critic_filter'] = 'true' if request.form.get('critic_filter') else 'false'
    session['critic_threshold'] = request.form.get('critic_threshold', 70)
    
    candidates = []
    
    try:
        # 1. Manual Search Mode
        if manual_query:
            url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={s.tmdb_key}&query={manual_query}"
            res = requests.get(url).json().get('results', [])
            if res:
                item = res[0]
                candidates.append({
                    'title': item.get('title', item.get('name')),
                    'year': (item.get('release_date') or item.get('first_air_date') or '')[:4],
                    'thumb': f"https://image.tmdb.org/t/p/w200{item.get('poster_path')}" if item.get('poster_path') else None,
                    'poster_path': item.get('poster_path')
                })

        # 2. Plex History Mode
        elif s.plex_url and s.plex_token:
            plex = PlexServer(s.plex_url, s.plex_token)
            
            # --- USER MAPPING ---
            user_map = {}
            try:
                for acct in plex.systemAccounts():
                    user_map[int(acct.id)] = acct.name
            except: pass

            try:
                account = plex.myPlexAccount()
                for user in account.users():
                    if user.id:
                        user_map[int(user.id)] = user.title
                if account.id:
                    user_map[int(account.id)] = account.username or "Admin"
            except: pass

            # Prepare ignore list
            ignored = [u.strip().lower() for u in (s.ignored_users or '').split(',')]
            
            history = plex.history(maxresults=5000)
            seen_titles = set()
            lib_type = 'movie' if media_type == 'movie' else 'episode'
            
            for h in history:
                if h.type != lib_type: continue
                
                # Check User
                user_id = getattr(h, 'accountID', None)
                user_name = "Unknown"
                if user_id is not None:
                    user_name = user_map.get(int(user_id), "Unknown")
                
                if user_name == "Unknown":
                    if hasattr(h, 'userName') and h.userName: user_name = h.userName
                    elif hasattr(h, 'user') and hasattr(h.user, 'title'): user_name = h.user.title

                if user_name.lower() in ignored: continue

                # --- DEDUPLICATE TV SHOWS ---
                # If it's an episode, use the Show Name (grandparentTitle)
                if h.type == 'episode':
                    title = h.grandparentTitle
                else:
                    title = h.title
                
                # Fallback checks
                if not title:
                    if hasattr(h, 'sourceTitle') and h.sourceTitle: title = h.sourceTitle
                    else: title = h.title

                if not title: continue
                
                # If we've already seen this Show Name, skip it (hides duplicate episodes)
                if title in seen_titles: continue
                
                year = h.year if hasattr(h, 'year') else 0
                
                # Fix TV Posters
                thumb = None
                try: 
                    if h.type == 'episode': thumb = h.grandparentThumb or h.thumb
                    else: thumb = h.thumb 
                except: pass

                candidates.append({
                    'title': title,
                    'year': year,
                    'thumb': f"{s.plex_url}{thumb}?X-Plex-Token={s.plex_token}" if thumb else None,
                    'poster_path': None
                })
                seen_titles.add(title)
            
            # --- SHUFFLE & LIMIT ---
            random.shuffle(candidates)
            candidates = candidates[:limit]

    except Exception as e:
        flash(f"Scan failed: {str(e)}", "error")
        return redirect(url_for('dashboard'))
        
    # Get Providers for Filtering
    providers = []
    try:
        reg = s.tmdb_region.split(',')[0] if s.tmdb_region else 'US'
        p_url = f"https://api.themoviedb.org/3/watch/providers/{media_type}?api_key={s.tmdb_key}&watch_region={reg}"
        p_data = requests.get(p_url).json().get('results', [])
        providers = sorted(p_data, key=lambda x: x.get('display_priority', 999))[:30]
    except: pass

    # Get Genres
    genres = []
    try:
        g_url = f"https://api.themoviedb.org/3/genre/{media_type}/list?api_key={s.tmdb_key}"
        genres = requests.get(g_url).json().get('genres', [])
    except: pass

    return render_template('review.html', 
                           movies=candidates, 
                           media_type=media_type,
                           providers=providers,
                           genres=genres)
                           
@app.route('/generate', methods=['POST'])
@login_required
def generate():
    s = Settings.query.filter_by(user_id=current_user.id).first()
    owned_keys = get_plex_cache(s)
    
    if request.form.get('lucky_mode') == 'true':
        raw_candidates = handle_lucky_mode(s)
        if not raw_candidates:
             flash("Could not find a lucky pick!", "error")
             return redirect(url_for('dashboard'))
        

        lucky_result = []
        for item in raw_candidates:
            # Stop once we have 5 good ones
            if len(lucky_result) >= 5: break
            
            # 1. Check Title (Fuzzy)
            t_clean = normalize_title(item['title'])
            if t_clean in owned_keys: continue
            
            # 2. Check ID (Exact - Alias DB)
            if TmdbAlias.query.filter_by(tmdb_id=item['id']).first(): continue
            
            lucky_result.append(item)
            
        if not lucky_result:
             flash("You own all the lucky picks! Try again.", "error")
             return redirect(url_for('dashboard'))

        RESULTS_CACHE[current_user.id] = {'candidates': lucky_result, 'next_index': len(lucky_result)}
        return render_template('results.html', movies=lucky_result, min_year=0, min_rating=0, genres=[], current_genre=None, use_critic_filter='false')

    # 2. STANDARD MODE
    media_type = request.form.get('media_type')
    selected_titles = request.form.getlist('selected_movies')
    
    session['media_type'] = media_type
    session['selected_titles'] = selected_titles
    session['genre_filter'] = request.form.get('genre_filter')
    session['keywords'] = request.form.get('keywords', '')
    
    try: session['min_year'] = int(request.form.get('min_year', 0))
    except: session['min_year'] = 0
    try: session['min_rating'] = float(request.form.get('min_rating', 0))
    except: session['min_rating'] = 0
    
    if not selected_titles:
        flash('Please select at least one item.', 'error')
        return redirect(url_for('dashboard'))

    blocked = set([b.title for b in Blocklist.query.filter_by(user_id=current_user.id).all()])
    
    recommendations = []
    seen_ids = set()
    seed_ids = []
    
    # Resolve Seeds
    for title in selected_titles:
        try:
            search_url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={s.tmdb_key}&query={title}"
            r = requests.get(search_url).json()
            if r.get('results'):
                seed_ids.append(r['results'][0]['id'])
        except: pass
            
    ## Fetch Recommendations (fetch 3 pages of media_type per media_type)
    for tmdb_id in seed_ids:
        try:
            # Loop through pages 1, 2, and 3 to get 60 items per seed
            for page_num in range(1, 4): 
                rec_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/recommendations?api_key={s.tmdb_key}&language=en-US&page={page_num}"
                data = requests.get(rec_url).json()
                
                for item in data.get('results', []):
                    if item['id'] in seen_ids: continue
                    
                    item['media_type'] = media_type
                    date = item.get('release_date') or item.get('first_air_date')
                    item['year'] = int(date[:4]) if date else 0
                    
                    if item.get('title', item.get('name')) in blocked: continue
                    t_clean = normalize_title(item.get('title', item.get('name')))
                    if t_clean in owned_keys: continue
                    
                    alias = TmdbAlias.query.filter_by(tmdb_id=item['id'], media_type=media_type).first()
                    if alias: continue 

                    recommendations.append(item)
                    seen_ids.add(item['id'])
        except: pass
            
    random.shuffle(recommendations)
    
    RESULTS_CACHE[current_user.id] = {
        'candidates': recommendations,
        'next_index': 0
    }
    
    # --- PROCESSING ---
    min_year, min_rating, genre_filter, critic_enabled, threshold = get_session_filters()
    raw_keywords = session.get('keywords', '')
    target_keywords = [k.strip() for k in raw_keywords.split('|') if k.strip()]

    # PARALLEL PREFETCH
    # Always run to populate cache for future filtering
    if target_keywords:
        # A. FILTERING ACTIVE: We must wait for data to filter correctly
        prefetch_keywords_parallel(recommendations, s.tmdb_key)
    else:
        # B. BROWSING MODE: Run in background to prevent Timeout/Crashing
        # This keeps the UI fast while filling the cache silently
        def async_prefetch(app_obj, items, key):
            with app_obj.app_context():
                prefetch_keywords_parallel(items, key)
        
        threading.Thread(target=async_prefetch, 
                         args=(app, recommendations, s.tmdb_key)).start()

    final_list = []
    idx = 0
    
# --- PROCESSING LOOP ---
    # Increased limit to 40 to fill larger screens
    while len(final_list) < 40 and idx < len(recommendations):
        item = recommendations[idx]
        idx += 1
        
        # 1. Apply Filters
        if item['year'] < min_year: continue
        if item.get('vote_average', 0) < min_rating: continue
        if genre_filter and genre_filter != 'all':
            if int(genre_filter) not in item.get('genre_ids', []): continue
            
        if target_keywords:
            if not item_matches_keywords(item, target_keywords):
                continue

        # 2. Get Badges (OMDB/Rotten Tomatoes)
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

    while len(final_list) < 40 and idx < len(recommendations):
        # ... (loop logic) ...
        final_list.append(item)

    if media_type == 'tv':
        prefetch_tv_states_parallel(final_list, s.tmdb_key)

    # Save Index for "Load More"
    RESULTS_CACHE[current_user.id]['next_index'] = idx
    
    # 4. SMART BACKGROUND PREFETCH (Prevents Timeouts)
    # If filtering, we wait. If browsing, we do it in background.
    if target_keywords:
        prefetch_keywords_parallel(recommendations, s.tmdb_key)
    else:
        def async_prefetch(app_obj, items, key):
            with app_obj.app_context():
                prefetch_keywords_parallel(items, key)
        threading.Thread(target=async_prefetch, args=(app, recommendations, s.tmdb_key)).start()
        
    g_url = f"https://api.themoviedb.org/3/genre/{media_type}/list?api_key={s.tmdb_key}"
    try: genres = requests.get(g_url).json().get('genres', [])
    except: genres = []

    return render_template('results.html', 
                           movies=final_list, 
                           genres=genres,
                           current_genre=genre_filter,
                           min_year=min_year,
                           min_rating=min_rating,
                           use_critic_filter='true' if critic_enabled else 'false')

@app.route('/reset_alias_db')
@login_required
def reset_alias_db():
    """Nuclear option to fix owned movies showing up"""
    try:
        db.session.query(TmdbAlias).delete()
        s = Settings.query.filter_by(user_id=current_user.id).first()
        s.last_alias_scan = 0
        db.session.commit()
        return "<h1>Alias DB Wiped.</h1><p>The scanner will now restart from scratch. Please wait 10 minutes and check logs.</p><a href='/dashboard'>Back</a>"
    except Exception as e:
        return f"Error: {e}"

@app.route('/playlists')
@login_required
def playlists():
    # 1. Get the Global Schedule Time
    s = Settings.query.filter_by(user_id=current_user.id).first()
    current_time = s.schedule_time if s and s.schedule_time else "04:00"

    # 2. Get Schedules
    schedules = {}
    for sch in CollectionSchedule.query.all():
        schedules[sch.preset_key] = sch.frequency
        
    # 3. Get Custom Presets
    custom_presets = {}
    for sch in CollectionSchedule.query.filter(CollectionSchedule.preset_key.like('custom_%')).all():
        if sch.configuration:
            config = json.loads(sch.configuration)
            custom_presets[sch.preset_key] = {
                'title': config.get('title', 'Untitled'),
                'description': config.get('description', 'Custom Builder Collection'),
                'media_type': config.get('media_type', 'movie'),
                'icon': config.get('icon', '🛠️')
            }

    # 4. Render with the new 'schedule_time' variable
    return render_template('playlists.html', 
                           presets=PLAYLIST_PRESETS, 
                           schedules=schedules, 
                           custom_presets=custom_presets,
                           schedule_time=current_time) # <--- THIS IS THE NEW PART
                           
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    s = Settings.query.filter_by(user_id=current_user.id).first()
    
    if request.method == 'POST':
        s.plex_url = request.form.get('plex_url')
        s.plex_token = request.form.get('plex_token')
        s.tmdb_key = request.form.get('tmdb_key')
        s.tmdb_region = request.form.get('tmdb_region')
        s.omdb_key = request.form.get('omdb_key')
        s.overseerr_url = request.form.get('overseerr_url')
        s.overseerr_api_key = request.form.get('overseerr_api_key')
        s.tautulli_url = request.form.get('tautulli_url')
        s.tautulli_api_key = request.form.get('tautulli_api_key')
        s.backup_interval = int(request.form.get('backup_interval', 2))
        s.backup_retention = int(request.form.get('backup_retention', 7))
        
        try: s.keyword_cache_size = int(request.form.get('keyword_cache_size', 2000))
        except: s.keyword_cache_size = 2000
        
        db.session.commit()
        
        # Max log size
        try: s.max_log_size = int(request.form.get('max_log_size', 5))
        except: s.max_log_size = 5
        
        try: s.scanner_log_size = int(request.form.get('scanner_log_size', 10))
        except: s.scanner_log_size = 10
        
        db.session.commit()
        # Send both 'message' and 'msg' to satisfy any frontend variation
        return jsonify({'status': 'success', 'message': 'Settings saved successfully.', 'msg': 'Settings saved successfully.'})

# Get Plex Users for Ignore List
    plex_users = []
    try:
        if s.plex_url and s.plex_token:
            p = PlexServer(s.plex_url, s.plex_token, timeout=3)
            # Try MyPlex first
            try:
                account = p.myPlexAccount()
                plex_users = [u.title for u in account.users()]
                if account.username: plex_users.insert(0, account.username)
            except:
                # Fallback: Try to guess from connected clients/system
                try: plex_users.append(p.myPlexAccount().username)
                except: pass
    except: pass
    
    # Parse ignored
    current_ignored = (s.ignored_users or '').split(',')

    # Logs
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(50).all()
    
# Cache Age
    cache_age = "Never"
    if os.path.exists(CACHE_FILE):
        ts = os.path.getmtime(CACHE_FILE)
        dt = datetime.datetime.fromtimestamp(ts)
        cache_age = dt.strftime('%Y-%m-%d %H:%M')

    # Get Count
    try: keyword_count = TmdbKeywordCache.query.count()
    except: keyword_count = 0

    return render_template('settings.html', 
                           settings=s, 
                           plex_users=plex_users, 
                           current_ignored=current_ignored, 
                           logs=logs, 
                           cache_age=cache_age,
                           keyword_count=keyword_count)

@app.route('/logs_page')
@login_required
def logs_page():
    # Dedicated logs page
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(200).all()
    s = Settings.query.filter_by(user_id=current_user.id).first()
    return render_template('logs.html', logs=logs, settings=s)

@app.route('/stats')
@login_required
def stats():       # <--- Renamed to 'stats' to match the template
    s = Settings.query.filter_by(user_id=current_user.id).first()
    has_tautulli = bool(s.tautulli_url and s.tautulli_api_key)
    return render_template('stats.html', has_tautulli=has_tautulli, tautulli_active=has_tautulli)

@app.route('/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    user = User.query.get(current_user.id)
    Settings.query.filter_by(user_id=current_user.id).delete()
    Blocklist.query.filter_by(user_id=current_user.id).delete()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))

@app.route('/builder')
@login_required
def builder():
    s = Settings.query.filter_by(user_id=current_user.id).first()
    try:
        g_url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={s.tmdb_key}"
        genres = requests.get(g_url).json().get('genres', [])
    except: genres = []
    return render_template('builder.html', genres=genres)

@app.route('/manage_blocklist')
@login_required
def manage_blocklist():
    blocks = Blocklist.query.filter_by(user_id=current_user.id).all()
    return render_template('blocklist.html', blocks=blocks)

@app.route('/kometa')
@login_required
def kometa():
    s = Settings.query.filter_by(user_id=current_user.id).first()
    return render_template('kometa.html', settings=s)

# ==================================================================================
# 4. SCHEDULER (Background Tasks)
# ==================================================================================

def run_scan_wrapper(app_ref):
    """Wraps the scanner in the app context to prevent DB crashes."""
    with app_ref.app_context():
        from utils import run_alias_scan
        run_alias_scan(app_ref)

def scheduled_tasks():
    with app.app_context():
        # 1. Prune Backups (Daily at 4:00 AM hardcoded for system cleanup)
        if datetime.datetime.now().hour == 4 and datetime.datetime.now().minute == 0:
            prune_backups()
            
        # 2. Cache Refresh (Based on Interval)
        s = Settings.query.first()
        if not s: return
        
        # Check Cache Age
        if os.path.exists(CACHE_FILE):
            mod_time = os.path.getmtime(CACHE_FILE)
            age_hours = (time.time() - mod_time) / 3600
            if age_hours >= (s.cache_interval or 24):
                 if not is_system_locked():
                     print("Scheduler: Starting Cache Refresh...")
                     refresh_plex_cache(app)

        # 3. Collection Schedules
        # PARSE GLOBAL RUN TIME (Default 04:00 AM)
        try:
            target_hour, target_minute = map(int, (s.schedule_time or "04:00").split(':'))
        except:
            target_hour, target_minute = 4, 0
            
        now = datetime.datetime.now()

        for sch in CollectionSchedule.query.all():
            if sch.frequency == 'manual': continue
            
            should_run = False
            last = sch.last_run
            
            # --- NEW LOGIC: "Run Once Per Day After X Time" ---
            if sch.frequency == 'daily':
                # Rule 1: Has it run today?
                run_today = False
                if last and last.date() == now.date():
                    run_today = True
                
                # Rule 2: Is it past the target time?
                past_target_time = False
                if now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute):
                    past_target_time = True
                
                # Execute if we haven't run today AND it's past the scheduled time
                if not run_today and past_target_time:
                    should_run = True

            # --- WEEKLY LOGIC ---
            elif sch.frequency == 'weekly':
                if not last:
                    should_run = True
                else:
                    delta = now - last
                    if delta.days >= 7: should_run = True
                
            if should_run:
                print(f"Scheduler: Running collection {sch.preset_key}...")
                
                # Fetch Preset Data
                if sch.preset_key.startswith('custom_'):
                     preset_data = json.loads(sch.configuration)
                else:
                     # 1. Load Default
                     preset_data = PLAYLIST_PRESETS.get(sch.preset_key, {}).copy()
                     
                     # 2. Merge User Overrides (Sync Mode)
                     if sch.configuration:
                         try:
                             user_config = json.loads(sch.configuration)
                             preset_data.update(user_config)
                         except: pass
                
                if preset_data:
                    # Run Logic from Utils
                    success, msg = run_collection_logic(s, preset_data, sch.preset_key)
                    if success:
                        sch.last_run = now
                        db.session.commit()

        # 4. BACKGROUND ALIAS SCANNER
        if s.scanner_enabled:
            # Check interval
            last = s.last_alias_scan or 0
            now_ts = int(time.time())
            interval_sec = (s.scanner_interval or 15) * 60
            
            if now_ts - last >= interval_sec:
                if not is_system_locked():
                    print("Scheduler: Starting Background Alias Scan...")
                    # Use the wrapper to pass the context
                    threading.Thread(target=run_scan_wrapper, args=(app,)).start()

scheduler.add_job(id='master_task', func=scheduled_tasks, trigger='interval', minutes=1)

# ==================================================================================
# 5. IMPORT API BLUEPRINT (Crucial Fix)
# ==================================================================================
from api import api_bp
app.register_blueprint(api_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)