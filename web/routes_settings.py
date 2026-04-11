"""
Blueprint for settings routes
Handles settings page, logs, profile deletion, webhook logs, and compatibility helpers
"""

import socket
import datetime
from datetime import timedelta
import requests
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash
from flask_login import login_required, current_user, logout_user
from werkzeug.security import check_password_hash
from auth_decorators import admin_required

from models import db, User, Settings, SystemLog, TmdbKeywordCache, TmdbRuntimeCache, TmdbAlias, Blocklist, WebhookLog
from utils.helpers import write_log
from utils.db_helpers import commit_with_retry
from utils.tmdb_http import is_tmdb_read_access_token, tmdb_get
from utils import validate_service_url, should_verify_tls
from services.IntegrationsService import IntegrationsService
from services.CloudService import CloudService
from plexapi.server import PlexServer

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
            if 'tmdb_key' in request.form:
                tmdb_value = (request.form.get('tmdb_key') or '').strip()
                if tmdb_value and not is_tmdb_read_access_token(tmdb_value):
                    return jsonify({
                        'status': 'error',
                        'message': 'TMDB now requires the API Read Access Token, not the legacy API key.'
                    }), 400
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
            if 'plex_url' in request.form or 'plex_token' in request.form or form_section == 'apis':
                # request.form.getlist handles multiple checkboxes with same name; if none checked, returns []
                s.ignored_users = ','.join([u for u in request.form.getlist('ignored_plex_users') if u])
            try:
                commit_with_retry()
            except Exception as e:
                db.session.rollback()
                write_log("error", "Settings", f"Save failed: {type(e).__name__}")
                return jsonify({'status': 'error', 'message': 'Database save failed. Please try again.'}), 500

        if update_scanners:
            if 'keyword_cache_size' in request.form:
                try:
                    s.keyword_cache_size = max(100, min(50000, int(request.form.get('keyword_cache_size', 3000))))
                except (TypeError, ValueError):
                    s.keyword_cache_size = 3000
            if 'runtime_cache_size' in request.form:
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
            if 'ignored_libraries' in request.form or form_section == 'scanners':
                ignored_libs = [l for l in request.form.getlist('ignored_libraries') if l]
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
            # cloud sync is now tied to tunnel status (no standalone checkbox)
            # this section is for system settings, so we don't change cloud_sync_owned_enabled here
            
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
    """Legacy fallback route to delete the current account."""
    data = request.get_json(silent=True) or request.form or {}
    current_password = (data.get('current_password') or '').strip()
    confirm_username = (data.get('confirm_username') or '').strip()

    if not current_password or not confirm_username:
        return jsonify({'status': 'error', 'message': 'Current password and username confirmation are required.'}), 400
    if confirm_username != current_user.username:
        return jsonify({'status': 'error', 'message': 'Username confirmation does not match your account.'}), 400
    if not check_password_hash(current_user.password_hash, current_password):
        return jsonify({'status': 'error', 'message': 'Current password is incorrect.'}), 400

    user = User.query.get(current_user.id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found.'}), 404

    total_users = User.query.count()
    if user.is_admin:
        other_admins = User.query.filter(User.is_admin.is_(True), User.id != user.id).count()
        if total_users > 1 and other_admins == 0:
            return jsonify({'status': 'error', 'message': 'Promote another admin before deleting this account.'}), 400

    user_id = user.id
    remaining_users_after_delete = max(total_users - 1, 0)

    try:
        Settings.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        Blocklist.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        from models import AppRequest, CloudRequest, KometaTemplate, RecoveryCode
        AppRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        CloudRequest.query.filter_by(owner_user_id=user_id).delete(synchronize_session=False)
        KometaTemplate.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        RecoveryCode.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()

        try:
            logout_user()
        except Exception:
            pass

        return jsonify({
            'status': 'success',
            'message': 'Your account has been deleted.',
            'redirect_url': '/register' if remaining_users_after_delete == 0 else '/login'
        })
    except Exception as e:
        db.session.rollback()
        write_log("error", "Settings", f"Delete profile failed: {type(e).__name__}")
        return jsonify({'status': 'error', 'message': f'Failed to delete account: {type(e).__name__}'}), 500

@web_settings_bp.route('/settings/admin/users')
@login_required
@admin_required
def get_all_users_fallback():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'is_admin': u.is_admin,
        'is_current': (u.id == current_user.id)
    } for u in users])

@web_settings_bp.route('/settings/admin/toggle_role', methods=['POST'])
@login_required
@admin_required
def toggle_user_role_fallback():
    data = request.get_json(silent=True) or {}
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

@web_settings_bp.route('/settings/admin/delete_user', methods=['POST'])
@login_required
@admin_required
def delete_user_fallback():
    data = request.get_json(silent=True) or {}
    target_id = data.get('user_id')

    if target_id == current_user.id:
        return jsonify({'status': 'error', 'message': 'Cannot delete yourself.'})

    user = User.query.get(target_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'})

    Settings.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Blocklist.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'User deleted.'})

@web_settings_bp.route('/settings/test_connection', methods=['POST'])
@login_required
def test_connection_fallback():
    data = request.get_json(silent=True) or {}
    service = data.get('service')
    use_stored = data.get('use_stored') is True
    s = current_user.settings if use_stored else None

    def _clean_url(url):
        if not url:
            return ""
        u = url.rstrip('/')
        if u.endswith('/api/v3'):
            u = u.rsplit('/api/v3', 1)[0]
        if u.endswith('/api'):
            u = u.rsplit('/api', 1)[0]
        return u

    try:
        if service == 'plex':
            u = (s.plex_url or '').strip() if use_stored and s else (data.get('url') or '').strip()
            t = (s.plex_token or '').strip() if use_stored and s else (data.get('token') or '').strip()
            if not u or not t:
                return jsonify({'status': 'error', 'message': 'Enter your Plex server URL and token to test the connection.'})
            is_safe, msg = validate_service_url(u)
            if not is_safe:
                return jsonify({'status': 'error', 'message': f"Security Block: {msg}"})
            p = PlexServer(u, t, timeout=5)
            return jsonify({'status': 'success', 'message': f"Connected: {p.friendlyName}"})

        if service == 'tmdb':
            clean_key = (s.tmdb_key or '').strip() if use_stored and s else (data.get('api_key') or '').strip()
            if not clean_key:
                return jsonify({'status': 'error', 'message': 'TMDB read access token required'})
            if not use_stored and not is_tmdb_read_access_token(clean_key):
                return jsonify({'status': 'error', 'message': 'Use the TMDB API Read Access Token, not the legacy API key'})
            r = tmdb_get('configuration', clean_key, timeout=10)
            return jsonify({'status': 'success', 'message': 'TMDB Connected!'}) if r.status_code == 200 else jsonify({'status': 'error', 'message': 'Invalid Key'})

        if service == 'omdb':
            clean_key = (s.omdb_key or '').strip() if use_stored and s else (data.get('api_key') or '').strip()
            if not clean_key:
                return jsonify({'status': 'error', 'message': 'API key required'})
            r = requests.get(f"https://www.omdbapi.com/?apikey={clean_key}&t=Inception", timeout=10)
            return jsonify({'status': 'success', 'message': 'OMDB Connected!'}) if r.json().get('Response') == 'True' else jsonify({'status': 'error', 'message': 'Invalid Key'})

        if service == 'tautulli':
            u = (s.tautulli_url or '').strip() if use_stored and s else (data.get('url') or '').strip()
            k = (s.tautulli_api_key or '').strip() if use_stored and s else (data.get('api_key') or '').strip()
            if not u or not k:
                return jsonify({'status': 'error', 'message': 'URL and API key required'})
            u = _clean_url(u)
            is_safe, msg = validate_service_url(u)
            if not is_safe:
                return jsonify({'status': 'error', 'message': f"Security Block: {msg}"})
            r = requests.get(f"{u}/api/v2?apikey={k}&cmd=get_server_info", timeout=5)
            return jsonify({'status': 'success', 'message': 'Tautulli Connected!'}) if r.status_code == 200 else jsonify({'status': 'error', 'message': 'Connection Failed'})

        if service == 'radarr':
            u = (s.radarr_url or '').strip() if use_stored and s else (data.get('url') or '').strip()
            k = (s.radarr_api_key or '').strip() if use_stored and s else (data.get('api_key') or '').strip()
            if not u or not k:
                return jsonify({'status': 'error', 'message': 'URL and API key required'})
            u = _clean_url(u)
            is_safe, msg = validate_service_url(u)
            if not is_safe:
                return jsonify({'status': 'error', 'message': f"Security Block: {msg}"})
            r = requests.get(f"{u}/api/v3/system/status", headers={'X-Api-Key': k}, timeout=5, verify=should_verify_tls(f"{u}/api/v3/system/status"))
            return jsonify({'status': 'success', 'message': 'Radarr Connected!'}) if r.status_code == 200 else jsonify({'status': 'error', 'message': f'Radarr returned HTTP {r.status_code}'})

        if service == 'sonarr':
            u = (s.sonarr_url or '').strip() if use_stored and s else (data.get('url') or '').strip()
            k = (s.sonarr_api_key or '').strip() if use_stored and s else (data.get('api_key') or '').strip()
            if not u or not k:
                return jsonify({'status': 'error', 'message': 'URL and API key required'})
            u = _clean_url(u)
            is_safe, msg = validate_service_url(u)
            if not is_safe:
                return jsonify({'status': 'error', 'message': f"Security Block: {msg}"})
            r = requests.get(f"{u}/api/v3/system/status", headers={'X-Api-Key': k}, timeout=5, verify=should_verify_tls(f"{u}/api/v3/system/status"))
            return jsonify({'status': 'success', 'message': 'Sonarr Connected!'}) if r.status_code == 200 else jsonify({'status': 'error', 'message': f'Sonarr returned HTTP {r.status_code}'})

        return jsonify({'status': 'error', 'message': 'Unknown service'})
    except Exception as e:
        write_log("error", "Settings", f"Test connection failed: {type(e).__name__}")
        return jsonify({'status': 'error', 'message': 'Connection failed'}), 500

@web_settings_bp.route('/dashboard/health')
@login_required
def dashboard_health_fallback():
    s = current_user.settings
    results = {
        'plex': {'status': 'unknown', 'message': 'Not configured'},
        'radarr': {'status': 'unknown', 'message': 'Not configured'},
        'sonarr': {'status': 'unknown', 'message': 'Not configured'},
        'cloud': {'status': 'unknown', 'message': 'Not configured'}
    }

    try:
        if s and s.plex_url and s.plex_token:
            url = f"{s.plex_url}/identity?X-Plex-Token={s.plex_token}"
            r = requests.get(url, timeout=3, verify=should_verify_tls(url))
            results['plex'] = {'status': 'online', 'message': 'Connected'} if r.status_code == 200 else {'status': 'offline', 'message': f'HTTP {r.status_code}'}
    except Exception:
        results['plex'] = {'status': 'offline', 'message': 'Offline'}

    try:
        if s and s.radarr_url and s.radarr_api_key:
            base = IntegrationsService._get_clean_base_url(s.radarr_url)
            status_url = f"{base}/api/v3/system/status"
            r = requests.get(status_url, headers={'X-Api-Key': s.radarr_api_key}, timeout=3, verify=should_verify_tls(status_url))
            results['radarr'] = {'status': 'online', 'message': 'Connected'} if r.status_code == 200 else {'status': 'offline', 'message': f'HTTP {r.status_code}'}
    except Exception:
        results['radarr'] = {'status': 'offline', 'message': 'Offline'}

    try:
        if s and s.sonarr_url and s.sonarr_api_key:
            base = IntegrationsService._get_clean_base_url(s.sonarr_url)
            status_url = f"{base}/api/v3/system/status"
            r = requests.get(status_url, headers={'X-Api-Key': s.sonarr_api_key}, timeout=3, verify=should_verify_tls(status_url))
            results['sonarr'] = {'status': 'online', 'message': 'Connected'} if r.status_code == 200 else {'status': 'offline', 'message': f'HTTP {r.status_code}'}
    except Exception:
        results['sonarr'] = {'status': 'offline', 'message': 'Offline'}

    try:
        if s and s.cloud_enabled and s.cloud_api_key:
            base = CloudService.get_cloud_base_url(s)
            r = requests.get(f"{base}/api/poll.php", headers={'X-Server-Key': s.cloud_api_key}, timeout=3)
            results['cloud'] = {'status': 'online', 'message': 'Connected'} if r.status_code == 200 else {'status': 'offline', 'message': f'Cloud Error {r.status_code}'}
    except Exception:
        results['cloud'] = {'status': 'offline', 'message': 'Offline'}

    return jsonify(results)
