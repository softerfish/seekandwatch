import os
import json
import logging
import requests
import time
import random
from datetime import datetime
from flask import current_app

from models import db, Settings, CloudRequest, AppRequest, DeletedCloudId
from config import CONFIG_DIR, CLOUD_REQUEST_TIMEOUT, SCHEDULER_USER_ID, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, CLOUD_URL
from services.IntegrationsService import IntegrationsService
from services.Router import Router
from utils.helpers import write_log

log = logging.getLogger(__name__)

CLOUD_IMPORT_LOG_FILE = os.path.join(CONFIG_DIR, 'cloud_import_log.json')
CLOUD_IMPORT_LOG_MAX = 50

# global poll state
_last_modified_header = None
_backoff_remaining = 0
_recommended_poll_interval_sec = 0
_recommended_poll_interval_min_sec = 0
_recommended_poll_interval_max_sec = 0
_last_webhook_received_at = 0.0
_next_poll_not_before = 0.0

class CloudService:
    @staticmethod
    def _get_default_settings():
        if SCHEDULER_USER_ID is not None:
            return Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
        return Settings.query.first()

    @staticmethod
    def _get_settings_for_user(user_id):
        if user_id is None:
            return None
        return Settings.query.filter_by(user_id=user_id).first()

    @staticmethod
    def _get_cloud_request_query(settings):
        query = CloudRequest.query
        owner_user_id = getattr(settings, 'user_id', None) if settings else None
        if owner_user_id is not None and hasattr(CloudRequest, 'owner_user_id'):
            query = query.filter_by(owner_user_id=owner_user_id)
        return query

    @staticmethod
    def _get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=False):
        if not cloud_id:
            return None
        req_db = CloudService._get_cloud_request_query(settings).filter_by(cloud_id=cloud_id).first()
        if req_db is not None or not claim_unowned or not hasattr(CloudRequest, 'owner_user_id'):
            return req_db

        req_db = CloudRequest.query.filter_by(cloud_id=cloud_id, owner_user_id=None).first()
        if req_db is not None:
            req_db.owner_user_id = getattr(settings, 'user_id', None)
        return req_db

    @staticmethod
    def _upsert_cloud_request(settings, cloud_id, **fields):
        if not cloud_id:
            return None
        req_db = CloudService._get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=True)
        if req_db is None:
            req_db = CloudRequest(cloud_id=cloud_id)
            if hasattr(req_db, 'owner_user_id'):
                req_db.owner_user_id = getattr(settings, 'user_id', None)
            db.session.add(req_db)
        for key, value in fields.items():
            setattr(req_db, key, value)
        return req_db

    @staticmethod
    def _apply_poll_headers(settings, resp):
        global _recommended_poll_interval_sec, _recommended_poll_interval_min_sec
        global _recommended_poll_interval_max_sec, _next_poll_not_before, _backoff_remaining

        def _read_int_header(name):
            try:
                value = int(resp.headers.get(name, 0))
            except (TypeError, ValueError):
                return 0
            return max(0, min(300, value))

        _recommended_poll_interval_sec = _read_int_header('X-Poll-Interval')
        _recommended_poll_interval_min_sec = _read_int_header('X-Poll-Interval-Min')
        _recommended_poll_interval_max_sec = _read_int_header('X-Poll-Interval-Max')

        interval_min = getattr(settings, 'cloud_poll_interval_min', None) or _recommended_poll_interval_min_sec or POLL_INTERVAL_MIN
        interval_max = getattr(settings, 'cloud_poll_interval_max', None) or _recommended_poll_interval_max_sec or POLL_INTERVAL_MAX
        interval_min = max(0, interval_min)
        interval_max = max(interval_min, interval_max)

        chosen_interval = _recommended_poll_interval_sec or interval_min
        chosen_interval = max(interval_min, min(interval_max, chosen_interval))
        if chosen_interval > 0:
            _next_poll_not_before = time.time() + chosen_interval
            _backoff_remaining = 0

    @staticmethod
    def log_webhook(event, payload, status, message=None, settings=None):
        try:
            from models import WebhookLog, Settings
            from config import SCHEDULER_USER_ID
            
            settings = settings or CloudService._get_default_settings()
            
            if settings and getattr(settings, 'quiet_webhook_logs', False) and status == 'success':
                return

            new_log = WebhookLog(
                event=event,
                payload=json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload),
                status=status,
                message=message
            )
            db.session.add(new_log)
            db.session.commit()
            
            max_logs = 100
            if settings and getattr(settings, 'max_webhook_logs', None):
                max_logs = max(10, min(1000, settings.max_webhook_logs))

            try:
                old_logs = WebhookLog.query.order_by(WebhookLog.timestamp.desc()).offset(max_logs).all()
                if old_logs:
                    for old_log in old_logs:
                        db.session.delete(old_log)
                    db.session.commit()
            except: pass
        except Exception as e:
            log.error(f"Failed to log webhook: {str(e)}")

    @staticmethod
    def get_cloud_base_url(settings=None):
        if settings and getattr(settings, 'cloud_base_url', None):
            return settings.cloud_base_url.rstrip('/')
        return CLOUD_URL

    @staticmethod
    def _describe_import_delivery(settings, source):
        source = (source or '').strip().lower()
        if source.startswith('webhook'):
            if not settings:
                return 'Webhook (legacy)'
            provider = (getattr(settings, 'tunnel_provider', None) or '').strip().lower() if settings else ''
            tunnel_name = (getattr(settings, 'tunnel_name', None) or '').strip().lower() if settings else ''
            if provider == 'external':
                return 'External'
            if provider == 'cloudflare':
                if tunnel_name == 'quick-tunnel':
                    return 'Quick Tunnel'
                if tunnel_name == 'named-tunnel':
                    return 'Named Tunnel'
                return 'Cloudflare Tunnel'
            if provider == 'ngrok':
                return 'ngrok'
            return 'Webhook'
        if source == 'poll_approved':
            return 'Poll fallback'
        if source == 'poll_manual':
            return 'Manual poll'
        return (source or 'unknown').replace('_', ' ').title()

    @staticmethod
    def _describe_import_source(source):
        source = (source or '').strip().lower()
        if source in ('webhook_approved', 'poll_approved', 'poll_manual'):
            return 'Approved'
        if source == 'webhook_pending':
            return 'Pending'
        if 'denied' in source or 'failed' in source:
            return 'Denied'
        return (source or 'unknown').replace('_', ' ').title()

    @staticmethod
    def log_cloud_import(source, title, media_type, success=True, settings=None):
        try:
            source = (source or '').strip().lower()
            if source == 'webhook_pending':
                return

            entries = []
            if os.path.exists(CLOUD_IMPORT_LOG_FILE):
                try:
                    with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
                        entries = json.load(f)
                except: entries = []
            
            entries.insert(0, {
                'at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'source': source,
                'source_label': CloudService._describe_import_source(source),
                'delivery': CloudService._describe_import_delivery(settings, source),
                'title': (title or '')[:200],
                'media_type': media_type or 'movie',
                'success': bool(success),
            })
            entries = entries[:CLOUD_IMPORT_LOG_MAX]
            with open(CLOUD_IMPORT_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(entries, f, indent=0)
        except: pass

    @staticmethod
    def get_cloud_import_log(limit=20, settings=None):
        try:
            if not os.path.exists(CLOUD_IMPORT_LOG_FILE): return []
            with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
                entries = json.load(f)
            entries = (entries if isinstance(entries, list) else [])
            entries = [
                entry for entry in entries
                if not (isinstance(entry, dict) and (entry.get('source') or '').strip().lower() == 'webhook_pending')
            ][:limit]
            for entry in entries:
                if isinstance(entry, dict):
                    if not entry.get('delivery'):
                        entry['delivery'] = CloudService._describe_import_delivery(None, entry.get('source'))
                    if not entry.get('source_label'):
                        entry['source_label'] = CloudService._describe_import_source(entry.get('source'))
            return entries
        except: return []

    @staticmethod
    def set_last_webhook_received():
        global _last_webhook_received_at
        _last_webhook_received_at = time.time()

    @staticmethod
    def register_webhook(settings, webhook_url, webhook_secret=None):
        if not settings or not settings.cloud_api_key: return False
        
        try:
            base = CloudService.get_cloud_base_url(settings)
            resp = requests.post(
                Router.get_cloud_url(base, Router.CLOUD_REGISTER_WEBHOOK),
                headers={
                    'X-Server-Key': settings.cloud_api_key,
                    'Content-Type': 'application/json',
                },
                json={
                    'webhook_url': webhook_url or '',
                    'webhook_secret': webhook_secret or settings.cloud_webhook_secret or '',
                },
                timeout=CLOUD_REQUEST_TIMEOUT
            )
            return resp.status_code == 200
        except Exception:
            log.error("Webhook registration failed")
            return False

    @staticmethod
    def process_item(settings, req_db):
        write_log("info", "Cloud", f"Processing {req_db.media_type} '{req_db.title}' (TMDB: {req_db.tmdb_id})")
        handler = 'direct'
        if req_db.media_type == 'movie':
            handler = settings.cloud_movie_handler
        elif req_db.media_type == 'tv':
            handler = settings.cloud_tv_handler
        
        write_log("info", "Cloud", f"Using handler '{handler}' for {req_db.media_type}")

        success = False
        try:
            success, msg = IntegrationsService.send_to_radarr_sonarr(settings, req_db.media_type, req_db.tmdb_id)
        except Exception as e:
            import traceback
            write_log("error", "Cloud", f"Process item failed: {str(e)}")
            msg = f"An error occurred during processing: {str(e)}"

        if success:
            req_db.status = 'completed'
            try:
                app_req = AppRequest(
                    user_id=settings.user_id,
                    tmdb_id=req_db.tmdb_id,
                    media_type=req_db.media_type,
                    title=req_db.title or 'Cloud Request',
                    requested_via='Radarr' if req_db.media_type == 'movie' else 'Sonarr'
                )
                db.session.add(app_req)
            except: pass

            if req_db.cloud_id:
                try:
                    base = CloudService.get_cloud_base_url(settings)
                    requests.post(
                        Router.get_cloud_url(base, Router.CLOUD_ACKNOWLEDGE),
                        headers={'X-Server-Key': settings.cloud_api_key, 'Content-Type': 'application/json'},
                        json={'request_id': str(req_db.cloud_id), 'status': 'completed'},
                        timeout=CLOUD_REQUEST_TIMEOUT
                    )
                except: pass
                try:
                    requests.post(
                        Router.get_cloud_url(base, Router.CLOUD_MARK_SYNCED),
                        headers={'X-Server-Key': settings.cloud_api_key, 'Content-Type': 'application/json'},
                        json={'request_id': str(req_db.cloud_id)},
                        timeout=CLOUD_REQUEST_TIMEOUT
                    )
                except Exception:
                    log.warning("Mark synced failed for cloud request %s", req_db.cloud_id)
            db.session.commit()
            return True
        
        write_log("error", "Cloud", f"process_item failed: {msg}")
        return False

    @staticmethod
    def fetch_cloud_requests(settings):
        if not settings or not settings.cloud_enabled or not settings.cloud_api_key:
            return False, "Cloud not configured."
        
        try:
            CloudService.sync_deletions(settings)
            base = CloudService.get_cloud_base_url(settings)
            resp = requests.get(
                Router.get_cloud_url(base, Router.CLOUD_POLL), 
                headers={'X-Server-Key': settings.cloud_api_key}, 
                timeout=CLOUD_REQUEST_TIMEOUT
            )
            
            if resp.status_code != 200: return False, f"Cloud error: {resp.status_code}"
            
            data = resp.json()
            approved = data.get('approved_to_sync', [])
            count = 0
            CloudService._apply_poll_headers(settings, resp)
            for item in approved:
                cloud_id = item.get('id')
                if not CloudService._get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=True):
                    req_db = CloudService._upsert_cloud_request(
                        settings,
                        cloud_id,
                        title=item.get('title'),
                        media_type=item.get('media_type'),
                        tmdb_id=item.get('tmdb_id'),
                        requested_by=item.get('requested_by'),
                        year=item.get('year'),
                        notes=item.get('notes'),
                        status='pending',
                    )
                    db.session.add(req_db)
                    db.session.commit()
                    if CloudService.process_item(settings, req_db):
                        count += 1
                        CloudService.log_cloud_import('poll_manual', item.get('title'), item.get('media_type'), True, settings=settings)
            
            return True, f"Synced {count} requests."
        except Exception:
            return False, "Failed to fetch cloud requests"

    @staticmethod
    def sync_deletions(settings):
        try:
            base = CloudService.get_cloud_base_url(settings)
            headers = {'X-Server-Key': settings.cloud_api_key}
            resp = requests.get(
                Router.get_cloud_url(base, Router.CLOUD_SYNC), 
                headers=headers, 
                timeout=CLOUD_REQUEST_TIMEOUT
            )
            if resp.status_code != 200: return resp
            CloudService._apply_poll_headers(settings, resp)

            active_ids = {str(i) for i in resp.json().get('active_ids', [])}
            local_reqs = CloudService._get_cloud_request_query(settings).filter(CloudRequest.cloud_id.isnot(None)).all()
            deleted = 0
            for req in local_reqs:
                if str(req.cloud_id) not in active_ids:
                    db.session.delete(req)
                    deleted += 1
            if deleted: db.session.commit()
            return resp
        except: return None

    @staticmethod
    def process_cloud_queue(app_obj):
        global _last_modified_header, _backoff_remaining, _recommended_poll_interval_sec
        global _recommended_poll_interval_min_sec, _recommended_poll_interval_max_sec, _next_poll_not_before

        with app_obj.app_context():
            settings = CloudService._get_default_settings()
            if not settings or not settings.cloud_enabled or not settings.cloud_api_key or not settings.cloud_sync_owned_enabled:
                return

            now = time.time()
            if _backoff_remaining > 0:
                _backoff_remaining -= 1
                return

            if _next_poll_not_before > now:
                return

            # let recent webhooks settle before polling
            if now - _last_webhook_received_at < 300: # 5 min
                return

            base = CloudService.get_cloud_base_url(settings)
            headers = {'X-Server-Key': settings.cloud_api_key}
            if _last_modified_header: headers['If-Modified-Since'] = _last_modified_header

            # polling also keeps deletions and interval hints in sync
            sync_resp = CloudService.sync_deletions(settings)
            try:
                resp = requests.get(
                    Router.get_cloud_url(base, Router.CLOUD_POLL), 
                    headers=headers, 
                    timeout=CLOUD_REQUEST_TIMEOUT
                )

                settings.last_cloud_poll_at = datetime.utcnow()
                if resp.status_code == 304:
                    settings.last_cloud_poll_ok = True
                    CloudService._apply_poll_headers(settings, resp)
                    db.session.commit()
                    return
                if resp.status_code == 429:
                    _backoff_remaining = 3
                    settings.last_cloud_poll_ok = False
                    db.session.commit()
                    return
                if resp.status_code != 200:
                    settings.last_cloud_poll_ok = False
                    db.session.commit()
                    return

                if 'Last-Modified' in resp.headers: _last_modified_header = resp.headers['Last-Modified']
                CloudService._apply_poll_headers(settings, resp)
                settings.last_cloud_poll_ok = True
                db.session.commit()
                
                data = resp.json()
                approved = data.get('approved_to_sync', [])
                for item in approved:
                    # only import approved items from poll
                    title = item.get('title', 'unknown')
                    media_type = item.get('media_type', 'movie')
                    tmdb_id = item.get('tmdb_id')
                    
                    cloud_id = item.get('id')
                    existing = CloudService._get_cloud_request_by_cloud_id(settings, cloud_id, claim_unowned=True)
                    if not existing:
                        req_db = CloudService._upsert_cloud_request(
                            settings,
                            cloud_id,
                            title=title,
                            media_type=media_type,
                            tmdb_id=tmdb_id,
                            requested_by=item.get('requested_by'),
                            year=item.get('year'),
                            notes=item.get('notes'),
                            status='pending',
                        )
                        db.session.add(req_db)
                        db.session.commit()
                        CloudService.process_item(settings, req_db)
                        CloudService.log_cloud_import('poll_approved', title, media_type, True, settings=settings)

            except Exception:
                try:
                    settings.last_cloud_poll_at = datetime.utcnow()
                    settings.last_cloud_poll_ok = False
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                log.error("Cloud poll failed")
