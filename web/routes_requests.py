"""
Blueprint for cloud request management routes
Handles request approval, denial, deletion, and cloud settings
"""

import requests
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash
from flask_login import login_required, current_user

from models import db, Settings, CloudRequest, DeletedCloudId
from services.CloudService import CloudService
from config import CLOUD_REQUEST_TIMEOUT

# Create blueprint
web_requests_bp = Blueprint('web_requests', __name__)

def _get_current_settings():
    return current_user.settings

def _get_owned_cloud_request_or_404(req_id):
    settings = _get_current_settings()
    query = CloudRequest.query.filter_by(id=req_id)
    if settings and hasattr(CloudRequest, 'owner_user_id'):
        query = query.filter_by(owner_user_id=settings.user_id)
    return query.first_or_404()

@web_requests_bp.route('/requests')
@login_required
def requests_page():
    """Requests page removed: notices and config live on Settings. Redirect to Settings."""
    return redirect(url_for('web_settings.settings'))

@web_requests_bp.route('/requests/settings')
@login_required
def requests_settings_page():
    """Cloud requests settings page"""
    settings = _get_current_settings()
    pairing_owner_id = (getattr(settings, 'pair_handoff_owner_user_id', None) or '').strip()
    pairing_bootstrap_secret = (getattr(settings, 'pair_handoff_bootstrap_secret', None) or '').strip()
    pairing_ready = bool(pairing_owner_id and pairing_bootstrap_secret)
    cloud_import_log = CloudService.get_cloud_import_log(20, settings=settings)
    last_instant_import = next(
        (entry for entry in cloud_import_log if (entry.get('delivery') or '').strip().lower() in (
            'quick tunnel', 'named tunnel', 'external', 'cloudflare tunnel', 'ngrok', 'webhook', 'webhook (legacy)'
        )),
        None
    )
    last_poll_import = next(
        (entry for entry in cloud_import_log if 'poll' in (entry.get('delivery') or '').strip().lower()),
        None
    )
    sync_mode = 'Instant webhook delivery plus backup polling'
    if settings.tunnel_provider == 'external':
        sync_mode = 'External webhook delivery plus backup polling'
    elif not settings.tunnel_enabled:
        sync_mode = 'Backup polling only until a tunnel is active'
    verification_state = 'Waiting for a tunnel to be enabled'
    if settings.tunnel_enabled and settings.tunnel_status == 'connected':
        verification_state = 'Tunnel connected and ready for instant imports'
    elif settings.tunnel_enabled and settings.tunnel_status == 'error':
        verification_state = f"Tunnel needs attention: {settings.tunnel_last_error or 'Unknown issue'}"
    elif settings.tunnel_enabled:
        verification_state = 'Tunnel is starting or being verified'
    elif settings.tunnel_provider == 'external' and settings.cloud_webhook_url:
        verification_state = 'Waiting for requests at your saved external webhook URL'
    return render_template(
        'requests_settings.html',
        settings=settings,
        pairing_ready=pairing_ready,
        pairing_owner_id=pairing_owner_id,
        cloud_import_log=cloud_import_log,
        last_instant_import=last_instant_import,
        last_poll_import=last_poll_import,
        sync_mode=sync_mode,
        verification_state=verification_state,
    )

@web_requests_bp.route('/save_cloud_settings', methods=['POST'])
@login_required
def save_cloud_settings():
    """Save cloud integration settings"""
    settings = _get_current_settings()
    previous_tunnel_provider = getattr(settings, 'tunnel_provider', None)
    previous_tunnel_name = getattr(settings, 'tunnel_name', None)
    if 'cloud_api_key' in request.form:
        if 'cloud_api_key_unchanged' in request.form:
            pass  # keep existing
        else:
            new_key = (request.form.get('cloud_api_key') or '').strip()
            if new_key:
                settings.cloud_api_key = new_key
                settings.cloud_enabled = True
            else:
                settings.cloud_api_key = None
                settings.cloud_enabled = False
    settings.pair_handoff_owner_user_id = (request.form.get('pair_handoff_owner_user_id') or '').strip() or None
    if 'pair_handoff_bootstrap_secret_unchanged' in request.form:
        pass
    else:
        settings.pair_handoff_bootstrap_secret = (request.form.get('pair_handoff_bootstrap_secret') or '').strip() or None
    settings.cloud_movie_handler = request.form.get('cloud_movie_handler')
    settings.cloud_tv_handler = request.form.get('cloud_tv_handler')
    
    # cloud sync is on if the tunnel is up or a manual external URL was given
    tunnel_choice = request.form.get('tunnel_provider_choice')
    if tunnel_choice == 'external':
        settings.tunnel_provider = 'external'
        settings.tunnel_enabled = False # the app isn't running this tunnel
        settings.cloud_sync_owned_enabled = True # but owned sync still is
    elif tunnel_choice == 'cloudflare_quick':
        settings.tunnel_provider = 'cloudflare'
        settings.tunnel_name = 'quick-tunnel'
        settings.cloud_sync_owned_enabled = settings.tunnel_enabled
    elif tunnel_choice == 'cloudflare_named':
        settings.tunnel_provider = 'cloudflare'
        if not settings.tunnel_name or settings.tunnel_name == 'quick-tunnel':
            settings.tunnel_name = 'named-tunnel'
        settings.cloud_sync_owned_enabled = settings.tunnel_enabled
    else:
        # normal auto-enable behavior for internal tunnels
        settings.cloud_sync_owned_enabled = settings.tunnel_enabled
    
    # handle the auto-recovery toggle from the tunnel config form
    if 'from_tunnel_config' in request.form:
        # update provider if changed
        if tunnel_choice:
            if tunnel_choice == 'cloudflare_quick':
                settings.tunnel_provider = 'cloudflare'
                settings.tunnel_name = 'quick-tunnel'
            elif tunnel_choice == 'cloudflare_named':
                settings.tunnel_provider = 'cloudflare'
                settings.tunnel_name = 'named-tunnel' # unless it's already set that way
            elif tunnel_choice == 'external':
                settings.tunnel_provider = 'external'

        # auto-recovery toggle
        if hasattr(settings, 'tunnel_auto_recovery_enabled'):
            switching_to_quick = (
                tunnel_choice == 'cloudflare_quick'
                and not (
                    previous_tunnel_provider == 'cloudflare'
                    and previous_tunnel_name == 'quick-tunnel'
                )
            )
            if switching_to_quick and 'tunnel_auto_recovery_enabled' not in request.form:
                settings.tunnel_auto_recovery_enabled = True
            else:
                settings.tunnel_auto_recovery_enabled = 'tunnel_auto_recovery_enabled' in request.form
        
        # circuit breaker reset
        if 'reset_circuit_breaker' in request.form and hasattr(settings, 'tunnel_recovery_disabled'):
            settings.tunnel_recovery_disabled = False
            settings.tunnel_recovery_count = 0
            settings.tunnel_consecutive_failures = 0
            flash("Auto-recovery has been reset. Try enabling the tunnel again.", "success")

    # save cloudflare tunnel settings
    if 'cloudflare_api_token_unchanged' in request.form:
        pass
    else:
        settings.cloudflare_api_token = (request.form.get('cloudflare_api_token') or '').strip() or None
    settings.cloudflare_account_id = (request.form.get('cloudflare_account_id') or '').strip() or None
    
    # save the webhook failsafe interval (6, 12, or 24 hours)
    webhook_failsafe = request.form.get('cloud_webhook_failsafe_hours')
    if webhook_failsafe and webhook_failsafe in ['6', '12', '24']:
        settings.cloud_webhook_failsafe_hours = int(webhook_failsafe)

    # the template sends external_tunnel_url, so prefer that name if it's there
    webhook_url = request.form.get('external_tunnel_url') or request.form.get('cloud_webhook_url')
    webhook_url = (webhook_url or '').strip()
    if 'cloud_webhook_secret' in request.form:
        if 'cloud_webhook_secret_unchanged' in request.form:
            pass  # keep existing
        else:
            v = (request.form.get('cloud_webhook_secret') or '').strip()
            if v:
                settings.cloud_webhook_secret = v
            else:
                settings.cloud_webhook_secret = None
    settings.cloud_webhook_url = webhook_url or None
    webhook_secret = (settings.cloud_webhook_secret or '').strip()  # used by register_webhook below

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
        # only hit the cloud when we actually have a webhook URL to sync
        # if the user left it blank, don't show a fake webhook failure
        if webhook_url:
            if CloudService.register_webhook(settings, webhook_url, webhook_secret):
                flash("Cloud settings updated successfully", "success")
            else:
                flash("Cloud settings saved, but webhook registration failed (check API key and network).", "warning")
        else:
            flash("Cloud settings updated successfully", "success")
    else:
        flash("Cloud settings updated successfully", "success")

    return redirect(url_for('web_requests.requests_settings_page'))

@web_requests_bp.route('/approve_request/<int:req_id>', methods=['POST'])
@login_required
def approve_request(req_id):
    """Approve a cloud request and send to Radarr/Sonarr"""
    req = _get_owned_cloud_request_or_404(req_id)
    settings = _get_current_settings()

    # Execute the download logic (sends to Radarr/Sonarr)
    if CloudService.process_item(settings, req):
        flash(f"Approved and sent: {req.title}", "success")
    else:
        flash(f"Failed to send {req.title}. Check system logs.", "error")

    return redirect(url_for('web_requests.requests_page'))

@web_requests_bp.route('/deny_request/<int:req_id>', methods=['POST'])
@login_required
def deny_request(req_id):
    """Deny a cloud request"""
    req = _get_owned_cloud_request_or_404(req_id)
    req.status = 'denied'
    db.session.commit()

    # tell the cloud so it stops showing as pending there too
    deny_cloud_ok = True
    if req.cloud_id:
        try:
            settings = _get_current_settings()
            if settings and settings.cloud_api_key:
                base = CloudService.get_cloud_base_url(settings)
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
        except Exception:
            deny_cloud_ok = False
            print("Warning: Could not acknowledge deny to cloud")

    if not deny_cloud_ok:
        flash(f"Denied locally but could not update SeekAndWatch Cloud (check API key in Requests Settings). It may still show as Pending on the web.", "warning")
    else:
        flash(f"Denied request: {req.title}", "warning")
    return redirect(url_for('web_requests.requests_page'))
    
@web_requests_bp.route('/delete_request/<int:req_id>', methods=['POST'])
@login_required
def delete_request(req_id):
    """Delete a request locally AND tell the Cloud to remove it."""
    req = _get_owned_cloud_request_or_404(req_id)
    title = req.title  # keep for the flash message
    
    # tell the cloud to delete it too
    # if this came from the cloud, delete it there first
    cloud_id_val = (str(req.cloud_id).strip() if req.cloud_id else None) or None
    cloud_delete_ok = True
    cloud_delete_404_id = None
    cloud_delete_error_detail = None  # e.g. "415: Content-Type must be application/json"
    if cloud_id_val:
        try:
            settings = _get_current_settings()
            if settings and settings.cloud_api_key:
                base = CloudService.get_cloud_base_url(settings)
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
        except Exception:
            cloud_delete_ok = False
            cloud_delete_error_detail = "request failed (check network or API key)"
            print("Warning: Could not delete from cloud")

    # Record deletion so we don't re-import from cloud
    if cloud_id_val:
        try:
            if not DeletedCloudId.query.filter_by(cloud_id=cloud_id_val).first():
                db.session.add(DeletedCloudId(cloud_id=cloud_id_val))
                db.session.flush()
        except Exception:
            pass  # table may not exist yet on old installs
    
    # delete locally
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
    except Exception:
        db.session.rollback()
        flash("Error deleting request", "error")
        
    return redirect(url_for('web_requests.requests_page'))
