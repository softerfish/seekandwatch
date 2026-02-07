"""Main Flask app - handles routing, auth, and the main UI stuff."""

import base64
import time
import os
import re
import sys

import config
from config import CONFIG_DIR, DATABASE_URI, SECRET_KEY_FILE, CLOUD_REQUEST_TIMEOUT
from utils import get_cloud_base_url
import requests
import random
import json
import datetime
from datetime import timedelta
import threading
import socket
import hashlib
import sqlalchemy
import concurrent.futures
import secrets
import subprocess

from flask import Flask, Blueprint, request, jsonify, session, send_from_directory, render_template, redirect, url_for, flash
from flask_login import login_required, current_user, LoginManager, login_user, logout_user
from auth_decorators import admin_required
from flask_apscheduler import APScheduler
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, generate_csrf
from plexapi.server import PlexServer
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User, TmdbKeywordCache, TmdbRuntimeCache, RadarrSonarrCache, RecoveryCode, CloudRequest, DeletedCloudId
from utils import (normalize_title, is_duplicate, is_owned_item, fetch_omdb_ratings, send_overseerr_request, 
                   run_collection_logic, create_backup, list_backups, restore_backup, 
                   prune_backups, BACKUP_DIR, sync_remote_aliases, get_tmdb_aliases, 
                   sync_plex_library, refresh_radarr_sonarr_cache, get_lock_status, is_system_locked,
                   write_scanner_log, read_scanner_log, prefetch_keywords_parallel,
                   item_matches_keywords, RESULTS_CACHE, get_session_filters, write_log,
                   check_for_updates, handle_lucky_mode, reset_stuck_locks, 
                   prefetch_tv_states_parallel, prefetch_ratings_parallel, prefetch_omdb_parallel,
                   prefetch_runtime_parallel, is_docker, is_unraid, is_git_repo, is_app_dir_writable, perform_git_update,
                   perform_release_update, save_results_cache, get_history_cache, set_history_cache,
                   score_recommendation, diverse_sample, get_tmdb_rec_cache, set_tmdb_rec_cache)
from presets import PLAYLIST_PRESETS
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

# basic app setup stuff

VERSION = "1.5.9"

UPDATE_CACHE = {
    'version': None,
    'last_check': 0
}

def get_persistent_key():
    """Gets the secret key from env or file, or makes a new one if needed."""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key

    key_path = SECRET_KEY_FILE
    try:
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                return f.read().strip()
        new_key = secrets.token_hex(32)
        with open(key_path, 'w') as f:
            f.write(new_key)
        return new_key
    except OSError as e:
        print(f"--- WARNING: Could not persist SECRET_KEY to disk ({type(e).__name__}); using temporary key. Set SECRET_KEY env or ensure {CONFIG_DIR!r} is writable. ---", flush=True)
        return secrets.token_hex(32)

app = Flask(__name__)
app.config['SECRET_KEY'] = get_persistent_key()
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Limit request body size (mitigates CVE-2024-49767 / multipart exhaustion)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
# Session cookie hardening. Set SECURE_COOKIE=1 (or SESSION_COOKIE_SECURE=1) when serving over HTTPS.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SECURE_COOKIE', '').strip() in ('1', 'true', 'yes') or os.environ.get('SESSION_COOKIE_SECURE', '').strip() in ('1', 'true', 'yes')
csrf = CSRFProtect(app)

# Rate limiting to prevent abuse.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["36000 per day", "1500 per hour"], 
    storage_uri="memory://"
)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


@app.after_request
def add_security_headers(response):
    """Add security-related response headers."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response


def _ensure_migrations():
    """If the DB is behind (e.g. after restore or post-update), run migrations so users never hit missing-column errors."""
    try:
        row = db.session.execute(text("SELECT version FROM schema_info WHERE id = 1")).fetchone()
        if row is not None and row[0] >= CURRENT_SCHEMA_VERSION:
            return
    except OperationalError as e:
        msg = str(e).lower()
        if "no such column" not in msg and "no such table" not in msg:
            raise
    run_migrations()
    db.session.rollback()
    # Force new connections so this request sees the updated schema (SQLite caches schema per connection).
    db.engine.dispose()


# Flag file written by restore_backup() so every worker disposes and reopens the DB (multi-worker).
DB_RESTORED_FLAG = os.path.join(CONFIG_DIR, '.seekandwatch_db_restored')

@app.before_request
def ensure_schema():
    """Run migrations when DB is behind; after restore, make this worker reopen the DB."""
    if os.path.exists(DB_RESTORED_FLAG):
        try:
            # Stale flag (e.g. process died before timer): remove so we don't dispose every request forever.
            if time.time() - os.path.getmtime(DB_RESTORED_FLAG) > 60:
                os.remove(DB_RESTORED_FLAG)
            else:
                db.session.remove()
                db.engine.dispose()
        except OSError:
            pass
    _ensure_migrations()


# db commit with retry (helps when sqlite is briefly locked)
def commit_with_retry(max_retries=3):
    for attempt in range(max_retries):
        try:
            db.session.commit()
            return
        except OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(0.15 * (attempt + 1))
                else:
                    raise
            else:
                raise


def _valid_url(val):
    """True if value is empty or a safe http(s) URL (no javascript:, data:)."""
    if not val or not str(val).strip():
        return True
    v = str(val).strip().lower()
    if v.startswith("javascript:") or v.startswith("data:"):
        return False
    return v.startswith("http://") or v.startswith("https://")


# database migration stuff - adds new columns and fixes admin issues
# Bump this when adding new migrations so request-time check can run migrations after restore/update.
CURRENT_SCHEMA_VERSION = 2

def _alter_add_column(conn, sql):
    """Run ALTER TABLE ADD COLUMN; ignore duplicate column (inspector can be stale)."""
    try:
        conn.execute(sqlalchemy.text(sql))
    except OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

def run_migrations():
    """Adds any missing DB columns and makes sure there's always at least one admin."""
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"--- [Migration] create_all: {type(e).__name__} ---", flush=True)
        
        # add any missing columns to existing tables
        try:
            inspector = sqlalchemy.inspect(db.engine)
            
            # check user table
            user_columns = [c['name'] for c in inspector.get_columns('user')]
            with db.engine.connect() as conn:
                if 'is_admin' not in user_columns:
                    print("--- [Migration] Adding 'is_admin' column to User table ---")
                    _alter_add_column(conn, "ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            
            # Settings table.
            settings_columns = [c['name'] for c in inspector.get_columns('settings')]
            with db.engine.connect() as conn:
                if 'tmdb_region' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tmdb_region VARCHAR(10) DEFAULT 'US'")
                if 'ignored_users' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN ignored_users VARCHAR(500)")
                if 'omdb_key' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN omdb_key VARCHAR(200)")
                if 'scanner_enabled' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN scanner_enabled BOOLEAN DEFAULT 0")
                if 'scanner_interval' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN scanner_interval INTEGER DEFAULT 15")
                if 'scanner_batch' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN scanner_batch INTEGER DEFAULT 500")
                if 'last_alias_scan' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN last_alias_scan INTEGER DEFAULT 0")
                if 'kometa_config' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN kometa_config TEXT")
                if 'scanner_log_size' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN scanner_log_size INTEGER DEFAULT 10")
                if 'keyword_cache_size' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN keyword_cache_size INTEGER DEFAULT 3000")
                if 'runtime_cache_size' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN runtime_cache_size INTEGER DEFAULT 3000")
                if 'radarr_sonarr_scanner_enabled' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN radarr_sonarr_scanner_enabled BOOLEAN DEFAULT 0")
                if 'radarr_sonarr_scanner_interval' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN radarr_sonarr_scanner_interval INTEGER DEFAULT 24")
                if 'last_radarr_sonarr_scan' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN last_radarr_sonarr_scan INTEGER DEFAULT 0")
                if 'schedule_time' not in settings_columns:
                    print("--- [Migration] Adding 'schedule_time' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN schedule_time VARCHAR(10) DEFAULT '04:00'")
                if 'ignored_libraries' not in settings_columns:
                    print("--- [Migration] Adding 'ignored_libraries' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN ignored_libraries VARCHAR(500)")
                if 'radarr_url' not in settings_columns:
                    print("--- [Migration] Adding 'radarr_url' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN radarr_url VARCHAR(200)")
                if 'radarr_api_key' not in settings_columns:
                    print("--- [Migration] Adding 'radarr_api_key' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN radarr_api_key VARCHAR(200)")
                if 'sonarr_url' not in settings_columns:
                    print("--- [Migration] Adding 'sonarr_url' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN sonarr_url VARCHAR(200)")
                if 'sonarr_api_key' not in settings_columns:
                    print("--- [Migration] Adding 'sonarr_api_key' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN sonarr_api_key VARCHAR(200)")
                if 'cloud_enabled' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_enabled' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_enabled BOOLEAN DEFAULT 0")
                if 'cloud_api_key' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_api_key' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_api_key VARCHAR(100)")
                if 'cloud_base_url' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_base_url' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_base_url VARCHAR(256)")
                if 'cloud_auto_approve' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_auto_approve' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_auto_approve BOOLEAN DEFAULT 0")
                if 'cloud_movie_handler' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_movie_handler' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_movie_handler VARCHAR(20) DEFAULT 'direct'")
                if 'cloud_tv_handler' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_tv_handler' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_tv_handler VARCHAR(20) DEFAULT 'direct'")
                if 'cloud_sync_owned_enabled' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_sync_owned_enabled' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_sync_owned_enabled BOOLEAN DEFAULT 1")
                if 'cloud_sync_owned_interval_hours' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_sync_owned_interval_hours' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_sync_owned_interval_hours INTEGER DEFAULT 24")
                if 'last_owned_sync_at' not in settings_columns:
                    print("--- [Migration] Adding 'last_owned_sync_at' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN last_owned_sync_at DATETIME")
                if 'cloud_webhook_url' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_webhook_url' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_webhook_url VARCHAR(512)")
                if 'cloud_webhook_secret' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_webhook_secret' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_webhook_secret VARCHAR(255)")
                if 'cloud_poll_interval_min' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_poll_interval_min' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_poll_interval_min INTEGER")
                if 'cloud_poll_interval_max' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_poll_interval_max' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_poll_interval_max INTEGER")
                if 'last_cloud_poll_at' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN last_cloud_poll_at DATETIME")
                if 'last_cloud_poll_ok' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN last_cloud_poll_ok BOOLEAN")
                conn.commit()
                
                # Check if kometa_template table exists
                try:
                    conn.execute(sqlalchemy.text("SELECT 1 FROM kometa_template LIMIT 1"))
                except Exception:
                    # Create kometa_template table
                    conn.execute(sqlalchemy.text("""
                        CREATE TABLE IF NOT EXISTS kometa_template (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            name VARCHAR(200) NOT NULL,
                            type VARCHAR(20),
                            cols TEXT,
                            ovls TEXT,
                            template_vars TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (user_id) REFERENCES user(id)
                        )
                    """))
                    
        except Exception as e:
            print(f"--- [Migration] Schema: {type(e).__name__}: {e} ---", flush=True)

        # if somehow there are no admins, make the first user an admin
        # (shouldn't happen but better safe than sorry)
        try:
            with db.engine.connect() as conn:
                result = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user WHERE is_admin = 1")).scalar()
                
                if result == 0:
                    user_count = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user")).scalar()
                    
                    if user_count > 0:
                        # Promote the lowest ID user.
                        conn.execute(sqlalchemy.text("UPDATE user SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM user)"))
                        conn.commit()
                        print("--- [Startup] AUTO-FIX: No admins found. Promoted the first user to Admin. ---")
        except Exception as e:
            print(f"--- [Migration] Admin auto-fix: {type(e).__name__}: {e} ---", flush=True)

        for model_name, model in [
            ('Blocklist', Blocklist),
            ('CollectionSchedule', CollectionSchedule),
            ('TmdbAlias', TmdbAlias),
            ('TmdbKeywordCache', TmdbKeywordCache),
            ('TmdbRuntimeCache', TmdbRuntimeCache),
            ('RadarrSonarrCache', RadarrSonarrCache),
            ('RecoveryCode', RecoveryCode),
            ('CloudRequest', CloudRequest),
        ]:
            try:
                model.__table__.create(db.engine, checkfirst=True)
            except Exception as e:
                print(f"--- [Migration] Create table {model_name}: {type(e).__name__} ---", flush=True)
        # add user_id to app_request so requested media is per-user (security)
        try:
            inspector = sqlalchemy.inspect(db.engine)
            if 'app_request' in inspector.get_table_names():
                app_request_columns = [c['name'] for c in inspector.get_columns('app_request')]
                if 'user_id' not in app_request_columns:
                    with db.engine.connect() as conn:
                        _alter_add_column(conn, "ALTER TABLE app_request ADD COLUMN user_id INTEGER REFERENCES user(id)")
                        conn.commit()
                        # backfill: assign existing rows to first user so they still show for that user
                        first_user = conn.execute(sqlalchemy.text("SELECT id FROM user ORDER BY id ASC LIMIT 1")).scalar()
                        if first_user is not None:
                            conn.execute(sqlalchemy.text("UPDATE app_request SET user_id = :uid WHERE user_id IS NULL"), {"uid": first_user})
                            conn.commit()
        except Exception as ex:
            print(f"Migration Warning (app_request user_id): {ex}")

        # cloud_request: optional year column for release year from cloud; notes from requester
        try:
            inspector = sqlalchemy.inspect(db.engine)
            if 'cloud_request' in inspector.get_table_names():
                cloud_req_columns = [c['name'] for c in inspector.get_columns('cloud_request')]
                if 'year' not in cloud_req_columns:
                    with db.engine.connect() as conn:
                        _alter_add_column(conn, "ALTER TABLE cloud_request ADD COLUMN year VARCHAR(4)")
                        conn.commit()
                        print("--- [Migration] Added 'year' column to cloud_request ---")
                if 'notes' not in cloud_req_columns:
                    with db.engine.connect() as conn:
                        _alter_add_column(conn, "ALTER TABLE cloud_request ADD COLUMN notes TEXT")
                        conn.commit()
                        print("--- [Migration] Added 'notes' column to cloud_request ---")
        except Exception as ex:
            print(f"Migration Warning (cloud_request year/notes): {ex}")

        # radarr_sonarr_cache: has_file so we only treat "has file" as owned (Radarr: "Not Available" = no file)
        try:
            inspector = sqlalchemy.inspect(db.engine)
            if 'radarr_sonarr_cache' in inspector.get_table_names():
                cache_columns = [c['name'] for c in inspector.get_columns('radarr_sonarr_cache')]
                if 'has_file' not in cache_columns:
                    with db.engine.connect() as conn:
                        _alter_add_column(conn, "ALTER TABLE radarr_sonarr_cache ADD COLUMN has_file BOOLEAN DEFAULT 1")
                        conn.commit()
                        print("--- [Migration] Added 'has_file' column to radarr_sonarr_cache ---")
        except Exception as ex:
            print(f"Migration Warning (radarr_sonarr_cache has_file): {ex}")

        # Record schema version so request-time check can detect restore/out-of-date DB
        try:
            with db.engine.connect() as conn:
                conn.execute(sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS schema_info (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"
                ))
                conn.execute(sqlalchemy.text("INSERT OR REPLACE INTO schema_info (id, version) VALUES (1, :v)"), {"v": CURRENT_SCHEMA_VERSION})
                conn.commit()
        except Exception as e:
            print(f"--- [Migration] schema_info: {type(e).__name__}: {e} ---", flush=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    
try:
    run_migrations()
except Exception as e:
    print(f"--- STARTUP ERROR: migrations failed: {e} ---", flush=True)
    sys.exit(1)

# clear any leftover lock files from crashes/restarts
print("--- BOOT SEQUENCE: CLEARING LOCKS ---", flush=True)
try:
    reset_stuck_locks()
except Exception as e:
    print(f"Error resetting locks: {e}", flush=True)

# GitHub stats cache.
github_cache = {
    "stars": "...",
    "latest_version": "0.0.0",
    "last_updated": 0
}

def update_github_stats():
    """Grabs github stars and latest version, runs every hour in the background."""
    while True:
        try:
            headers = {"User-Agent": "SeekAndWatch-App"}
            r_stars = requests.get('https://api.github.com/repos/softerfish/seekandwatch', headers=headers)
            if r_stars.ok:
                data = r_stars.json()
                github_cache['stars'] = data.get('stargazers_count', '...')

            r_release = requests.get('https://api.github.com/repos/softerfish/seekandwatch/releases/latest', headers=headers)
            if r_release.ok:
                tag = r_release.json().get('tag_name', 'v0.0.0')
                github_cache['latest_version'] = tag.replace('v', '')
                
            github_cache['last_updated'] = time.time()
            
        except Exception as e:
            print(f"GitHub Update Error: {e}")
            
        time.sleep(3600)

# Start background thread.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=update_github_stats, daemon=True).start()
    # Cloud requests are polled every minute via scheduled_tasks() when cloud sync is enabled

# Inject into all templates.
@app.context_processor
def inject_github_data():
    return dict(
        github_stars=github_cache['stars'],
        latest_version=github_cache['latest_version'],
        current_version=VERSION,
        is_unraid=is_unraid()
    )

# main page routes

# one-click updater for git/release installs (CSRF required via X-CSRFToken in fetch)
@app.route('/trigger_update', methods=['POST'])
@limiter.limit("10 per hour")
@login_required
def trigger_update_route():
    import json
    import sys
    from flask import Response
    
    # Allow the confirm modal to force an update.
    force_update = request.args.get('force_git') == 'true'
    
    try:
        # Check latest release.
        current_version = "Unknown"
        try: current_version = VERSION
        except Exception: pass
        latest = check_for_updates(current_version, "https://api.github.com/repos/softerfish/seekandwatch/releases/latest")
        if not latest and not force_update:
             return Response(json.dumps({'status': 'success', 'message': 'Up to date', 'action': 'none'}), mimetype='application/json')

        # unraid users have to update through the app store, can't do it here
        if is_unraid():
            return Response(json.dumps({
                'status': 'success',
                'message': 'Update available!',
                'action': 'unraid_instruction',
                'version': str(latest)
            }), mimetype='application/json')

        if not is_git_repo() and not force_update:
            if is_app_dir_writable():
                return Response(json.dumps({
                    'status': 'success',
                    'message': 'Update available',
                    'action': 'release_update_available',
                    'version': str(latest)
                }), mimetype='application/json')
            if is_docker():
                return Response(json.dumps({
                    'status': 'success',
                    'message': 'Update available!',
                    'action': 'docker_instruction',
                    'version': str(latest)
                }), mimetype='application/json')
            return Response(json.dumps({'status': 'success', 'message': 'Manual update required', 'action': 'manual_instruction', 'version': str(latest)}), mimetype='application/json')

        # Manual (git) installs: ask for confirmation before pulling.
        if is_git_repo() and not force_update:
            return Response(json.dumps({
                'status': 'success',
                'message': 'Update available',
                'action': 'git_update_available',
                'version': str(latest)
            }), mimetype='application/json')

        # git updates are preferred if available
        if is_git_repo():
            print(f"--- Git Update Triggered (Force: {force_update}) ---", flush=True)
            success, msg = perform_git_update()
            action = 'restart_needed' if success else 'error'
            status = 'success' if success else 'error'
            return Response(json.dumps({'status': status, 'message': msg, 'action': action}), mimetype='application/json')

        # No git repo: try a release update when forced.
        if force_update:
            success, msg = perform_release_update()
            action = 'restart_needed' if success else 'error'
            status = 'success' if success else 'error'
            return Response(json.dumps({'status': status, 'message': msg, 'action': action}), mimetype='application/json')

        return Response(json.dumps({'status': 'error', 'message': 'Update failed to determine path.'}), mimetype='application/json')

    except Exception as e:
        try:
            # Do not log full traceback or exception message (clear-text logging of sensitive information)
            write_log("error", "Updater", f"Update failed: {type(e).__name__}")
        except Exception:
            pass
        print("Update Error (see logs).", flush=True)
        return Response(json.dumps({'status': 'error', 'message': 'Update failed. Check logs for details.'}), mimetype='application/json')
        
@app.context_processor
def inject_version():
    return dict(version=VERSION)

@app.context_processor
def inject_pending_requests_count():
    """Inject pending cloud request count for sidebar badge."""
    if not current_user.is_authenticated:
        return dict(pending_requests_count=0)
    try:
        count = CloudRequest.query.filter(CloudRequest.status == 'pending').count()
        return dict(pending_requests_count=count)
    except Exception:
        return dict(pending_requests_count=0)

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

def _no_users_exist():
    """Check if no users exist - used to exempt first registration/login from rate limiting."""
    try:
        return User.query.count() == 0
    except Exception:
        return False

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", exempt_when=_no_users_exist)
def login():
    # Check if no users exist - redirect to register
    if User.query.count() == 0:
        flash('No accounts exist. Please register to create the first admin account.')
        return redirect(url_for('register'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            session['notify_tabs_login'] = True
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour", exempt_when=_no_users_exist)
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '')
        if len(username) < 1 or len(username) > 150:
            flash('Username must be 1-150 characters.')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.')
        elif User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(username=username, password_hash=hashed_pw)
            
            db.session.add(new_user)
            db.session.commit()
            
            if User.query.count() == 1:
                new_user.is_admin = True
                db.session.commit()
            
            db.session.add(Settings(user_id=new_user.id))
            db.session.commit()
            
            # Generate recovery codes and show once after registration
            count = 10
            plain_codes = [secrets.token_hex(8) for _ in range(count)]
            for plain in plain_codes:
                rec = RecoveryCode(user_id=new_user.id, code_hash=generate_password_hash(plain, method='pbkdf2:sha256'))
                db.session.add(rec)
            db.session.commit()
            session['show_recovery_codes'] = plain_codes
            
            login_user(new_user)
            session['notify_tabs_login'] = True
            return redirect(url_for('welcome_codes'))
            
    return render_template('login.html', register=True)
    
@app.route('/api/csrf-token')
def csrf_token_route():
    """Return current session CSRF token for fetch/XHR. 401 when not logged in (so other tabs can redirect)."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'csrf_token': generate_csrf()})


@app.route('/logout')
@login_required
def logout():
    logout_user()
    # Notify other tabs so they reload (logout in one tab = others see login)
    return render_template('logout_redirect.html', login_url=url_for('login'))

@app.route('/reset_password', methods=['GET'])
def reset_password_page():
    """Page to reset your password using a one-time recovery code."""
    return render_template('reset_password.html')


@app.route('/welcome_codes')
@login_required
def welcome_codes():
    """Show recovery codes once after registration. Codes are in session; user must click Continue to clear."""
    codes = session.get('show_recovery_codes')
    if not codes:
        return redirect(url_for('dashboard'))
    return render_template('welcome_codes.html', codes=codes)


@app.route('/welcome_codes_done', methods=['GET', 'POST'])
@login_required
def welcome_codes_done():
    """Clear one-time recovery codes from session and go to dashboard."""
    session.pop('show_recovery_codes', None)
    session['notify_tabs_login'] = True
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    s = current_user.settings
    if not s:
        flash("Please complete setup in Settings.", "error")
        return redirect(url_for('settings'))
    # check for new versions every 4 hours (don't spam github)
    now = time.time()
    if UPDATE_CACHE['version'] is None or (now - UPDATE_CACHE['last_check'] > 14400):
        try:
            latest = check_for_updates(VERSION, "https://raw.githubusercontent.com/softerfish/seekandwatch/main/app.py")
            if latest: UPDATE_CACHE['version'] = latest
            UPDATE_CACHE['last_check'] = now
        except Exception: pass

    new_version = None
    if UPDATE_CACHE['version'] and UPDATE_CACHE['version'] != VERSION:
        new_version = UPDATE_CACHE['version']
        
    has_tautulli = bool(s.tautulli_url and s.tautulli_api_key)

    # get plex libraries for display
    plex_libraries = []
    try:
        if s.plex_url and s.plex_token:
            p = PlexServer(s.plex_url, s.plex_token, timeout=2)
            plex_libraries = [sec.title for sec in p.library.sections() if sec.type in ['movie', 'show']]
    except Exception: pass
       
    return render_template('dashboard.html', 
                           settings=s, 
                           new_version=new_version,
                           has_omdb=bool(s.omdb_key if s else False),
                           has_tautulli=has_tautulli,
                           plex_libraries=plex_libraries)
                           
@app.route('/get_local_trending')
@login_required
def get_local_trending():
    from utils import get_tautulli_trending
    m_type = request.args.get('type', 'movie')
    days = request.args.get('days', '30')
    try:
        days = int(days)
        if days < 1: days = 1
        if days > 365: days = 365
    except (ValueError, TypeError):
        days = 30
    items = get_tautulli_trending(m_type, days=days, settings=current_user.settings)
    return jsonify({'status': 'success', 'items': items})

@app.route('/recommend_from_trending')
@login_required
def recommend_from_trending():
    from utils import get_tautulli_trending, normalize_title, RESULTS_CACHE, is_owned_item
    
    m_type = request.args.get('type', 'movie')
    
    # grab trending stuff from tautulli
    trending = get_tautulli_trending(m_type, settings=current_user.settings)
    if not trending:
        flash("No trending data found to base recommendations on.", "error")
        return redirect(url_for('dashboard'))
        
    seed_ids = [str(x['tmdb_id']) for x in trending]
    
    # fetch TMDB recommendations for each trending item (in parallel)
    final_recs = []
    s = current_user.settings
    if not s:
        flash("No settings found.", "error")
        return redirect(url_for('dashboard'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for tid in seed_ids:
            for p in [1, 2]:  # grab 2 pages per item
                url = f"https://api.themoviedb.org/3/{m_type}/{tid}/recommendations?api_key={s.tmdb_key}&language=en-US&page={p}"
                futures.append(executor.submit(requests.get, url))
            
        for f in concurrent.futures.as_completed(futures):
            try:
                data = f.result().json()
                final_recs.extend(data.get('results', []))
            except Exception: pass

    # remove duplicates and filter out stuff we already own
    seen = set()
    unique_recs = []
    
    for r in final_recs:
        if r['id'] not in seen:
            # normalize the year so we don't crash on weird dates
            date = r.get('release_date') or r.get('first_air_date')
            r['year'] = int(date[:4]) if date else 0
            r['media_type'] = m_type
            # Set default runtime (will be fetched in background)
            if not r.get('runtime'):
                r['runtime'] = 0

            # check if already owned (improved duplicate detection)
            if is_owned_item(r, m_type):
                continue
            
            seen.add(r['id'])
            unique_recs.append(r)
            
    random.shuffle(unique_recs)
    
    # Fetch runtime in background for trending recommendations
    def async_fetch_runtime_trending(app_obj, items, key):
        with app_obj.app_context():
            prefetch_runtime_parallel(items, key)
    threading.Thread(target=async_fetch_runtime_trending, args=(app, unique_recs[:40], s.tmdb_key)).start()
    
    # save to cache so "load more" works
    RESULTS_CACHE[current_user.id] = {
        'candidates': unique_recs,
        'next_index': 40
    }
    genres = []
    try:
        g_url = f"https://api.themoviedb.org/3/genre/{m_type}/list?api_key={s.tmdb_key}"
        genres = requests.get(g_url, timeout=10).json().get('genres', [])
    except Exception: pass
            
    return render_template('results.html', movies=unique_recs[:40], 
                         genres=genres, current_genre=None, min_year=0, min_rating=0)
                         
@app.route('/review_history', methods=['POST'])
@login_required
def review_history():
    # scan plex watch history to find stuff for recommendations
    s = current_user.settings
    if not s:
        flash("No settings found.", "error")
        return redirect(url_for('dashboard'))
    
    ignored_libs = [l.strip().lower() for l in request.form.getlist('ignored_libraries')]
    
    media_type = request.form.get('media_type', 'movie')
    manual_query = request.form.get('manual_query')
    limit = max(1, min(500, int(request.form.get('history_limit', 20))))
    
    # save filter preferences to session
    session['critic_filter'] = 'true' if request.form.get('critic_filter') else 'false'
    session['critic_threshold'] = request.form.get('critic_threshold', 70)
    
    candidates = []
    providers = []
    genres = []

    future_mode = request.form.get('future_mode') == 'true'
    include_obscure = request.form.get('include_obscure') == 'true'

    try:
        # manual search
        if manual_query:
            url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={s.tmdb_key}&query={manual_query}"
            res = requests.get(url, timeout=10).json().get('results', [])
            if res:
                item = res[0]
                candidates.append({
                    'title': item.get('title', item.get('name')),
                    'year': (item.get('release_date') or item.get('first_air_date') or '')[:4],
                    'thumb': f"https://image.tmdb.org/t/p/w200{item.get('poster_path')}" if item.get('poster_path') else None,
                    'poster_path': item.get('poster_path')
                })

        # scan actual plex watch history
        elif s.plex_url and s.plex_token:
            plex = PlexServer(s.plex_url, s.plex_token)
            # convert library names to IDs
            ignored_lib_names = [l.strip().lower() for l in request.form.getlist('ignored_libraries')]
            ignored_lib_ids = []
            
            if ignored_lib_names:
                try:
                    for section in plex.library.sections():
                        if section.title.lower() in ignored_lib_names:
                            ignored_lib_ids.append(str(section.key))
                except Exception: pass
            
            # build a map of plex user IDs to their display names
            user_map = {}
            try:
                for acct in plex.systemAccounts():
                    user_map[int(acct.id)] = acct.name
            except Exception: pass

            try:
                account = plex.myPlexAccount()
                for user in account.users():
                    if user.id:
                        user_map[int(user.id)] = user.title
                if account.id:
                    user_map[int(account.id)] = account.username or "Admin"
            except Exception: pass

            ignored = [u.strip().lower() for u in (s.ignored_users or '').split(',')]
            
            cache_key = f"{current_user.id}:{media_type}:{limit}:{','.join(sorted(ignored))}:{','.join(sorted(ignored_lib_ids))}"
            cached_candidates = get_history_cache(cache_key)
            if cached_candidates:
                candidates = cached_candidates
            else:
                history = plex.history(maxresults=5000)
                seen_titles = set()
                lib_type = 'movie' if media_type == 'movie' else 'episode'
                title_stats = {}
                now_ts = datetime.datetime.now().timestamp()
                
                for h in history:
                    if h.type != lib_type:
                        continue

                    # check if user should be ignored
                    user_id = getattr(h, 'accountID', None)
                    user_name = "Unknown"
                    if user_id is not None:
                        user_name = user_map.get(int(user_id), "Unknown")

                    if user_name == "Unknown":
                        if hasattr(h, 'userName') and h.userName:
                            user_name = h.userName
                        elif hasattr(h, 'user') and hasattr(h.user, 'title'):
                            user_name = h.user.title

                    if user_name.lower() in ignored:
                        continue

                    # also skip if the library is ignored
                    if hasattr(h, 'librarySectionID') and h.librarySectionID:
                        if str(h.librarySectionID) in ignored_lib_ids:
                            continue

                    # dedupe TV shows (use show title, not episode)
                    if h.type == 'episode':
                        title = h.grandparentTitle
                    else:
                        title = h.title

                    if not title:
                        if hasattr(h, 'sourceTitle') and h.sourceTitle:
                            title = h.sourceTitle
                        else:
                            title = h.title

                    if not title:
                        continue

                    # track how often and recently this was watched (for scoring)
                    viewed_at = getattr(h, 'viewedAt', None)
                    if isinstance(viewed_at, datetime.datetime):
                        viewed_ts = viewed_at.timestamp()
                    elif isinstance(viewed_at, (int, float)):
                        viewed_ts = float(viewed_at)
                    else:
                        viewed_ts = None

                    stats = title_stats.setdefault(title, {'count': 0, 'last_viewed': 0})
                    stats['count'] += 1
                    if viewed_ts and viewed_ts > stats['last_viewed']:
                        stats['last_viewed'] = viewed_ts

                    # skip if we've seen this show already
                    if title in seen_titles:
                        continue

                    year = h.year if hasattr(h, 'year') else 0

                    # get poster (use show poster for TV)
                    thumb = None
                    try:
                        if h.type == 'episode':
                            thumb = h.grandparentThumb or h.thumb
                        else:
                            thumb = h.thumb
                    except Exception as e:
                        write_log("warning", "App", f"Plex poster/thumb fetch failed ({type(e).__name__})")

                    candidates.append({
                        'title': title,
                        'year': year,
                        'thumb': f"{s.plex_url}{thumb}?X-Plex-Token={s.plex_token}" if thumb else None,
                        'poster_path': None
                    })
                    seen_titles.add(title)

                # score items based on how often and recently they were watched
                for c in candidates:
                    stats = title_stats.get(c['title'], {})
                    count = stats.get('count', 1)
                    last_viewed = stats.get('last_viewed', 0)
                    days_ago = (now_ts - last_viewed) / 86400 if last_viewed else 365
                    recency = 1 / (1 + max(days_ago, 0))
                    c['score'] = (count * 0.7) + (recency * 0.3)

                candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
                candidates = candidates[:limit]
                set_history_cache(cache_key, candidates)

    except Exception as e:
        write_log("error", "Review History", f"Scan failed: {str(e)}")
        flash("Scan failed. Please check your Plex connection and try again.", "error")
        return redirect(url_for('dashboard'))

    # fetch providers and genres in parallel
    def _fetch_providers():
        try:
            reg = s.tmdb_region.split(',')[0] if s.tmdb_region else 'US'
            p_url = f"https://api.themoviedb.org/3/watch/providers/{media_type}?api_key={s.tmdb_key}&watch_region={reg}"
            p_data = requests.get(p_url, timeout=10).json().get('results', [])
            providers[:] = sorted(p_data, key=lambda x: x.get('display_priority', 999))[:30]
        except Exception as e:
            write_log("warning", "Review History", f"Failed to fetch providers: {str(e)}")
    def _fetch_genres():
        try:
            g_url = f"https://api.themoviedb.org/3/genre/{media_type}/list?api_key={s.tmdb_key}"
            genres[:] = requests.get(g_url, timeout=10).json().get('genres', [])
        except Exception as e:
            write_log("warning", "Review History", f"Failed to fetch genres: {str(e)}")
    t_prov = threading.Thread(target=_fetch_providers)
    t_gen = threading.Thread(target=_fetch_genres)
    t_prov.start()
    t_gen.start()
    t_prov.join()
    t_gen.join()

    return render_template('review.html', 
                           movies=candidates, 
                           media_type=media_type,
                           providers=providers,
                           genres=genres,
                           future_mode=future_mode,
                           include_obscure=include_obscure)
                           
@app.route('/generate', methods=['POST'])
@login_required
def generate():
    s = current_user.settings
    if not s:
        flash("No settings found. Please complete Settings (e.g. TMDB API key) first.", "error")
        return redirect(url_for('dashboard'))
    if not (s.tmdb_key or '').strip():
        flash("TMDB API key is required for recommendations. Add it in Settings > APIs & Connections.", "error")
        return redirect(url_for('dashboard'))
    
    # "I'm feeling lucky" mode - just grab random popular stuff
    if request.form.get('lucky_mode') == 'true':
        raw_candidates = handle_lucky_mode(s)
        if not raw_candidates:
             flash("Could not find a lucky pick!", "error")
             return redirect(url_for('dashboard'))
        
        lucky_result = []
        # keep fetching pages until we have 5 unowned items
        page = 1
        max_pages = 10
        while len(lucky_result) < 5 and page <= max_pages:
            # if we've exhausted the current candidates, fetch more
            if page > 1 or len(raw_candidates) == 0:
                try:
                    random_genre = random.choice([28, 35, 18, 878, 27, 53])
                    url = f"https://api.themoviedb.org/3/discover/movie?api_key={s.tmdb_key}&with_genres={random_genre}&sort_by=popularity.desc&page={page}"
                    data = requests.get(url, timeout=10).json().get('results', [])
                    raw_candidates = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in data]
                    random.shuffle(raw_candidates)
                except Exception as e:
                    write_log("warning", "App", f"Recommend-from-trending page fetch failed ({type(e).__name__})")
                    break
            
            for item in raw_candidates:
                if len(lucky_result) >= 5:
                    break
                
                # Set default runtime (will be fetched in background)
                if not item.get('runtime'):
                    item['runtime'] = 0
                
                # check if already owned (improved duplicate detection)
                if is_owned_item(item, 'movie'):
                    continue
                
                lucky_result.append(item)
            
            page += 1
            
        if not lucky_result:
             flash("You own all the lucky picks! Try again.", "error")
             return redirect(url_for('dashboard'))

        genres = []
        try:
            g_url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={s.tmdb_key}"
            genres = requests.get(g_url, timeout=10).json().get('genres', [])
        except Exception: pass

        # Fetch runtime in background for lucky results
        def async_fetch_runtime_lucky(app_obj, items, key):
            with app_obj.app_context():
                prefetch_runtime_parallel(items, key)
        threading.Thread(target=async_fetch_runtime_lucky, args=(app, lucky_result, s.tmdb_key)).start()

        # Ensure every item has 'title' for frontend (lucky is movies-only but keep consistent)
        for item in lucky_result:
            if not item.get('title') and item.get('name'):
                item['title'] = item['name']

        RESULTS_CACHE[current_user.id] = {'candidates': lucky_result, 'next_index': len(lucky_result)}
        return render_template('results.html', 
                               movies=lucky_result, 
                               min_year=0, 
                               min_rating=0, 
                               genres=genres, 
                               current_genre=None, 
                               use_critic_filter='false',
                               is_lucky=True)

    # standard recommendation mode
    media_type = request.form.get('media_type')
    selected_titles = request.form.getlist('selected_movies')
    
    session['media_type'] = media_type
    session['selected_titles'] = selected_titles
    session['genre_filter'] = request.form.getlist('genre_filter')
    session['keywords'] = request.form.get('keywords', '')
    
    try: session['min_year'] = max(0, min(2100, int(request.form.get('min_year', 0))))
    except Exception: session['min_year'] = 0
    try: session['min_rating'] = float(request.form.get('min_rating', 0))
    except Exception: session['min_rating'] = 0
    
    if not selected_titles:
        flash('Please select at least one item.', 'error')
        return redirect(url_for('dashboard'))

    blocked = set([b.title for b in Blocklist.query.filter_by(user_id=current_user.id).all()])

    recommendations = []
    seen_ids = set()
    seed_ids = []

    def resolve_title_to_id(title):
        try:
            search_url = f"https://api.themoviedb.org/3/search/{media_type}?api_key={s.tmdb_key}&query={title}"
            r = requests.get(search_url, timeout=10).json()
            if r.get('results'):
                return r['results'][0]['id']
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        resolved = list(executor.map(resolve_title_to_id, selected_titles))
    seed_ids = [tid for tid in resolved if tid is not None]
    # Cap seeds to avoid long timeouts (TMDB calls scale with seed count)
    max_seeds = 10
    if len(seed_ids) > max_seeds:
        write_log("info", "Generate", f"Capping seeds from {len(seed_ids)} to {max_seeds} to reduce timeout risk.")
        seed_ids = seed_ids[:max_seeds]
    if not seed_ids:
        write_log("warning", "Generate", "No TMDB IDs resolved from selected titles; check TMDB API key and titles.")
        flash("Could not find any of the selected titles on TMDB. Check your TMDB API key in Settings.", "error")
        return redirect(url_for('dashboard'))

    future_mode = request.form.get('future_mode') == 'true'
    include_obscure = request.form.get('include_obscure') == 'true'
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    def fetch_seed_results(tmdb_id):
        # Thread workers need Flask app context for write_log and any DB-backed cache
        with app.app_context():
            return _fetch_seed_results_impl(tmdb_id)

    def _fetch_seed_results_impl(tmdb_id):
        # keep cache key simple - we'll shuffle results after combining all seeds
        cache_key = f"{media_type}:{tmdb_id}:{'future' if future_mode else 'recs'}:{today}"
        cached = get_tmdb_rec_cache(cache_key)
        if cached:
            return cached

        try:
            if future_mode:
                details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}"
                details = requests.get(details_url, timeout=10).json()
                genres = [str(g['id']) for g in details.get('genres', [])[:3]]
                genre_str = "|".join(genres)

                disc_url = f"https://api.themoviedb.org/3/discover/{media_type}"
                params = {
                    'api_key': s.tmdb_key,
                    'language': 'en-US',
                    'sort_by': 'popularity.desc',
                    'with_genres': genre_str,
                    'with_original_language': 'en',
                    'popularity.gte': 5,
                    'page': 1
                }

                if media_type == 'movie':
                    params['primary_release_date.gte'] = today
                    params['with_release_type'] = '3|2'
                    params['region'] = 'US'
                else:
                    params['first_air_date.gte'] = today
                    params['include_null_first_air_dates'] = 'false'
                    params['with_origin_country'] = 'US'

                data = requests.get(disc_url, params=params).json()
                results = data.get('results', [])
            else:
                # fetch 2 pages per seed; skip TMDB error responses (e.g. status_code in body)
                results = []
                for page_num in range(1, 3):
                    rec_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/recommendations?api_key={s.tmdb_key}&language=en-US&page={page_num}"
                    page_data = requests.get(rec_url, timeout=10).json()
                    if page_data.get('status_code'):
                        write_log("warning", "Generate", f"TMDB recommendations error for {media_type} {tmdb_id}: {page_data.get('status_message', page_data.get('status_code'))}")
                        continue  # TMDB error response, skip this page
                    results.extend(page_data.get('results', []))

                # recommendations often empty for niche titles; fall back to similar (genre/keyword-based)
                if not results:
                    similar_key = f"{media_type}:{tmdb_id}:similar:{today}"
                    cached_similar = get_tmdb_rec_cache(similar_key)
                    if cached_similar:
                        results = cached_similar
                    else:
                        for page_num in range(1, 3):
                            sim_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/similar?api_key={s.tmdb_key}&language=en-US&page={page_num}"
                            sim_data = requests.get(sim_url, timeout=10).json()
                            if sim_data.get('status_code'):
                                write_log("warning", "Generate", f"TMDB similar error for {media_type} {tmdb_id}: {sim_data.get('status_message', sim_data.get('status_code'))}")
                                continue
                            results.extend(sim_data.get('results', []))
                        if results:
                            set_tmdb_rec_cache(similar_key, results)

                # still empty: discover by this title's genres so we always get something per seed
                if not results:
                    disc_key = f"{media_type}:{tmdb_id}:discover:{today}"
                    cached_disc = get_tmdb_rec_cache(disc_key)
                    if cached_disc:
                        results = cached_disc
                    else:
                        try:
                            details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}"
                            details = requests.get(details_url, timeout=10).json()
                            if not details.get('status_code'):
                                genres = details.get('genres', [])[:3]
                                if genres:
                                    genre_str = "|".join(str(g['id']) for g in genres)
                                    disc_url = f"https://api.themoviedb.org/3/discover/{media_type}"
                                    params = {
                                        'api_key': s.tmdb_key,
                                        'language': 'en-US',
                                        'sort_by': 'popularity.desc',
                                        'with_genres': genre_str,
                                        'page': 1
                                    }
                                    if not include_obscure:
                                        params['with_original_language'] = 'en'
                                    data = requests.get(disc_url, params=params, timeout=10).json()
                                    if not data.get('status_code'):
                                        results = data.get('results', [])
                                        if results:
                                            set_tmdb_rec_cache(disc_key, results)
                        except Exception as disc_e:
                            write_log("warning", "Generate", f"Discover fallback for {tmdb_id} failed: {disc_e}")

            if results:
                set_tmdb_rec_cache(cache_key, results)
            return results
        except Exception as e:
            write_log("warning", "Generate", f"Fetch seed {tmdb_id} failed: {type(e).__name__}: {e}")
            return []

    # fetch recommendations from all seeds, filtering owned items as we go
    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for results in executor.map(fetch_seed_results, seed_ids):
            all_results.extend(results)
    raw_count = len(all_results)
    used_last_resort = False

    # last-resort: if every seed returned nothing (e.g. cache was empty, API flakiness), get popular discover
    if raw_count == 0:
        try:
            disc_url = f"https://api.themoviedb.org/3/discover/{media_type}"
            base_params = {'api_key': s.tmdb_key, 'language': 'en-US', 'sort_by': 'popularity.desc'}
            if not include_obscure:
                base_params['with_original_language'] = 'en'
            all_results = []
            # random starting page (1–10), fetch 6 pages (~120 results) so we get plenty after filtering
            start_page = random.randint(1, 10)
            for page_num in range(start_page, start_page + 6):
                params = dict(base_params, page=page_num)
                data = requests.get(disc_url, params=params, timeout=10).json()
                if data.get('status_code'):
                    break
                all_results.extend(data.get('results', []))
            if all_results:
                raw_count = len(all_results)
                used_last_resort = True
        except Exception as e:
            write_log("warning", "Generate", f"Last-resort discover failed: {e}")

    if used_last_resort:
        write_log("info", "Generate", f"TMDB returned {raw_count} raw recommendations (last-resort discover; seeds had 0).")
    else:
        write_log("info", "Generate", f"TMDB returned {raw_count} raw recommendations from {len(seed_ids)} seeds.")
    
    # shuffle all results once before processing to get variety
    random.shuffle(all_results)
    
    # vote threshold: 10 so niche/seasonal titles still pass; use 20 only when we have plenty of raw recs
    vote_min = 10 if raw_count < 100 else 20
    # now filter and process
    for item in all_results:
        if item['id'] in seen_ids: continue
        
        # filter out low-quality stuff (unless user wants obscure content)
        if not include_obscure:
            # only english-language content in standard mode
            if item.get('original_language') != 'en': continue
            
            # skip stuff with very few votes (probably not great)
            if not future_mode and item.get('vote_count', 0) < vote_min: continue
        
        item['media_type'] = media_type
        date = item.get('release_date') or item.get('first_air_date')
        item['year'] = int(date[:4]) if date else 0
        item['score'] = score_recommendation(item)
        # Set default runtime (will be fetched in background)
        if not item.get('runtime'):
            item['runtime'] = 0 if media_type == 'tv' else 0  # Start with 0, will be updated when fetched
        
        if item.get('title', item.get('name')) in blocked: continue
        
        # check if already owned (improved duplicate detection)
        is_owned = is_owned_item(item, media_type)
        if is_owned:
            continue
        
        recommendations.append(item)
        seen_ids.add(item['id'])
    if raw_count and not recommendations:
        write_log("warning", "Generate", f"All {raw_count} raw recs were filtered out (lang/vote/blocked/owned). Try enabling International & Obscure.")
    # sort by score (popularity + votes)
    recommendations.sort(key=lambda x: x.get('score', 0), reverse=True)
    if include_obscure:
        # if user wants diverse/obscure stuff, mix it up by genre and decade
        def bucket_fn(item):
            genre_ids = item.get('genre_ids') or []
            if genre_ids:
                return genre_ids[0]
            year = item.get('year', 0)
            return year // 10
        recommendations = diverse_sample(recommendations, len(recommendations), bucket_fn=bucket_fn)
    
    # one more dedupe pass just to be safe
    unique_recs = []
    seen_final = set()
    for item in recommendations:
        if item['id'] not in seen_final:
            unique_recs.append(item)
            seen_final.add(item['id'])
    
    # shuffle results so they're different each time
    random.shuffle(unique_recs)
    
    RESULTS_CACHE[current_user.id] = {
        'candidates': unique_recs,
        'next_index': 0,
        'ts': int(time.time()),
        'sorted': False  # mark as not sorted since we shuffled
    }
    save_results_cache()
    
    # apply filters (use form values; session was set earlier)
    min_year, min_rating, genre_filter, critic_enabled, threshold = get_session_filters()
    # "All genres" selected (long list) = no genre filter
    if isinstance(genre_filter, list) and len(genre_filter) >= 15:
        genre_filter = None
    rating_filter = request.form.getlist('rating_filter')
    session['rating_filter'] = rating_filter
    raw_keywords = session.get('keywords', '')
    target_keywords = [k.strip() for k in raw_keywords.split('|') if k.strip()]

    # use shuffled list for display, not sorted recommendations
    prefetch_ratings_parallel(unique_recs[:60], s.tmdb_key)
    # Fetch runtime in background to not block initial render
    def async_fetch_runtime(app_obj, items, key):
        with app_obj.app_context():
            prefetch_runtime_parallel(items, key)
    threading.Thread(target=async_fetch_runtime, args=(app, unique_recs[:60], s.tmdb_key)).start()
    
    if s.omdb_key:
        prefetch_omdb_parallel(unique_recs[:80], s.omdb_key)

    if target_keywords:
        prefetch_keywords_parallel(unique_recs, s.tmdb_key)
    else:
        def async_prefetch(app_obj, items, key):
            with app_obj.app_context():
                prefetch_keywords_parallel(items, key)
        threading.Thread(target=async_prefetch, args=(app, unique_recs, s.tmdb_key)).start()

    final_list = []
    idx = 0
    
    # use shuffled unique_recs instead of sorted recommendations
    while len(final_list) < 40 and idx < len(unique_recs):
        item = unique_recs[idx]
        idx += 1
        
        if item['year'] < min_year: continue
        # skip rating check in future mode (upcoming movies have 0 rating)
        if not future_mode and item.get('vote_average', 0) < min_rating: continue
        
        # runtime filter (if set in session)
        max_runtime = session.get('max_runtime', 9999)
        if max_runtime and max_runtime < 9999:
            item_runtime = item.get('runtime', 9999)
            if item_runtime > max_runtime: continue
        
        if rating_filter:
            c_rate = item.get('content_rating', 'NR')
            if c_rate not in rating_filter: continue
        
        if genre_filter and genre_filter != 'all':
            try:
                allowed_ids = [int(g) for g in genre_filter] if isinstance(genre_filter, list) else [int(genre_filter)]
                item_genres = item.get('genre_ids') or []
                if item_genres and not any(gid in allowed_ids for gid in item_genres):
                    continue
            except Exception:
                pass
            
        # check if it matches the keyword filter
        if target_keywords:
            if not item_matches_keywords(item, target_keywords): continue

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
            # Only exclude by critic when we have an actual RT score below threshold; missing score = include
            rt = item.get('rt_score') or 0
            if critic_enabled and rt > 0 and rt < threshold:
                continue

        final_list.append(item)

    if media_type == 'tv':
        prefetch_tv_states_parallel(final_list, s.tmdb_key)

    RESULTS_CACHE[current_user.id]['next_index'] = idx
    save_results_cache()

    # ensure every item has a 'title' key (TMDB TV uses 'name')
    for item in final_list:
        if not item.get('title') and item.get('name'):
            item['title'] = item['name']

    if not final_list:
        write_log("warning", "Generate", f"No results after filters (had {len(unique_recs)} recs, seeds={len(seed_ids)}). Try lowering min rating/year or enabling International & Obscure.")
        if raw_count == 0:
            flash("TMDB returned no recommendations for your selected titles. Try different titles or enable International & Obscure.", "error")
        else:
            flash("No recommendations matched your filters. Try lowering min rating/year or enabling International & Obscure.", "error")
        return redirect(url_for('dashboard'))

    g_url = f"https://api.themoviedb.org/3/genre/{media_type}/list?api_key={s.tmdb_key}"
    try: genres = requests.get(g_url, timeout=10).json().get('genres', [])
    except Exception as e:
        write_log("warning", "Generate", f"Failed to fetch genres: {str(e)}")
        genres = []

    return render_template('results.html', 
                           movies=final_list, 
                           genres=genres,
                           current_genre=genre_filter,
                           min_year=min_year,
                           min_rating=min_rating,
                           use_critic_filter='true' if critic_enabled else 'false',
                           is_lucky=False)
                           
@app.route('/reset_alias_db')
@login_required
def reset_alias_db():
    # wipe alias DB to fix owned items showing up
    try:
        db.session.query(TmdbAlias).delete()
        s = current_user.settings
        s.last_alias_scan = 0
        db.session.commit()
        return "<h1>Alias DB Wiped.</h1><p>The scanner will now restart from scratch. Please wait 10 minutes and check logs.</p><a href='" + url_for('dashboard') + "'>Back</a>"
    except Exception as e:
        write_log("error", "Wipe Database", f"Failed to wipe alias database: {str(e)}")
        return "<h1>Error</h1><p>An error occurred while wiping the alias database.</p><a href='" + url_for('dashboard') + "'>Back</a>"

def _get_plex_collection_titles(settings):
    """Return set of collection titles that exist in Plex (so we can remove app jobs for deleted collections). None on failure."""
    if not settings or not settings.plex_url or not settings.plex_token:
        return None
    try:
        plex = PlexServer(settings.plex_url, settings.plex_token, timeout=5)
        titles = set()
        for section in plex.library.sections():
            if section.type in ('movie', 'show'):
                for col in section.collections():
                    titles.add(col.title)
        return titles
    except Exception:
        return None

@app.route('/playlists')
@login_required
def playlists():
    s = current_user.settings
    current_time = s.schedule_time if s and s.schedule_time else "04:00"

    # Two-way delete: if collection was deleted in Plex, remove the sync from app
    plex_titles = _get_plex_collection_titles(s)
    if plex_titles is not None:
        for sch in list(CollectionSchedule.query.all()):
            title = None
            if sch.preset_key.startswith('custom_') and sch.configuration:
                try:
                    cfg = json.loads(sch.configuration)
                    title = cfg.get('title')
                except Exception:
                    pass
            else:
                preset = PLAYLIST_PRESETS.get(sch.preset_key, {})
                title = preset.get('title')
            if title and title not in plex_titles:
                CollectionSchedule.query.filter_by(preset_key=sch.preset_key).delete()
        db.session.commit()

    schedules = {}
    sync_modes = {}
    visibility = {}  # preset_key -> { home, library, friends }
    for sch in CollectionSchedule.query.all():
        schedules[sch.preset_key] = sch.frequency
        if sch.configuration:
            try:
                config = json.loads(sch.configuration)
                sync_modes[sch.preset_key] = config.get('sync_mode', 'append')
                visibility[sch.preset_key] = {
                    'home': config.get('visibility_home', True),
                    'library': config.get('visibility_library', False),
                    'friends': config.get('visibility_friends', False)
                }
            except Exception:
                sync_modes[sch.preset_key] = 'append'
                visibility[sch.preset_key] = {'home': True, 'library': False, 'friends': False}

    custom_presets = {}
    for sch in CollectionSchedule.query.filter(CollectionSchedule.preset_key.like('custom_%')).all():
        if sch.configuration:
            try:
                config = json.loads(sch.configuration)
                custom_presets[sch.preset_key] = {
                    'title': config.get('title', 'Untitled'),
                    'description': config.get('description', 'Custom Builder Collection'),
                    'media_type': config.get('media_type', 'movie'),
                    'icon': config.get('icon', '🛠️'),
                    'sync_mode': config.get('sync_mode', 'append'),
                    'visibility_home': config.get('visibility_home', True),
                    'visibility_library': config.get('visibility_library', False),
                    'visibility_friends': config.get('visibility_friends', False)
                }
            except Exception:
                pass

    return render_template('playlists.html', 
                           presets=PLAYLIST_PRESETS, 
                           schedules=schedules, 
                           sync_modes=sync_modes,
                           visibility=visibility,
                           custom_presets=custom_presets,
                           schedule_time=current_time)
                           
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    s = current_user.settings
    if request.args.get('restored'):
        flash('Backup restored. If API keys or other settings are missing, restart the app (e.g. restart the Docker container) so all data loads from the backup.', 'success')

    if request.method == 'POST':
        form_section = request.form.get('form_section', '').strip()
        # Partial updates: only update fields for the submitted section (one form per action)
        update_apis = form_section == 'apis' or not form_section
        update_scanners = form_section == 'scanners' or not form_section
        update_system = form_section == 'system' or not form_section

        if update_apis:
            url_fields = ['plex_url', 'overseerr_url', 'tautulli_url', 'radarr_url', 'sonarr_url']
            for field in url_fields:
                if field in request.form:
                    val = request.form.get(field)
                    if val and not _valid_url(val):
                        return jsonify({'status': 'error', 'message': f'Invalid URL in {field.replace("_", " ")}. Use http:// or https:// only.'}), 400
            # Only update API fields that are present (allows multiple small forms in APIs tab)
            # Keys/tokens: if user sent a non-empty value, always save it. Else if *_unchanged keep existing; else don't overwrite with empty.
            def _apply_key(field_name, unchanged_name, attr_name):
                if field_name not in request.form:
                    return
                v = (request.form.get(field_name) or '').strip()
                if v:
                    setattr(s, attr_name, v)
                elif unchanged_name in request.form:
                    pass
                elif getattr(s, attr_name, None):
                    pass
                else:
                    setattr(s, attr_name, None)
            if 'plex_url' in request.form:
                s.plex_url = request.form.get('plex_url')
            _apply_key('plex_token', 'plex_token_unchanged', 'plex_token')
            _apply_key('tmdb_key', 'tmdb_key_unchanged', 'tmdb_key')
            if 'tmdb_region' in request.form:
                s.tmdb_region = request.form.get('tmdb_region')
            _apply_key('omdb_key', 'omdb_key_unchanged', 'omdb_key')
            if 'overseerr_url' in request.form:
                s.overseerr_url = request.form.get('overseerr_url')
            _apply_key('overseerr_api_key', 'overseerr_api_key_unchanged', 'overseerr_api_key')
            if 'tautulli_url' in request.form:
                s.tautulli_url = request.form.get('tautulli_url')
            _apply_key('tautulli_api_key', 'tautulli_api_key_unchanged', 'tautulli_api_key')
            if 'radarr_url' in request.form:
                s.radarr_url = request.form.get('radarr_url')
            _apply_key('radarr_api_key', 'radarr_api_key_unchanged', 'radarr_api_key')
            if 'sonarr_url' in request.form:
                s.sonarr_url = request.form.get('sonarr_url')
            _apply_key('sonarr_api_key', 'sonarr_api_key_unchanged', 'sonarr_api_key')
            if 'plex_url' in request.form or 'plex_token' in request.form:
                s.ignored_users = ','.join(request.form.getlist('ignored_plex_users'))
            try:
                commit_with_retry()
            except Exception as e:
                db.session.rollback()
                write_log("error", "Settings", f"Save failed: {type(e).__name__}")
                return jsonify({'status': 'error', 'message': 'Database save failed. Please try again.'}), 500

        if update_scanners:
            try:
                s.keyword_cache_size = max(100, min(50000, int(request.form.get('keyword_cache_size', 3000))))
            except (TypeError, ValueError):
                s.keyword_cache_size = 3000
            try:
                s.runtime_cache_size = max(100, min(50000, int(request.form.get('runtime_cache_size', 3000))))
            except (TypeError, ValueError):
                s.runtime_cache_size = 3000
            if 'max_log_size' in request.form:
                try:
                    s.max_log_size = max(1, min(100, int(request.form.get('max_log_size', 5))))
                except (TypeError, ValueError):
                    s.max_log_size = 5
            if 'scanner_log_size' in request.form:
                try:
                    s.scanner_log_size = max(1, min(100, int(request.form.get('scanner_log_size', 10))))
                except (TypeError, ValueError):
                    s.scanner_log_size = 10
            if 'ignored_libraries' in request.form or request.form.getlist('ignored_libraries'):
                ignored_libs = request.form.getlist('ignored_libraries')
                s.ignored_libraries = ",".join(ignored_libs)
            try:
                commit_with_retry()
            except Exception as e:
                db.session.rollback()
                write_log("error", "Settings", f"Save failed: {type(e).__name__}")
                return jsonify({'status': 'error', 'message': 'Database save failed. Please try again.'}), 500

        if update_system:
            try:
                s.backup_interval = max(1, min(168, int(request.form.get('backup_interval', 2))))
            except (TypeError, ValueError):
                s.backup_interval = 2
            try:
                s.backup_retention = max(1, min(365, int(request.form.get('backup_retention', 7))))
            except (TypeError, ValueError):
                s.backup_retention = 7
            if 'cloud_sync_owned_enabled' in request.form:
                s.cloud_sync_owned_enabled = True
            elif form_section in ('system', ''):
                s.cloud_sync_owned_enabled = False
            try:
                commit_with_retry()
            except Exception as e:
                db.session.rollback()
                write_log("error", "Settings", f"Save failed: {type(e).__name__}")
                return jsonify({'status': 'error', 'message': 'Database save failed. Please try again.'}), 500

        return jsonify({'status': 'success', 'message': 'Settings saved successfully.', 'msg': 'Settings saved successfully.'})

    # get plex users for ignore list
    plex_users = []
    try:
        if s.plex_url and s.plex_token:
            p = PlexServer(s.plex_url, s.plex_token, timeout=3)
            # Try MyPlex first
            try:
                account = p.myPlexAccount()
                plex_users = [u.title for u in account.users()]
                if account.username: plex_users.insert(0, account.username)
            except Exception as e:
                write_log("warning", "Settings", f"Plex account users fetch failed ({type(e).__name__})")
                # Fallback: Try to guess from connected clients/system
                try:
                    plex_users.append(p.myPlexAccount().username)
                except Exception:
                    pass
    except Exception:
        pass
    
    current_ignored = (s.ignored_users or '').split(',')

    # get plex libraries
    plex_libraries = []
    try:
        if s.plex_url and s.plex_token:
            p = PlexServer(s.plex_url, s.plex_token, timeout=3)
            plex_libraries = [sec.title for sec in p.library.sections() if sec.type in ['movie', 'show']]
    except Exception as e:
        err_str = str(e)
        if "Connection refused" in err_str or "Max retries exceeded" in err_str or "plex.direct" in err_str:
            write_log("warning", "Settings", f"Plex libraries unreachable (connection refused). Use Plex Local URL like http://YOUR_IP:32400 in Settings → APIs if .plex.direct fails. ({err_str[:100]})")
        else:
            write_log("warning", "Settings", f"Failed to fetch Plex libraries: {err_str}")
    
    current_ignored_libs = (s.ignored_libraries or '').split(',')

    # only admins see system logs (avoid leaking paths/errors to other users)
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(50).all() if current_user.is_admin else []
    
    # last Plex library sync (TMDB index)
    cache_age = "Never"
    if s and (s.last_alias_scan or 0) > 0:
        try:
            cache_age = datetime.datetime.fromtimestamp(s.last_alias_scan).strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass

    try: keyword_count = TmdbKeywordCache.query.count()
    except Exception: keyword_count = 0
    
    try: runtime_count = TmdbRuntimeCache.query.count()
    except Exception: runtime_count = 0
    
    # Extract server IP/hostname from request for auto-fill (validate against allowlist; Host header can be spoofed)
    server_host = None
    try:
        host_header = request.host
        if ':' in host_header:
            server_host = host_header.split(':')[0].strip().lower()
        else:
            server_host = (host_header or "").strip().lower()
        allowed_hosts = getattr(config, 'PLEX_URL_SUGGESTION_ALLOWED_HOSTS', None) or ['localhost', '127.0.0.1', '0.0.0.0']
        if server_host and server_host not in [h.lower() for h in allowed_hosts]:
            server_host = None
        if server_host:
            # Don't use localhost/127.0.0.1 - try to get actual IP for the suggestion
            if server_host in ['localhost', '127.0.0.1', '0.0.0.0']:
                # Try to get the actual server IP from the request
                forwarded_for = request.headers.get('X-Forwarded-For')
                if forwarded_for:
                    server_host = forwarded_for.split(',')[0].strip()
                elif request.remote_addr and request.remote_addr not in ['127.0.0.1', '::1']:
                    server_host = request.remote_addr
                else:
                    # Fallback: try to detect from socket
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.connect(("8.8.8.8", 80))
                        server_host = sock.getsockname()[0]
                        sock.close()
                    except OSError as e:
                        write_log("warning", "Settings", f"Socket bind failed ({type(e).__name__})")
                        server_host = None
    except Exception as e:
        write_log("warning", "Settings", f"Plex base URL detection failed ({type(e).__name__})")
        server_host = None

    return render_template('settings.html', 
                           settings=s, 
                           plex_users=plex_users, 
                           current_ignored=current_ignored,
                           plex_libraries=plex_libraries,
                           current_ignored_libs=current_ignored_libs,
                           logs=logs, 
                           cache_age=cache_age,
                           keyword_count=keyword_count,
                           runtime_count=runtime_count,
                           server_host=server_host)

@app.route('/logs_page')
@login_required
@admin_required
def logs_page():
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(200).all()
    s = current_user.settings
    
    # Count errors for summary
    error_count = SystemLog.query.filter(SystemLog.level.in_(['error', 'ERROR'])).count()
    recent_error_count = SystemLog.query.filter(
        SystemLog.level.in_(['error', 'ERROR']),
        SystemLog.timestamp >= datetime.datetime.now() - timedelta(days=7)
    ).count()
    
    return render_template('logs.html', logs=logs, settings=s, 
                         error_count=error_count, recent_error_count=recent_error_count)

@app.route('/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    user = User.query.get(current_user.id)
    Settings.query.filter_by(user_id=current_user.id).delete()
    Blocklist.query.filter_by(user_id=current_user.id).delete()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return render_template('logout_redirect.html', login_url=url_for('login'))

@app.route('/builder')
@login_required
def builder():
    s = current_user.settings
    try:
        g_url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={s.tmdb_key}"
        genres = requests.get(g_url, timeout=10).json().get('genres', [])
    except Exception: genres = []
    return render_template('builder.html', genres=genres)

@app.route('/manage_blocklist')
@login_required
def manage_blocklist():
    blocks = Blocklist.query.filter_by(user_id=current_user.id).all()
    return render_template('blocklist.html', blocks=blocks)

@app.route('/kometa')
@login_required
def kometa():
    s = current_user.settings
    return render_template('kometa.html', settings=s)

@app.route('/media')
@login_required
def media():
    s = current_user.settings
    return render_template('media.html', settings=s)

@app.route('/calendar')
@login_required
def calendar_page():
    s = current_user.settings
    return render_template('calendar.html', settings=s)

@app.route('/support')
@login_required
def support_us():
    return render_template('support.html')

# background scheduler - runs collections, cache refreshes, etc on a schedule

def scheduled_tasks():
    with app.app_context():
        # prune backups at 4am
        if datetime.datetime.now().hour == 4 and datetime.datetime.now().minute == 0:
            prune_backups()
            
        # cache refresh + collection schedule (no request context; use config user or first row)
        if getattr(config, 'SCHEDULER_USER_ID', None) is not None:
            s = Settings.query.filter_by(user_id=config.SCHEDULER_USER_ID).first()
        else:
            s = Settings.query.first()
        if not s:
            return
        
        # Plex library sync (TMDB index) on interval (0 = disabled). Only run after at least one manual sync.
        last_sync = s.last_alias_scan or 0
        interval_hours = (s.cache_interval or 0)
        if interval_hours > 0 and last_sync > 0 and (time.time() - last_sync) >= interval_hours * 3600:
            if not is_system_locked():
                print("Scheduler: Starting Plex library sync...")
                sync_plex_library(app)

        # check if any collections need to run
        try:
            target_hour, target_minute = map(int, (s.schedule_time or "04:00").split(':'))
        except (ValueError, TypeError, AttributeError):
            target_hour, target_minute = 4, 0
            
        now = datetime.datetime.now()

        for sch in CollectionSchedule.query.all():
            if sch.frequency == 'manual': continue
            
            should_run = False
            last = sch.last_run
            
            # daily collections run once per day after the target time
            if sch.frequency == 'daily':
                run_today = False
                if last and last.date() == now.date():
                    run_today = True
                
                past_target_time = False
                if now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute):
                    past_target_time = True
                
                if not run_today and past_target_time:
                    should_run = True

            # weekly
            elif sch.frequency == 'weekly':
                if not last:
                    should_run = True
                else:
                    delta = now - last
                    if delta.days >= 7: should_run = True
                
            if should_run:
                print(f"Scheduler: Running collection {sch.preset_key}...")
                
                if sch.preset_key.startswith('custom_'):
                     preset_data = json.loads(sch.configuration)
                else:
                     preset_data = PLAYLIST_PRESETS.get(sch.preset_key, {}).copy()
                     
                     # merge user overrides
                     if sch.configuration:
                         try:
                             user_config = json.loads(sch.configuration)
                             preset_data.update(user_config)
                         except Exception: pass
                
                if preset_data:
                    success, msg = run_collection_logic(s, preset_data, sch.preset_key, app_obj=app)
                    if success:
                        sch.last_run = now
                        db.session.commit()

        # background Radarr/Sonarr scanner
        if s.radarr_sonarr_scanner_enabled:
            last = s.last_radarr_sonarr_scan or 0
            now_ts = int(time.time())
            interval_sec = (s.radarr_sonarr_scanner_interval or 24) * 3600  # convert hours to seconds
            
            if now_ts - last >= interval_sec:
                if not is_system_locked():
                    print("Scheduler: Starting Radarr/Sonarr Cache Refresh...")
                    threading.Thread(target=refresh_radarr_sonarr_cache, args=(app,)).start()

        # Cloud polling: fetch approved requests from SeekAndWatch Cloud
        if getattr(s, 'cloud_enabled', False) and getattr(s, 'cloud_api_key', None) and getattr(s, 'cloud_sync_owned_enabled', True):
            try:
                from cloud_worker import process_cloud_queue
                process_cloud_queue()
            except Exception as e:
                print(f"Cloud poll error: {e}")

scheduler.add_job(id='master_task', func=scheduled_tasks, trigger='interval', minutes=1)

# Import API blueprint - must be after app creation
try:
    from api import api_bp
    app.register_blueprint(api_bp)
    import api
    api.limiter = limiter
except ImportError as e:
    import traceback
    print(f"error: failed to import api module: {e}")
    traceback.print_exc()
    print(f"Current working directory: {os.getcwd()}")
    print(f"Files in current directory: {os.listdir('.')}")
    raise
except Exception as e:
    import traceback
    print(f"error: api blueprint registration failed: {e}")
    traceback.print_exc()
    raise


# global error handlers so users see a friendly page instead of a crash
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='Page not found.'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', message='Something went wrong. Please try again or check the logs.'), 500


# lightweight health endpoint for Docker/orchestration (no auth, no heavy work)
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': VERSION}), 200


def _add_cors(resp):
    """Allow browser (web page) to POST from another origin (e.g. seekandwatch.com)."""
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Webhook-Secret'
    return resp


@app.route('/api/seekandwatch/approved', methods=['POST', 'OPTIONS'])
@limiter.limit("200 per hour")
def webhook_approved():
    """Receive approved requests from SeekAndWatch (instant). Called by cloud server or by your browser when you approve on the web."""
    if request.method == 'OPTIONS':
        return _add_cors(jsonify({'status': 'ok'})), 200
    secret = (request.headers.get('X-Webhook-Secret') or '').strip()
    settings = None
    for s in Settings.query.filter(Settings.cloud_webhook_url.isnot(None)).all():
        if secrets.compare_digest(s.cloud_webhook_secret or '', secret):
            settings = s
            break
    if not settings:
        return _add_cors(jsonify({'error': 'Unauthorized'})), 401
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        return _add_cors(jsonify({'error': 'Invalid JSON'})), 400
    requests_list = data.get('requests')
    if not isinstance(requests_list, list):
        return _add_cors(jsonify({'error': 'Missing or invalid requests array'})), 400
    from cloud_worker import process_approved_from_web
    synced = 0
    for item in requests_list:
        if isinstance(item, dict) and item.get('id'):
            ok, _ = process_approved_from_web(settings, item)
            if ok:
                synced += 1
    return _add_cors(jsonify({'status': 'ok', 'synced': synced})), 200


# SeekAndWatch cloud routes

@app.route('/requests')
@login_required
def requests_page():
    # Requests page removed: notices and config live on Settings. Redirect to Settings.
    return redirect(url_for('settings'))


@app.route('/requests/settings')
@login_required
def requests_settings_page():
    settings = current_user.settings
    return render_template('requests_settings.html', settings=settings)


@app.route('/api/cloud/test', methods=['POST'])
@login_required
def test_cloud_connection():
    """Test SeekAndWatch Cloud API key and connection. Accepts optional api_key in JSON to test before save."""
    settings = current_user.settings
    key = None
    if request.is_json and request.json:
        key = (request.json.get('api_key') or '').strip()
    if not key and settings:
        key = (settings.cloud_api_key or '').strip()
    if not key:
        return jsonify({'status': 'error', 'message': 'No API key provided. Enter a key and try again.'}), 400
    try:
        base = get_cloud_base_url(settings)
        r = requests.get(
            f"{base}/api/poll.php",
            headers={'X-Server-Key': key},
            timeout=min(15, CLOUD_REQUEST_TIMEOUT),
        )
        if r.status_code == 200:
            return jsonify({'status': 'success', 'message': 'Connection OK. API key is valid.'})
        if r.status_code == 401:
            return jsonify({'status': 'error', 'message': 'Invalid API key. Check your key in the Cloud Dashboard.'}), 200
        if r.status_code == 429:
            return jsonify({'status': 'warning', 'message': 'Too many requests (429). The cloud is temporarily rate-limiting; wait a minute and try again. Your key is valid.'}), 200
        return jsonify({'status': 'error', 'message': f'Cloud returned status {r.status_code}.'}), 200
    except requests.exceptions.Timeout:
        return jsonify({'status': 'error', 'message': 'Connection timed out. Check your network.'}), 200
    except requests.exceptions.ConnectionError:
        return jsonify({'status': 'error', 'message': 'Could not reach SeekAndWatch Cloud. Check your network.'}), 200
    except Exception as e:
        write_log("warning", "Cloud Test", str(e))
        return jsonify({'status': 'error', 'message': str(e) or 'Connection failed.'}), 200


@app.route('/save_cloud_settings', methods=['POST'])
@login_required
def save_cloud_settings():
    settings = current_user.settings
    if 'cloud_api_key' in request.form:
        if 'cloud_api_key_unchanged' in request.form:
            pass  # keep existing
        else:
            new_key = (request.form.get('cloud_api_key') or '').strip()
            if new_key:
                settings.cloud_api_key = new_key
                settings.cloud_enabled = True
            elif settings.cloud_api_key:
                pass  # safeguard: don't overwrite existing with empty
            else:
                settings.cloud_api_key = None
                settings.cloud_enabled = False
    settings.cloud_movie_handler = request.form.get('cloud_movie_handler')
    settings.cloud_tv_handler = request.form.get('cloud_tv_handler')
    settings.cloud_sync_owned_enabled = 'cloud_sync_owned_enabled' in request.form

    webhook_url = (request.form.get('cloud_webhook_url') or '').strip()
    if 'cloud_webhook_secret' in request.form:
        if 'cloud_webhook_secret_unchanged' in request.form:
            pass  # keep existing
        else:
            v = (request.form.get('cloud_webhook_secret') or '').strip()
            if v:
                settings.cloud_webhook_secret = v
            elif settings.cloud_webhook_secret:
                pass  # safeguard: don't overwrite existing with empty
            else:
                settings.cloud_webhook_secret = None
    settings.cloud_webhook_url = webhook_url or None
    webhook_secret = (settings.cloud_webhook_secret or '').strip()  # for register_webhook below

    raw_min = (request.form.get('cloud_poll_interval_min') or '').strip()
    raw_max = (request.form.get('cloud_poll_interval_max') or '').strip()
    poll_min = int(raw_min) if raw_min.isdigit() else None
    poll_max = int(raw_max) if raw_max.isdigit() else None
    if poll_min is not None:
        poll_min = max(30, poll_min)
    if poll_max is not None and poll_min is not None and poll_max < poll_min:
        poll_max = poll_min
    settings.cloud_poll_interval_min = poll_min
    settings.cloud_poll_interval_max = poll_max

    db.session.commit()

    if settings.cloud_api_key and settings.cloud_enabled:
        # Only call cloud to register/clear webhook when we have a webhook URL or had one (so cloud stays in sync)
        # If user left webhook blank, skip the API call so we don't show "webhook failed" when they only added the API key
        if webhook_url:
            try:
                base = get_cloud_base_url(settings)
                r = requests.post(
                    f"{base}/api/register_webhook.php",
                    headers={
                        'X-Server-Key': settings.cloud_api_key,
                        'Content-Type': 'application/json',
                    },
                    json={
                        'webhook_url': webhook_url or '',
                        'webhook_secret': webhook_secret or '',
                    },
                    timeout=CLOUD_REQUEST_TIMEOUT,
                )
                if r.status_code != 200:
                    flash("Cloud settings saved, but webhook registration failed (check API key).", "warning")
                else:
                    flash("Cloud settings updated successfully", "success")
            except Exception as e:
                write_log("warning", "Cloud", f"Webhook registration failed: {getattr(e, 'message', str(e))}")
                flash("Cloud settings saved, but could not register webhook (check API key and network).", "warning")
        else:
            flash("Cloud settings updated successfully", "success")
    else:
        flash("Cloud settings updated successfully", "success")

    return redirect(url_for('requests_settings_page'))

@app.route('/approve_request/<int:req_id>', methods=['POST'])
@login_required
def approve_request(req_id):
    # --- IMPORTANT: Local Import to prevent crash ---
    from cloud_worker import process_item

    req = CloudRequest.query.get_or_404(req_id)
    settings = current_user.settings

    # Execute the download logic (sends to Radarr/Sonarr/Overseerr); returns (success, cloud_ack_ok)
    success, cloud_ack_ok = process_item(settings, req)

    if success:
        flash(f"Approved and sent: {req.title}", "success")
        if not cloud_ack_ok:
            flash("Could not update SeekAndWatch Cloud (check API key in Requests Settings). It may still show as Pending on the web.", "warning")
    else:
        flash(f"Failed to send {req.title}. Check system logs.", "error")

    return redirect(url_for('requests_page'))

@app.route('/deny_request/<int:req_id>', methods=['POST'])
@login_required
def deny_request(req_id):
    req = CloudRequest.query.get_or_404(req_id)
    req.status = 'denied'
    db.session.commit()

    # Tell the cloud so friends see "Denied" and it no longer shows as pending
    deny_cloud_ok = True
    if req.cloud_id:
        try:
            settings = current_user.settings
            if settings and settings.cloud_api_key:
                base = get_cloud_base_url(settings)
                r = requests.post(
                    f"{base}/api/acknowledge.php",
                    headers={
                        'X-Server-Key': settings.cloud_api_key,
                        'Content-Type': 'application/json',
                    },
                    json={'request_id': str(req.cloud_id).strip(), 'status': 'failed'},
                    timeout=CLOUD_REQUEST_TIMEOUT
                )
                if r.status_code != 200:
                    deny_cloud_ok = False
                    print(f"Warning: Cloud acknowledge (deny) returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            deny_cloud_ok = False
            print(f"Warning: Could not acknowledge deny to cloud: {e}")

    if not deny_cloud_ok:
        flash(f"Denied locally but could not update SeekAndWatch Cloud (check API key in Requests Settings). It may still show as Pending on the web.", "warning")
    else:
        flash(f"Denied request: {req.title}", "warning")
    return redirect(url_for('requests_page'))
    
@app.route('/delete_request/<int:req_id>', methods=['POST'])
@login_required
def delete_request(req_id):
    """
    Deletes the request locally AND tells the Cloud to remove it.
    """
    req = CloudRequest.query.get_or_404(req_id)
    title = req.title # Save for message
    
    # --- 1. TELL CLOUD TO DELETE ---
    # If this request came from the cloud, we must kill it at the source
    cloud_id_val = (str(req.cloud_id).strip() if req.cloud_id else None) or None
    cloud_delete_ok = True
    cloud_delete_404_id = None
    cloud_delete_error_detail = None  # e.g. "415: Content-Type must be application/json"
    if cloud_id_val:
        try:
            settings = current_user.settings
            if settings and settings.cloud_api_key:
                base = get_cloud_base_url(settings)
                r = requests.post(
                    f"{base}/api/delete.php",
                    headers={
                        'X-Server-Key': settings.cloud_api_key,
                        'Content-Type': 'application/json',
                    },
                    json={'cloud_id': cloud_id_val},
                    timeout=CLOUD_REQUEST_TIMEOUT
                )
                if r.status_code != 200:
                    cloud_delete_ok = False
                    print(f"Warning: Cloud delete returned {r.status_code}: {r.text[:200]}")
                    try:
                        err_body = r.json()
                        err_msg = err_body.get('error', r.text[:80]) if isinstance(err_body, dict) else (r.text[:80] if r.text else '')
                        if r.status_code == 404 and err_body.get('cloud_id'):
                            cloud_delete_404_id = err_body.get('cloud_id')
                    except Exception:
                        err_msg = r.text[:80] if r.text else ''
                    cloud_delete_error_detail = f"{r.status_code}: {err_msg}" if err_msg else str(r.status_code)
        except Exception as e:
            cloud_delete_ok = False
            cloud_delete_error_detail = str(e)
            print(f"Warning: Could not delete from cloud: {e}")
    # -------------------------------

    # --- 2. RECORD DELETION SO WE DON'T RE-IMPORT FROM CLOUD ---
    if cloud_id_val:
        try:
            if not DeletedCloudId.query.filter_by(cloud_id=cloud_id_val).first():
                db.session.add(DeletedCloudId(cloud_id=cloud_id_val))
                db.session.flush()
        except Exception:
            pass  # table may not exist yet on old installs
    # --- 3. DELETE LOCALLY ---
    try:
        db.session.delete(req)
        db.session.commit()
        if not cloud_delete_ok:
            if cloud_delete_404_id:
                flash(f"Cloud could not find that request (id sent: {cloud_delete_404_id}). Compare with requests.id in the database.", "warning")
            elif cloud_delete_error_detail:
                flash(f"Deleted locally but cloud said: {cloud_delete_error_detail}. Fix that (e.g. API key, Content-Type) then try again.", "warning")
            else:
                flash(f"Deleted locally but could not remove from SeekAndWatch Cloud (check API key in Requests Settings or try again). It may still show as Pending on the web.", "warning")
        else:
            flash(f"Permanently deleted: {title}", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting request: {e}", "error")
        
    return redirect(url_for('requests_page'))
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)