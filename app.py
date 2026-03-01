"""Main Flask app - handles routing, auth, and the main UI stuff."""

import base64
import time
import os
import re
import sys
import logging

logging.basicConfig(level=logging.DEBUG)

# quiet down noisy loggers
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)

import config
from config import CONFIG_DIR, DATABASE_URI, SECRET_KEY_FILE, CLOUD_REQUEST_TIMEOUT, VERSION, UPDATE_CACHE
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
from flask_wtf.csrf import CSRFProtect, generate_csrf
from plexapi.server import PlexServer
from models import db, Blocklist, CollectionSchedule, TmdbAlias, SystemLog, Settings, User, TmdbKeywordCache, TmdbRuntimeCache, RadarrSonarrCache, RecoveryCode, CloudRequest, DeletedCloudId, WebhookLog
from utils.rate_limiter import limiter

# auto-migrate: add cloudflare and webhook columns if they don't exist (runs before tunnel init)
def ensure_cloudflare_columns():
    """Add cloudflare_api_token, cloudflare_account_id, cloud_webhook_failsafe_hours, and CloudRequest webhook columns if missing."""
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        
        # Settings table columns (tables should already exist from db.create_all() in startup)
        columns = [col['name'] for col in inspector.get_columns('settings')]
        
        if 'cloudflare_api_token' not in columns:
            print("Adding cloudflare_api_token column...")
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE settings ADD COLUMN cloudflare_api_token VARCHAR(255)'))
                conn.commit()
            print("✓ Added cloudflare_api_token")
        
        if 'cloudflare_account_id' not in columns:
            print("Adding cloudflare_account_id column...")
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE settings ADD COLUMN cloudflare_account_id VARCHAR(100)'))
                conn.commit()
            print("✓ Added cloudflare_account_id")
        
        if 'cloud_webhook_failsafe_hours' not in columns:
            print("Adding cloud_webhook_failsafe_hours column...")
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE settings ADD COLUMN cloud_webhook_failsafe_hours INTEGER DEFAULT 6'))
                conn.commit()
            print("✓ Added cloud_webhook_failsafe_hours")

        if 'pairing_token' not in columns:
            print("Adding pairing_token column...")
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE settings ADD COLUMN pairing_token VARCHAR(100)'))
                conn.commit()
            print("✓ Added pairing_token")

        if 'pairing_token_expires' not in columns:
            print("Adding pairing_token_expires column...")
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE settings ADD COLUMN pairing_token_expires DATETIME'))
                conn.commit()
            print("✓ Added pairing_token_expires")
        
        # CloudRequest table columns (for future webhook delay feature)
        if 'cloud_request' in inspector.get_table_names():
            cloud_req_columns = [col['name'] for col in inspector.get_columns('cloud_request')]
            
            if 'webhook_received_at' not in cloud_req_columns:
                print("Adding webhook_received_at column to cloud_request...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE cloud_request ADD COLUMN webhook_received_at DATETIME'))
                    conn.commit()
                print("✓ Added webhook_received_at")
            
            if 'webhook_process_after' not in cloud_req_columns:
                print("Adding webhook_process_after column to cloud_request...")
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE cloud_request ADD COLUMN webhook_process_after DATETIME'))
                    conn.commit()
                print("✓ Added webhook_process_after")
    except Exception as e:
        print(f"Warning: Could not add early migration columns: {e}")


def migrate_custom_poster_paths():
    """Fix stale /app/assets/custom_posters/ paths saved in the DB before we moved to /config/custom_posters/."""
    OLD_PATH = '/app/assets/custom_posters/'
    NEW_PATH = '/config/custom_posters/'
    try:
        rows = CollectionSchedule.query.filter(
            CollectionSchedule.configuration.ilike(f'%{OLD_PATH}%')
        ).all()
        if not rows:
            return
        count = 0
        for row in rows:
            try:
                cfg = json.loads(row.configuration or '{}')
                changed = False
                if isinstance(cfg.get('custom_poster'), str) and OLD_PATH in cfg['custom_poster']:
                    cfg['custom_poster'] = cfg['custom_poster'].replace(OLD_PATH, NEW_PATH)
                    changed = True
                if changed:
                    row.configuration = json.dumps(cfg)
                    count += 1
            except Exception:
                pass
        if count:
            db.session.commit()
            print(f"Migrated custom poster paths in {count} collection(s) from {OLD_PATH} to {NEW_PATH}")
    except Exception as e:
        print(f"Warning: custom poster path migration failed: {e}")

from utils import (normalize_title, is_duplicate, is_owned_item, fetch_omdb_ratings, 
                   create_backup, list_backups, restore_backup, 
                   prune_backups, BACKUP_DIR, sync_remote_aliases, get_tmdb_aliases, 
                   sync_plex_library, refresh_radarr_sonarr_cache, get_lock_status, is_system_locked,
                   write_scanner_log, read_scanner_log, prefetch_keywords_parallel,
                   item_matches_keywords, get_session_filters, write_log,
                   check_for_updates, handle_lucky_mode, reset_stuck_locks, 
                   prefetch_tv_states_parallel, prefetch_ratings_parallel, prefetch_omdb_parallel,
                   prefetch_runtime_parallel, is_docker, is_unraid, is_git_repo, is_app_dir_writable, perform_git_update,
                   perform_release_update, save_results_cache, get_history_cache, set_history_cache,
                   score_recommendation, diverse_sample, get_tmdb_rec_cache, set_tmdb_rec_cache,
                   get_results_cache, set_results_cache)
from utils.db_helpers import commit_with_retry
from presets import PLAYLIST_PRESETS
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

# basic app setup stuff
# VERSION and UPDATE_CACHE now imported from config.py

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

# Rate limiting to prevent abuse (imported from utils.rate_limiter to avoid circular imports)
limiter.init_app(app)

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

db.init_app(app)

# run database migrations on startup
with app.app_context():
    # CRITICAL: Ensure all tables exist first (including User table)
    # This must happen before any migrations that query tables
    try:
        db.create_all()
        print("✓ Database tables initialized")
    except Exception as e:
        print(f"ERROR: Failed to create database tables: {e}")
        import traceback
        traceback.print_exc()
    
    ensure_cloudflare_columns()
    migrate_custom_poster_paths()

login_manager = LoginManager()
login_manager.login_view = 'web_auth.login'
login_manager.init_app(app)

# initialize tunnel manager and health monitor
tunnel_manager = None
health_monitor = None

def init_tunnel_services():
    """Initialize tunnel manager and health monitor on app startup."""
    global tunnel_manager, health_monitor
    
    try:
        from tunnel.manager import TunnelManager
        from tunnel.health import HealthMonitor
        
        # create tunnel manager instance
        tunnel_manager = TunnelManager(app, db)
        app.tunnel_manager = tunnel_manager
        
        # create health monitor
        health_monitor = HealthMonitor(tunnel_manager, check_interval=60)
        
        # start tunnels for users who have them enabled AND have the required credentials
        with app.app_context():
            from models import Settings
            enabled_users = Settings.query.filter_by(tunnel_enabled=True).all()
            
            for settings in enabled_users:
                # Check for Quick Tunnel first
                if settings.tunnel_name == 'quick-tunnel' or not hasattr(settings, 'cloudflare_api_token') or not settings.cloudflare_api_token:
                    app.logger.info(f"Starting quick tunnel for user {settings.user_id}")
                    tunnel_url = tunnel_manager.start_quick_tunnel(settings.user_id)
                    
                    if tunnel_url and settings.cloud_enabled and settings.cloud_api_key:
                        # Ensure we have a secret locally
                        if not settings.cloud_webhook_secret:
                            import secrets
                            settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                            db.session.commit()

                        # re-register webhook with new URL
                        from services.Router import Router
                        cloud_base = get_cloud_base_url(settings)
                        app.logger.info(f"Re-registering webhook for quick tunnel: {tunnel_url} with {cloud_base}")
                        tunnel_manager.register_webhook(
                            tunnel_url=tunnel_url,
                            api_key=settings.cloud_api_key,
                            cloud_base_url=cloud_base,
                            user_id=settings.user_id,
                            webhook_secret=settings.cloud_webhook_secret
                        )
                    continue

                # only try to start if user has cloudflare API token (needed for API-based tunnels)
                if not hasattr(settings, 'cloudflare_api_token') or not settings.cloudflare_api_token:
                    app.logger.warning(f"Skipping tunnel start for user {settings.user_id}: no Cloudflare API token")
                    continue
                
                # check if we have encrypted tunnel credentials with token
                if not settings.tunnel_credentials_encrypted:
                    app.logger.warning(f"Skipping tunnel start for user {settings.user_id}: no tunnel credentials")
                    continue
                
                try:
                    app.logger.info(f"Starting tunnel for user {settings.user_id}")
                    
                    # decrypt credentials to get tunnel token
                    credentials = tunnel_manager._decrypt_credentials(settings.tunnel_credentials_encrypted)
                    
                    if not credentials or 'tunnel_token' not in credentials:
                        app.logger.error(f"Failed to decrypt tunnel token for user {settings.user_id}")
                        continue
                    
                    # start tunnel with token (API-based approach)
                    tunnel_manager.start_tunnel_with_token(settings.user_id, credentials['tunnel_token'])
                    
                except Exception:
                    app.logger.error(f"Failed to start tunnel for user {settings.user_id}")
            
            # start health monitoring
            if enabled_users:
                health_monitor.start()
                app.logger.info("Tunnel health monitor started")
                
                # Perform startup handshake for all enabled tunnels
                def perform_handshake(user_ids):
                    time.sleep(15) # Wait for DNS propagation
                    with app.app_context():
                        from tunnel.registrar import WebhookRegistrar
                        from services.Router import Router
                        from models import Settings
                        for uid in user_ids:
                            s = Settings.query.filter_by(user_id=uid).first()
                            if s and s.cloud_enabled and s.cloud_api_key and s.tunnel_url:
                                try:
                                    app.logger.info(f"Performing startup handshake for user {s.user_id}...")
                                    registrar = WebhookRegistrar(get_cloud_base_url(s), s.cloud_api_key)
                                    success, message = registrar.test_connection(timeout=10)
                                    if success:
                                        app.logger.info(f"Handshake successful: {message}")
                                    else:
                                        app.logger.warning(f"Handshake failed: {message}")
                                except Exception as e:
                                    app.logger.error(f"Handshake error: {e}")

                enabled_ids = [s.user_id for s in enabled_users]
                threading.Thread(target=perform_handshake, args=(enabled_ids,), daemon=True).start()
        
    except Exception:
        app.logger.error("Failed to initialize tunnel services")

# initialize tunnel services after a short delay (let app finish starting up)
import threading
def delayed_tunnel_init():
    import time
    time.sleep(5)  # wait 5 seconds for app to be ready
    init_tunnel_services()

tunnel_init_thread = threading.Thread(target=delayed_tunnel_init, daemon=True)
tunnel_init_thread.start()



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
    except OperationalError:
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
    """Run ALTER TABLE ADD COLUMN; ignore duplicate column (inspector can be stale).
    
    WARNING: This function uses raw SQL and should be replaced with ORM operations.
    Only use for legacy migrations. New migrations should use migration_helpers.
    """
    try:
        conn.execute(sqlalchemy.text(sql))
    except OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise

def run_migrations():
    """Adds any missing DB columns and makes sure there's always at least one admin."""
    from utils.migration_helpers import MigrationLock, create_backup_before_migration
    
    # use secure file lock
    with MigrationLock():
        # create backup before migrations (safety net)
        create_backup_before_migration(app)
        
        # run migrations
        _perform_actual_migrations()

def _perform_actual_migrations():
    with app.app_context():
        # Ensure all core tables exist (User, Settings, etc.)
        # This is critical - if this fails, the app cannot function
        try:
            db.create_all()
            print("✓ Core database tables verified")
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to create core database tables: {e}")
            import traceback
            traceback.print_exc()
            raise  # Don't continue if core tables can't be created
        
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
                if 'cloud_webhook_failsafe_hours' not in settings_columns:
                    print("--- [Migration] Adding 'cloud_webhook_failsafe_hours' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN cloud_webhook_failsafe_hours INTEGER DEFAULT 6")
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
                if 'quiet_webhook_logs' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN quiet_webhook_logs BOOLEAN DEFAULT 0")
                else:
                    # flip existing users from quiet (1) to verbose (0) for better debugging
                    try:
                        conn.execute("UPDATE settings SET quiet_webhook_logs = 0 WHERE quiet_webhook_logs = 1")
                        print("--- [Migration] Disabled quiet_webhook_logs for existing users ---", flush=True)
                    except: pass
                if 'max_webhook_log_size_mb' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN max_webhook_log_size_mb INTEGER DEFAULT 2")
                if 'max_webhook_logs' not in settings_columns:
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN max_webhook_logs INTEGER DEFAULT 100")
                
                # Cloudflare Tunnel columns
                if 'tunnel_enabled' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_enabled' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_enabled BOOLEAN DEFAULT 0")
                if 'tunnel_url' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_url' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_url VARCHAR(512)")
                if 'tunnel_name' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_name' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_name VARCHAR(100)")
                if 'tunnel_credentials_encrypted' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_credentials_encrypted' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_credentials_encrypted TEXT")
                if 'tunnel_last_started' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_last_started' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_last_started DATETIME")
                if 'tunnel_last_error' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_last_error' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_last_error VARCHAR(512)")
                if 'tunnel_status' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_status' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_status VARCHAR(20) DEFAULT 'disconnected'")
                if 'tunnel_restart_count' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_restart_count' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_restart_count INTEGER DEFAULT 0")
                if 'tunnel_last_health_check' not in settings_columns:
                    print("--- [Migration] Adding 'tunnel_last_health_check' column ---")
                    _alter_add_column(conn, "ALTER TABLE settings ADD COLUMN tunnel_last_health_check DATETIME")
                
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
            print(f"--- [Migration] Schema failed: {e} ---", flush=True)

        # if somehow there are no admins, make the first user an admin
        # (shouldn't happen but better safe than sorry)
        try:
            with db.engine.connect() as conn:
                result = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user WHERE is_admin = 1")).scalar()
                
                if result == 0:
                    user_count = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM user")).scalar()
                    
                    if user_count > 0:
                        # promote the lowest id user
                        conn.execute(sqlalchemy.text("UPDATE user SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM user)"))
                        conn.commit()
                        print("--- [Startup] AUTO-FIX: No admins found. Promoted the first user to Admin. ---")
        except Exception as e:
            print(f"--- [Migration] Admin auto-fix failed: {e} ---", flush=True)

        for model_name, model in [
            ('Blocklist', Blocklist),
            ('CollectionSchedule', CollectionSchedule),
            ('TmdbAlias', TmdbAlias),
            ('TmdbKeywordCache', TmdbKeywordCache),
            ('TmdbRuntimeCache', TmdbRuntimeCache),
            ('RadarrSonarrCache', RadarrSonarrCache),
            ('RecoveryCode', RecoveryCode),
            ('CloudRequest', CloudRequest),
            ('WebhookLog', WebhookLog),
        ]:
            try:
                model.__table__.create(db.engine, checkfirst=True)
            except Exception as e:
                print(f"--- [Migration] Create table {model_name} failed: {e} ---", flush=True)
        
        # create security tables (webhook_attempt, login_attempt, account_lockout)
        try:
            from models_security import WebhookAttempt, LoginAttempt, AccountLockout
            for model_name, model in [
                ('WebhookAttempt', WebhookAttempt),
                ('LoginAttempt', LoginAttempt),
                ('AccountLockout', AccountLockout),
            ]:
                try:
                    model.__table__.create(db.engine, checkfirst=True)
                    print(f"✓ Created security table: {model_name}")
                except Exception as e:
                    print(f"--- [Migration] Create security table {model_name} failed: {e} ---", flush=True)
        except ImportError as e:
            print(f"--- [Migration] Could not import security models: {e} ---", flush=True)
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
        except Exception as e:
            print(f"--- [Migration] app_request user_id failed: {e} ---", flush=True)

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
        except Exception as e:
            print(f"--- [Migration] cloud_request failed: {e} ---", flush=True)

        # radarr_sonarr_cache: has_file so we only treat "has file" as owned (radarr: "not available" = no file)
        try:
            inspector = sqlalchemy.inspect(db.engine)
            if 'radarr_sonarr_cache' in inspector.get_table_names():
                cache_columns = [c['name'] for c in inspector.get_columns('radarr_sonarr_cache')]
                if 'has_file' not in cache_columns:
                    with db.engine.connect() as conn:
                        _alter_add_column(conn, "ALTER TABLE radarr_sonarr_cache ADD COLUMN has_file BOOLEAN DEFAULT 1")
                        conn.commit()
                        print("--- [Migration] Added 'has_file' column to radarr_sonarr_cache ---")
        except Exception as e:
            print(f"--- [Migration] radarr_sonarr_cache failed: {e} ---", flush=True)

        # record schema version so request-time check can detect restore/out-of-date db
        try:
            with db.engine.connect() as conn:
                conn.execute(sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS schema_info (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"
                ))
                conn.execute(sqlalchemy.text("INSERT OR REPLACE INTO schema_info (id, version) VALUES (1, :v)"), {"v": CURRENT_SCHEMA_VERSION})
                conn.commit()
        except Exception as e:
            print(f"--- [Migration] schema_info failed: {e} ---", flush=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    
try:
    run_migrations()
except Exception as e:
    import traceback
    print(f"--- STARTUP ERROR: migrations failed: {e} ---", flush=True)
    traceback.print_exc()
    sys.exit(1)

# clear any leftover lock files from crashes/restarts
print("--- BOOT SEQUENCE: CLEARING LOCKS ---", flush=True)
try:
    reset_stuck_locks()
except Exception:
    print("Error resetting locks", flush=True)

# github stats cache
github_cache = {
    "stars": "...",
    "latest_version": "0.0.0",
    "last_updated": 0
}

def update_github_stats():
    """grabs github stars and latest version, runs every hour in the background"""
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
            
        except Exception:
            print(f"GitHub Update Error: {e}")
            
        time.sleep(3600)

# start background thread
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=update_github_stats, daemon=True).start()
    # cloud requests are polled every minute via scheduled_tasks() when cloud sync is enabled

# inject into all templates
@app.context_processor
def inject_github_data():
    return dict(
        github_stars=github_cache['stars'],
        latest_version=github_cache['latest_version'],
        current_version=VERSION,
        is_unraid=is_unraid()
    )

# main page routes

@app.context_processor
def inject_version():
    return dict(version=VERSION)

@app.context_processor
def inject_pending_requests_count():
    """inject pending cloud request count for sidebar badge"""
    if not current_user.is_authenticated:
        return dict(pending_requests_count=0)
    try:
        count = CloudRequest.query.filter(CloudRequest.status == 'pending').count()
        return dict(pending_requests_count=count)
    except Exception:
        return dict(pending_requests_count=0)

# migrated to web/routes_auth.py (phase 3.2b)
# @app.route('/')
# def index():
#     if current_user.is_authenticated:
#         return redirect(url_for('web_pages.dashboard'))
#     return redirect(url_for('login'))

# def _no_users_exist():
#     """check if no users exist, used to exempt first registration/login from rate limiting"""
#     try:
#         return User.query.count() == 0
#     except Exception:
#         return False

# auth routes migrated to web/routes_auth.py (phase 3.2b)
# old routes removed, now handled by web_auth_bp blueprint
# routes migrated: /, /login, /register, /logout, /reset_password, 
#                  /welcome_codes, /welcome_codes_done, /api/csrf-token

# dashboard and main page routes migrated to web/routes_pages.py (phase 3.2d)
# old routes removed, now handled by web_pages_bp blueprint
# routes migrated: /dashboard, /builder, /playlists, /kometa, /media, /support, /tests, /scripts, /manage_blocklist

# phase 3.2g - generate flow routes migrated to web/routes_generate.py
# routes migrated: /get_local_trending, /recommend_from_trending, /review_history, /generate, /reset_alias_db

from services.CollectionService import CollectionService
from services.CloudService import CloudService

# background scheduler - runs collections, cache refreshes, etc on a schedule

def scheduled_tasks():
    with app.app_context():
        # prune backups
        try:
            if datetime.datetime.now().hour == 4 and datetime.datetime.now().minute == 0:
                prune_backups()
        except Exception as e:
            print(f"Scheduler Error (Pruning): {e}")
            
        # grab Settings (needed for remaining tasks)
        try:
            if getattr(config, 'SCHEDULER_USER_ID', None) is not None:
                s = Settings.query.filter_by(user_id=config.SCHEDULER_USER_ID).first()
            else:
                s = Settings.query.first()
            if not s: return
        except Exception as e:
            print(f"Scheduler Error (DB Access): {e}")
            return
        
        # sync Plex library
        try:
            last_sync = s.last_alias_scan or 0
            interval_hours = (s.cache_interval or 0)
            if interval_hours > 0 and last_sync > 0 and (time.time() - last_sync) >= interval_hours * 3600:
                if not is_system_locked():
                    print("Scheduler: Starting Plex library sync...")
                    sync_plex_library(app)
        except Exception as e:
            print(f"Scheduler Error (Plex Sync): {e}")

        # collection scheduling
        try:
            target_hour, target_minute = 4, 0
            try:
                target_hour, target_minute = map(int, (s.schedule_time or "04:00").split(':'))
            except: pass
                
            now = datetime.datetime.now()
            for sch in CollectionSchedule.query.all():
                try:
                    if sch.frequency == 'manual': continue
                    
                    should_run = False
                    last = sch.last_run
                    
                    if sch.frequency == 'daily':
                        run_today = (last and last.date() == now.date())
                        past_target_time = (now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute))
                        if not run_today and past_target_time: should_run = True
                    elif sch.frequency == 'weekly':
                        if not last or (now - last).days >= 7: should_run = True
                        
                    if should_run:
                        # process collection
                        if sch.preset_key.startswith('custom_'):
                             try: preset_data = json.loads(sch.configuration)
                             except: preset_data = None
                        else:
                             preset_data = PLAYLIST_PRESETS.get(sch.preset_key, {}).copy()
                             if sch.configuration and preset_data:
                                 try: preset_data.update(json.loads(sch.configuration))
                                 except: pass
                        
                        if not preset_data:
                            print(f"Scheduler: ⚠️ Deleting missing or invalid collection '{sch.preset_key}' from database.")
                            db.session.delete(sch)
                            db.session.commit()
                            continue

                        print(f"Scheduler: Running collection {sch.preset_key}...")
                        CollectionService.run_collection_logic(s, preset_data, sch.preset_key, app_obj=app)
                        sch.last_run = now
                        db.session.commit()
                except Exception as task_err:
                    print(f"Scheduler Error (Collection {sch.preset_key}): {task_err}")
        except Exception as e:
            print(f"Scheduler Error (Collection Loop): {e}")

        # Radarr/Sonarr scanner
        try:
            if s.radarr_sonarr_scanner_enabled:
                last = s.last_radarr_sonarr_scan or 0
                if int(time.time()) - last >= (s.radarr_sonarr_scanner_interval or 24) * 3600:
                    if not is_system_locked():
                        print("Scheduler: Starting Radarr/Sonarr Cache Refresh...")
                        threading.Thread(target=refresh_radarr_sonarr_cache, args=(app,)).start()
        except Exception as e:
            print(f"Scheduler Error (Integrations): {e}")

        # Cloud polling
        try:
            if getattr(s, 'cloud_enabled', False) and getattr(s, 'cloud_api_key', None) and getattr(s, 'cloud_sync_owned_enabled', True):
                CloudService.process_cloud_queue(app)
        except Exception as e:
            print(f"Scheduler Error (Cloud Poll): {e}")

scheduler.add_job(id='master_task', func=scheduled_tasks, trigger='interval', minutes=15)

# blueprint registration
# order matters! first registered blueprint wins for conflicting routes
# 
# registration order:
# 1. api blueprint (url_prefix='/api') - registered first, won't conflict with web routes
# 2. auth blueprint - handles /, /login, /logout - must be early to catch root route
# 3. settings blueprint - handles /settings, /logs, /webhook_logs, /delete_profile
# 4. pages blueprint - handles /dashboard, /playlists, /builder, etc.
#
# why this order:
# - api blueprint has url_prefix so it's isolated from web routes
# - auth blueprint must catch '/' before other blueprints
# - settings and pages blueprints don't conflict (different urls)
# - later blueprints cannot override earlier ones

# import api blueprint (must be after app creation)
try:
    from api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    # exempt webhook from csrf protection
    csrf.exempt(api_bp)
    import api
    api.limiter = limiter
except ImportError:
    import traceback
    print("error: failed to import api module")
    traceback.print_exc()
    print(f"Current working directory: {os.getcwd()}")
    print(f"Files in current directory: {os.listdir('.')}")
    raise
except Exception:
    import traceback

# import web blueprints (phase 3.2 blueprint migration)
try:
    from web.routes_auth import web_auth_bp
    app.register_blueprint(web_auth_bp)
    
    from web.routes_settings import web_settings_bp
    app.register_blueprint(web_settings_bp)
    
    from web.routes_pages import web_pages_bp
    app.register_blueprint(web_pages_bp)
    
    # phase 3.2e - utility routes (trigger_update, api/cloud/test, api/settings/autodiscover, api/plex/metadata)
    from web.routes_utility import web_utility_bp
    app.register_blueprint(web_utility_bp)
    
    # phase 3.2f - cloud request routes (requests, approve/deny/delete, save_cloud_settings)
    from web.routes_requests import web_requests_bp
    app.register_blueprint(web_requests_bp)
    
    # phase 3.2g - generate flow routes (trending, history, generate, reset_alias_db)
    from web.routes_generate import generate_bp
    app.register_blueprint(generate_bp)
except ImportError:
    import traceback
    print("error: failed to import web blueprints")
    traceback.print_exc()
    raise
except Exception:
    import traceback
    print("error: web blueprint registration failed")
    traceback.print_exc()
    raise


# global error handlers so users see a friendly page instead of a crash
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', message='Page not found.'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', message='Something went wrong. Please try again or check the logs.'), 500


# lightweight health endpoint for docker/orchestration (no auth, no heavy work)
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': VERSION}), 200


# favicon route (browsers request this automatically)
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'icon.png',
        mimetype='image/png'
    )


# utility and cloud request routes migrated (phase 3.2e & 3.2f)
# old routes removed, now handled by web_utility_bp and web_requests_bp blueprints
# routes migrated to web/routes_utility.py:
#   - /trigger_update (post)
#   - /api/cloud/test (post)
#   - /api/settings/autodiscover (post)
#   - /api/plex/metadata (get)
# routes migrated to web/routes_requests.py:
#   - /requests (get)
#   - /requests/settings (get)
#   - /approve_request/<int:req_id> (post)
#   - /deny_request/<int:req_id> (post)
#   - /delete_request/<int:req_id> (post)
#   - /save_cloud_settings (post)

# custom poster static file serving (kept in app.py as system-level route)
from utils import CUSTOM_POSTER_DIR

@app.route('/img/custom_posters/<path:filename>')
def custom_poster(filename):
    return send_from_directory(CUSTOM_POSTER_DIR, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

