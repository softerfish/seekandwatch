"""
Blueprint for settings routes
Handles settings page, logs, profile deletion, and webhook logs
"""

import socket
import datetime
from datetime import timedelta
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash
from flask_login import login_required, current_user, logout_user
from auth_decorators import admin_required

from models import db, User, Settings, SystemLog, TmdbKeywordCache, TmdbRuntimeCache, TmdbAlias, Blocklist, WebhookLog
from utils import write_log
from utils.db_helpers import commit_with_retry

# Create blueprint
web_settings_bp = Blueprint('web_settings', __name__)

def _valid_url(val):
    """True if value is empty or a safe http(s) URL (no javascript:, data:)."""
    if not val or not str(val).strip():
        return True
    v = str(val).strip().lower()
    if v.startswith("javascript:") or v.startswith("data:"):
        return False
    return v.startswith("http://") or v.startswith("https://")

@web_settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Settings page - handles all settings forms"""
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
            url_fields = ['plex_url', 'tautulli_url', 'radarr_url', 'sonarr_url']
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
                else:
                    setattr(s, attr_name, None)
            if 'plex_url' in request.form:
                s.plex_url = request.form.get('plex_url')
            _apply_key('plex_token', 'plex_token_unchanged', 'plex_token')
            _apply_key('tmdb_key', 'tmdb_key_unchanged', 'tmdb_key')
            if 'tmdb_region' in request.form:
                s.tmdb_region = request.form.get('tmdb_region')
            _apply_key('omdb_key', 'omdb_key_unchanged', 'omdb_key')
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
            
            s.quiet_webhook_logs = 'quiet_webhook_logs' in request.form
            try:
                s.max_webhook_logs = max(10, min(1000, int(request.form.get('max_webhook_logs', 100))))
            except (TypeError, ValueError):
                s.max_webhook_logs = 100
            try:
                s.max_webhook_log_size_mb = max(1, min(10, int(request.form.get('max_webhook_log_size_mb', 2))))
            except (TypeError, ValueError):
                s.max_webhook_log_size_mb = 2

            try:
                commit_with_retry()
            except Exception as e:
                db.session.rollback()
                write_log("error", "Settings", f"Save failed: {type(e).__name__}")
                return jsonify({'status': 'error', 'message': 'Database save failed. Please try again.'}), 500

        return jsonify({'status': 'success', 'message': 'Settings saved successfully.', 'msg': 'Settings saved successfully.'})

    current_ignored = (s.ignored_users or '').split(',')
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

    try: alias_count = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).count()
    except Exception: alias_count = 0
    
    # Extract server IP/hostname from request for auto-fill
    server_host = None
    try:
        host_header = request.host
        if ':' in host_header:
            server_host = host_header.split(':')[0].strip().lower()
        else:
            server_host = (host_header or "").strip().lower()
        
        if server_host in ['localhost', '127.0.0.1', '0.0.0.0'] or server_host.endswith('.trycloudflare.com'):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.connect(("8.8.8.8", 80))
                server_host = sock.getsockname()[0]
                sock.close()
            except:
                server_host = None
    except Exception:
        server_host = None

    return render_template('settings.html', 
                           settings=s, 
                           current_ignored=current_ignored,
                           current_ignored_libs=current_ignored_libs,
                           logs=logs, 
                           cache_age=cache_age,
                           alias_count=alias_count,
                           keyword_count=keyword_count,
                           runtime_count=runtime_count,
                           server_host=server_host)

@web_settings_bp.route('/logs_page')
@login_required
@admin_required
def logs_page():
    """System logs page (admin only)"""
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

@web_settings_bp.route('/webhook_logs')
@login_required
def webhook_logs_page():
    """Webhook logs page"""
    logs = WebhookLog.query.order_by(WebhookLog.timestamp.desc()).limit(100).all()
    s = current_user.settings
    quiet_mode = s.quiet_webhook_logs if s else False
    return render_template('webhook_logs.html', logs=logs, quiet_mode=quiet_mode)

@web_settings_bp.route('/delete_profile', methods=['POST'])
@login_required
def delete_profile():
    """Delete user profile and all associated data"""
    user = User.query.get(current_user.id)
    Settings.query.filter_by(user_id=current_user.id).delete()
    Blocklist.query.filter_by(user_id=current_user.id).delete()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return render_template('logout_redirect.html', login_url=url_for('web_auth.login'))
