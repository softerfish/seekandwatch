"""
CloudService - Handles all communication with SeekAndWatch Cloud.
Manages pairing, webhooks, polling, and synchronization of requests.
"""

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

log = logging.getLogger(__name__)

CLOUD_IMPORT_LOG_FILE = os.path.join(CONFIG_DIR, 'cloud_import_log.json')
CLOUD_IMPORT_LOG_MAX = 50

# Global state for polling (moved from cloud_worker.py)
_last_modified_header = None
_backoff_remaining = 0
_recommended_poll_interval_sec = 0
_recommended_poll_interval_min_sec = 0
_recommended_poll_interval_max_sec = 0
_last_webhook_received_at = 0.0

class CloudService:
    @staticmethod
    def get_cloud_base_url(settings=None):
        """Return the Cloud base URL."""
        if settings and getattr(settings, 'cloud_base_url', None):
            return settings.cloud_base_url.rstrip('/')
        return CLOUD_URL

    @staticmethod
    def log_cloud_import(source, title, media_type, success=True):
        """Log a cloud import event to a local JSON file."""
        try:
            entries = []
            if os.path.exists(CLOUD_IMPORT_LOG_FILE):
                try:
                    with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
                        entries = json.load(f)
                except: entries = []
            
            entries.insert(0, {
                'at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'source': source,
                'title': (title or '')[:200],
                'media_type': media_type or 'movie',
                'success': bool(success),
            })
            entries = entries[:CLOUD_IMPORT_LOG_MAX]
            with open(CLOUD_IMPORT_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(entries, f, indent=0)
        except: pass

    @staticmethod
    def get_cloud_import_log(limit=20):
        """Fetch the local cloud import log."""
        try:
            if not os.path.exists(CLOUD_IMPORT_LOG_FILE): return []
            with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
                entries = json.load(f)
            return (entries if isinstance(entries, list) else [])[:limit]
        except: return []

    @staticmethod
    def set_last_webhook_received():
        global _last_webhook_received_at
        _last_webhook_received_at = time.time()

    @staticmethod
    def register_webhook(settings, webhook_url, webhook_secret=None):
        """Registers a webhook URL with the web app."""
        if not settings or not settings.cloud_api_key: return False
        
        try:
            base = CloudService.get_cloud_base_url(settings)
            resp = requests.post(
                f"{base}/api/register_webhook.php",
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
        """Process a single cloud request item."""
        print(f"DEBUG: Processing {req_db.media_type} '{req_db.title}' (TMDB: {req_db.tmdb_id})", flush=True)
        handler = 'direct'
        if req_db.media_type == 'movie':
            handler = settings.cloud_movie_handler
        elif req_db.media_type == 'tv':
            handler = settings.cloud_tv_handler

        success = False
        try:
            if handler == 'overseerr':
                success, msg = IntegrationsService.send_to_overseerr(settings, req_db.media_type, req_db.tmdb_id)
            else:
                success, msg = IntegrationsService.send_to_radarr_sonarr(settings, req_db.media_type, req_db.tmdb_id)
        except Exception:
            log.error("Process item failed")
            msg = "An error occurred during processing"

        if success:
            req_db.status = 'completed'
            # Add to local requested list
            try:
                app_req = AppRequest(
                    user_id=settings.user_id,
                    tmdb_id=req_db.tmdb_id,
                    media_type=req_db.media_type,
                    title=req_db.title or 'Cloud Request',
                    requested_via='Overseerr' if handler == 'overseerr' else ('Radarr' if req_db.media_type == 'movie' else 'Sonarr')
                )
                db.session.add(app_req)
            except: pass

            # Acknowledge to cloud
            if req_db.cloud_id:
                try:
                    base = CloudService.get_cloud_base_url(settings)
                    requests.post(
                        f"{base}/api/acknowledge.php",
                        headers={'X-Server-Key': settings.cloud_api_key, 'Content-Type': 'application/json'},
                        json={'request_id': str(req_db.cloud_id), 'status': 'completed'},
                        timeout=CLOUD_REQUEST_TIMEOUT
                    )
                except: pass
            db.session.commit()
            return True
        return False

    @staticmethod
    def fetch_cloud_requests(settings):
        """On-demand sync triggered by user opening the Requests page."""
        if not settings or not settings.cloud_enabled or not settings.cloud_api_key:
            return False, "Cloud not configured."
        
        try:
            CloudService.sync_deletions(settings)
            base = CloudService.get_cloud_base_url(settings)
            resp = requests.get(f"{base}/api/poll.php", headers={'X-Server-Key': settings.cloud_api_key}, timeout=CLOUD_REQUEST_TIMEOUT)
            
            if resp.status_code != 200: return False, f"Cloud error: {resp.status_code}"
            
            data = resp.json()
            approved = data.get('approved_to_sync', [])
            count = 0
            for item in approved:
                cloud_id = item.get('id')
                if not CloudRequest.query.filter_by(cloud_id=cloud_id).first():
                    req_db = CloudRequest(cloud_id=cloud_id, title=item.get('title'), media_type=item.get('media_type'), tmdb_id=item.get('tmdb_id'), status='pending')
                    db.session.add(req_db)
                    db.session.commit()
                    if CloudService.process_item(settings, req_db):
                        count += 1
                        CloudService.log_cloud_import('poll_manual', item.get('title'), item.get('media_type'), True)
            
            return True, f"Synced {count} requests."
        except Exception:
            return False, "Failed to fetch cloud requests"

    @staticmethod
    def sync_deletions(settings):
        """Syncs local request state with Cloud master list."""
        try:
            base = CloudService.get_cloud_base_url(settings)
            headers = {'X-Server-Key': settings.cloud_api_key}
            resp = requests.get(f"{base}/api/sync.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
            if resp.status_code != 200: return resp

            active_ids = {str(i) for i in resp.json().get('active_ids', [])}
            local_reqs = CloudRequest.query.filter(CloudRequest.cloud_id.isnot(None)).all()
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
        """Main background polling task."""
        global _last_modified_header, _backoff_remaining, _recommended_poll_interval_sec
        global _recommended_poll_interval_min_sec, _recommended_poll_interval_max_sec

        with app_obj.app_context():
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first() if SCHEDULER_USER_ID else Settings.query.first()
            if not settings or not settings.cloud_enabled or not settings.cloud_api_key or not settings.cloud_sync_owned_enabled:
                return

            # Skip polling if webhook was received very recently
            if time.time() - _last_webhook_received_at < 300: # 5 min
                return

            base = CloudService.get_cloud_base_url(settings)
            headers = {'X-Server-Key': settings.cloud_api_key}
            if _last_modified_header: headers['If-Modified-Since'] = _last_modified_header

            # Sync deletions and get interval recommendations
            sync_resp = CloudService.sync_deletions(settings)
            if sync_resp:
                try:
                    _recommended_poll_interval_sec = int(sync_resp.headers.get('X-Poll-Interval', 0))
                except: pass

            try:
                resp = requests.get(f"{base}/api/poll.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
                
                if resp.status_code == 304: return
                if resp.status_code == 429:
                    _backoff_remaining = 3
                    return
                if resp.status_code != 200: return

                if 'Last-Modified' in resp.headers: _last_modified_header = resp.headers['Last-Modified']
                
                data = resp.json()
                approved = data.get('approved_to_sync', [])
                for item in approved:
                    # Logic to process approved items from poll
                    title = item.get('title', 'Unknown')
                    media_type = item.get('media_type', 'movie')
                    tmdb_id = item.get('tmdb_id')
                    
                    cloud_id = item.get('id')
                    existing = CloudRequest.query.filter_by(cloud_id=cloud_id).first()
                    if not existing:
                        req_db = CloudRequest(cloud_id=cloud_id, title=title, media_type=media_type, tmdb_id=tmdb_id, status='pending')
                        db.session.add(req_db)
                        db.session.commit()
                        CloudService.process_item(settings, req_db)
                        CloudService.log_cloud_import('poll_approved', title, media_type, True)

            except Exception:
                log.error("Cloud poll failed")
