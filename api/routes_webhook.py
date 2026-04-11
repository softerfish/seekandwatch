"""webhook routes - receive approved requests from cloud app with enhanced security"""

import hmac
import threading
import time
from flask import request, jsonify
from flask_login import login_required, current_user
from api import api_bp, rate_limit_decorator
from models import db, Settings, CloudRequest
from services.CloudService import CloudService
from services.Router import Router
from config import SCHEDULER_USER_ID
from utils.helpers import write_log

# webhook processing lock (prevents recovery during webhook processing)
_webhook_processing_count = 0
_webhook_lock = threading.Lock()

def _set_webhook_processing(delta):
    global _webhook_processing_count
    with _webhook_lock:
        _webhook_processing_count = max(0, _webhook_processing_count + delta)

def is_webhook_processing():
    """Check if webhook is currently being processed (used by recovery logic)"""
    with _webhook_lock:
        return _webhook_processing_count > 0

@api_bp.route(Router.LOCAL_WEBHOOK_PATH.replace('/api', ''), methods=['GET'])
@rate_limit_decorator("60 per hour")
def webhook_health_check():
    """health check endpoint for webhook connectivity testing (GET only)"""
    return jsonify({
        'status': 'ok',
        'message': 'Webhook endpoint is reachable',
        'methods': ['POST'],
        'app_running': True
    }), 200


@api_bp.route(Router.LOCAL_WEBHOOK_PATH.replace('/api', ''), methods=['POST'])
@rate_limit_decorator("10 per minute")
def receive_webhook():
    """receive webhook from cloud app"""
    # set processing flag to prevent recovery during webhook processing
    _set_webhook_processing(1)

    # log incoming request
    ip_address = request.remote_addr
    write_log("info", "Webhook", f"webhook request from {ip_address}")

    try:
        # verify secret (basic auth)
        provided_secret = request.headers.get('X-Webhook-Secret', '')
        if SCHEDULER_USER_ID is not None:
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
            if not settings:
                return jsonify({'error': 'configuration error'}), 500
            webhook_secret = getattr(settings, 'cloud_webhook_secret', None) or ''
            if not webhook_secret:
                return jsonify({'error': 'webhook not configured'}), 401
            secret_ok = hmac.compare_digest(provided_secret, webhook_secret)
        else:
            secret_ok = False
            settings = None
            if provided_secret:
                for candidate in Settings.query.filter(Settings.cloud_webhook_secret.isnot(None)).all():
                    candidate_secret = getattr(candidate, 'cloud_webhook_secret', None) or ''
                    if candidate_secret and hmac.compare_digest(provided_secret, candidate_secret):
                        settings = candidate
                        secret_ok = True
                        break
        if not secret_ok:
            write_log("error", "Webhook", f"invalid secret from {ip_address}")
            return jsonify({'error': 'invalid secret'}), 401

        # parse payload
        payload = request.get_json()
        if not payload:
            return jsonify({'error': 'invalid json'}), 400

        event = payload.get('event', '')
        requests_data = payload.get('requests', [])

        # also support singular 'request' for robustness
        if not requests_data and 'request' in payload:
            requests_data = [payload['request']]

        write_log("info", "Webhook", f"event: {event} ({len(requests_data)} items)")

        if event == 'test_connection':
            CloudService.log_webhook(event, payload, 'success', 'handshake test received', settings=settings)
            return jsonify({'status': 'success', 'message': 'test received'}), 200

        if not isinstance(requests_data, list):
            CloudService.log_webhook(event, payload, 'error', 'invalid requests format', settings=settings)
            return jsonify({'error': 'invalid requests format'}), 400

        # notify cloud worker that webhook was received (backs off polling)
        CloudService.set_last_webhook_received()

        # process approved requests
        if event == 'approved':
            import threading
            from flask import current_app

            # extract data first to avoid thread-safety issues with request object
            requests_to_process = []
            for req_data in requests_data:
                cloud_id = req_data.get('id', '')
                title = req_data.get('title', 'unknown')
                media_type = req_data.get('media_type', 'movie')
                tmdb_id = req_data.get('tmdb_id', 0)
                year = req_data.get('year')
                requested_by = req_data.get('requested_by', '')
                notes = req_data.get('notes', '')

                if not tmdb_id: continue

                # update/save to db immediately so it's tracked
                existing = CloudService._get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=True) if cloud_id else None
                if existing:
                    req_db = existing
                    req_db.title = title
                    req_db.media_type = media_type
                    req_db.tmdb_id = tmdb_id
                    req_db.year = year
                    req_db.requested_by = requested_by
                    req_db.notes = notes
                    req_db.status = 'pending'
                else:
                    req_db = CloudRequest(
                        owner_user_id=getattr(settings, 'user_id', None),
                        cloud_id=cloud_id,
                        title=title,
                        media_type=media_type,
                        tmdb_id=tmdb_id,
                        year=year,
                        requested_by=requested_by,
                        notes=notes,
                        status='pending'
                    )
                    db.session.add(req_db)

                requests_to_process.append(cloud_id)

            db.session.commit()

            CloudService.log_webhook(event, payload, 'success', f'queued {len(requests_to_process)} requests', settings=settings)

            # process in background
            def run_async_process(app_obj, ids, settings_user_id):
                _set_webhook_processing(1)
                with app_obj.app_context():
                    try:
                        # Re-fetch the exact settings row whose webhook secret matched.
                        s_obj = CloudService._get_settings_for_user(settings_user_id)
                        if not s_obj:
                            write_log("error", "Webhook", f"matched settings missing for user_id={settings_user_id}")
                            return
                        for cid in ids:
                            r = CloudService._get_cloud_request_by_cloud_id(s_obj, cid, claim_unowned=True)
                            if r:
                                if CloudService.process_item(s_obj, r):
                                    CloudService.log_cloud_import('webhook_approved', r.title, r.media_type, True, settings=s_obj)
                                else:
                                    CloudService.log_cloud_import('webhook_approved', r.title, r.media_type, False, settings=s_obj)
                    finally:
                        _set_webhook_processing(-1)

            threading.Thread(
                target=run_async_process,
                args=(current_app._get_current_object(), requests_to_process, getattr(settings, 'user_id', None)),
                daemon=True
            ).start()

            return jsonify({
                'success': True,
                'message': f'queued {len(requests_to_process)} requests for background processing'
            }), 200

        # handle other event types (new_pending, etc)
        elif event == 'new_pending':
            # just acknowledge, don't process (owner needs to approve first)
            processed_count = 0
            for req_data in requests_data:
                # add/update pending requests
                title = req_data.get('title', 'unknown')
                media_type = req_data.get('media_type', 'movie')
                cloud_id = req_data.get('id', '')
                existing = CloudService._get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=True) if cloud_id else None
                if not existing:
                    req_db = CloudRequest(
                        owner_user_id=getattr(settings, 'user_id', None),
                        cloud_id=cloud_id,
                        title=title,
                        media_type=media_type,
                        tmdb_id=req_data.get('tmdb_id', 0),
                        year=req_data.get('year'),
                        requested_by=req_data.get('requested_by', ''),
                        notes=req_data.get('notes', ''),
                        status='pending'
                    )
                    db.session.add(req_db)
                    db.session.commit()
                    CloudService.log_cloud_import('webhook_pending', title, media_type, True, settings=settings)
                    processed_count += 1

            CloudService.log_webhook(event, payload, 'success', f'received {processed_count} new pending requests', settings=settings)
            CloudService.set_last_webhook_received()
            return jsonify({'success': True, 'message': 'pending request notification received'}), 200

        else:
            CloudService.log_webhook(event, payload, 'filtered', f'unknown event type: {event}', settings=settings)
            return jsonify({'error': f'unknown event type: {event}'}), 400

    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        write_log("error", "Webhook", f"webhook error: {str(e)}")
        try:
            # try to log the failure if possible
            CloudService.log_webhook('error', request.get_data(as_text=True), 'error', str(e), settings=settings if 'settings' in locals() else None)
        except: pass
        return jsonify({'error': 'internal server error'}), 500

    finally:
        # clear processing flag
        _set_webhook_processing(-1)

@api_bp.route('/webhook/clear_logs', methods=['POST'])
@login_required
def clear_webhook_logs():
    """clear all webhook logs from the database"""
    try:
        from models import WebhookLog
        db.session.query(WebhookLog).delete()
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("webhook/clear_logs")
        return jsonify({'status': 'error', 'message': 'Failed to clear webhook logs'}), 500

@api_bp.route('/webhook/toggle_quiet_mode', methods=['POST'])
@login_required
def toggle_webhook_quiet_mode():
    """toggle quiet mode for webhook logs"""
    try:
        s = current_user.settings
        if not s:
            return jsonify({'status': 'error', 'message': 'Settings not found'}), 404

        # handle case where column might not exist yet (shouldn't happen but be safe)
        current_value = getattr(s, 'quiet_webhook_logs', False)
        s.quiet_webhook_logs = not current_value
        db.session.commit()

        return jsonify({
            'status': 'success',
            'quiet_mode': s.quiet_webhook_logs
        })
    except Exception:
        db.session.rollback()
        from api.helpers import _log_api_exception
        _log_api_exception("webhook/toggle_quiet_mode")
        return jsonify({'status': 'error', 'message': 'Failed to toggle quiet mode'}), 500
