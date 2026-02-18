import os
import json
import requests
import time
import random
from datetime import datetime
from app import app, db
from models import Settings, CloudRequest, AppRequest, DeletedCloudId

# cloud processing uses these (defined in utils.py only; api.py has HTTP endpoints, not these helpers)
from config import CONFIG_DIR, CLOUD_REQUEST_TIMEOUT, SCHEDULER_USER_ID, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX
from utils import get_cloud_base_url, send_to_radarr_sonarr, send_to_overseerr

CLOUD_IMPORT_LOG_FILE = os.path.join(CONFIG_DIR, 'cloud_import_log.json')
CLOUD_IMPORT_LOG_MAX = 50


def log_cloud_import(source, title, media_type, success=True):
    """Append one entry to the cloud import log (for Last 20 imported on requests settings page)."""
    try:
        entries = []
        if os.path.exists(CLOUD_IMPORT_LOG_FILE):
            try:
                with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
                    entries = json.load(f)
            except (json.JSONDecodeError, OSError):
                entries = []
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
    except Exception:
        pass


def get_cloud_import_log(limit=20):
    """Return the last N cloud import log entries (newest first)."""
    try:
        if not os.path.exists(CLOUD_IMPORT_LOG_FILE):
            return []
        with open(CLOUD_IMPORT_LOG_FILE, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        return (entries if isinstance(entries, list) else [])[:limit]
    except (json.JSONDecodeError, OSError):
        return []

# configuration (poll intervals from config or env overrides)
# After 429 we back off: next N cycles use interval * BACKOFF_MULT; then decay back to 1
BACKOFF_MULT_AFTER_429 = 2.0
BACKOFF_CYCLES = 3
BACKOFF_CAP_SEC = 300

# Global state
last_modified_header = None
backoff_remaining = 0  # cycles left to use longer sleep after 429
recommended_poll_interval_sec = 0  # set from X-Poll-Interval (legacy single value)
recommended_poll_interval_min_sec = 0  # set from X-Poll-Interval-Min when cloud sends min/max
recommended_poll_interval_max_sec = 0  # set from X-Poll-Interval-Max
last_webhook_received_at = 0.0  # time.time() when webhook was last received; poll backs off when recent

def set_last_webhook_received():
    """Call from webhook endpoint when a webhook (new_pending or approved) is received. Enables longer poll interval."""
    global last_webhook_received_at
    last_webhook_received_at = time.time()

def get_poll_sleep_seconds():
    """Return how many seconds to sleep before next poll (jitter + backoff + cloud recommendation). Use from app or __main__."""
    # When webhook URL is set, poll is only a backup: use 30-45 min and ignore user's min/max (600/900 etc.)
    try:
        with app.app_context():
            s = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first() if SCHEDULER_USER_ID is not None else None
            if s is None:
                s = Settings.query.first()
            webhook_url = (getattr(s, 'cloud_webhook_url', None) or '').strip()
            if s and webhook_url:
                base = random.randint(1800, 2700)  # 30-45 min when webhook is on
                if backoff_remaining > 0:
                    base = min(BACKOFF_CAP_SEC, int(base * BACKOFF_MULT_AFTER_429))
                return max(base, recommended_poll_interval_sec)
    except Exception:
        pass
    min_sec, max_sec = POLL_INTERVAL_MIN, POLL_INTERVAL_MAX
    try:
        with app.app_context():
            s = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first() if SCHEDULER_USER_ID is not None else None
            if s is None:
                s = Settings.query.first()
            user_min = getattr(s, 'cloud_poll_interval_min', None) if s else None
            user_max = getattr(s, 'cloud_poll_interval_max', None) if s else None
            if user_min is not None and user_max is not None and user_min >= 30:
                min_sec = max(30, user_min)
                max_sec = max(min_sec, user_max)
    except Exception:
        pass
    # Admin (cloud) min/max from X-Poll-Interval-Min/Max are a floor: user cannot go below, but can set higher
    if recommended_poll_interval_min_sec > 0 and recommended_poll_interval_max_sec >= recommended_poll_interval_min_sec:
        min_sec = max(min_sec, recommended_poll_interval_min_sec)
        max_sec = max(min_sec, max_sec, recommended_poll_interval_max_sec)
    base = random.randint(min_sec, max_sec)
    if backoff_remaining > 0:
        base = min(BACKOFF_CAP_SEC, int(base * BACKOFF_MULT_AFTER_429))
    return max(base, recommended_poll_interval_sec)

def process_item(settings, req_db):
    """
    Executes the request based on the specific handler settings for Movies vs TV.
    Returns True if successful, False otherwise.
    """
    success = False
    msg = ""

    # 1. Determine which handler to use based on media type
    handler_to_use = 'direct' # Default fallback
    
    if req_db.media_type == 'movie':
        handler_to_use = settings.cloud_movie_handler
    elif req_db.media_type == 'tv':
        handler_to_use = settings.cloud_tv_handler

    # 2. Execute based on the determined handler
    try:
        if handler_to_use == 'overseerr':
            # Send to Overseerr (Handles both movies and TV)
            success, msg = send_to_overseerr(settings, req_db.media_type, req_db.tmdb_id)
        else:
            # "Direct" means Radarr/Sonarr
            success, msg = send_to_radarr_sonarr(settings, req_db.media_type, req_db.tmdb_id)
    except Exception as e:
        msg = str(e)
        print(f"Error processing item: {msg}")

    # 3. Handle Result
    if success:
        req_db.status = 'completed'
        print(f"SUCCESS: Processed {req_db.title}")

        # so it shows on the Media -> Requested tab (that tab lists AppRequest + Overseerr)
        if settings and getattr(settings, 'user_id', None):
            requested_via = 'Overseerr' if handler_to_use == 'overseerr' else ('Radarr' if req_db.media_type == 'movie' else 'Sonarr')
            try:
                app_req = AppRequest(
                    user_id=settings.user_id,
                    tmdb_id=req_db.tmdb_id,
                    media_type=req_db.media_type,
                    title=req_db.title or 'Cloud Request',
                    requested_via=requested_via
                )
                db.session.add(app_req)
            except Exception as e:
                print(f"Warning: Could not add to Requested list: {e}")

        # Tell Cloud it's done so it doesn't show as pending there anymore (only if we have a cloud_id)
        cloud_ack_ok = True
        if req_db.cloud_id:
            try:
                base = get_cloud_base_url(settings)
                r = requests.post(
                    f"{base}/api/acknowledge.php",
                    headers={
                        'X-Server-Key': settings.cloud_api_key,
                        'Content-Type': 'application/json',
                    },
                    json={'request_id': str(req_db.cloud_id).strip(), 'status': 'completed'},
                    timeout=CLOUD_REQUEST_TIMEOUT
                )
                if r.status_code != 200:
                    cloud_ack_ok = False
                    print(f"Warning: Cloud acknowledge (approve) returned {r.status_code}: {r.text[:200]}")
            except requests.exceptions.Timeout:
                cloud_ack_ok = False
                print(f"Warning: Cloud acknowledge timed out after {CLOUD_REQUEST_TIMEOUT}s.")
            except Exception as e:
                cloud_ack_ok = False
                print(f"Warning: Could not acknowledge to cloud (Network issue?): {e}")
        else:
            cloud_ack_ok = False
        # Save changes to local DB
        db.session.commit()
        return (True, cloud_ack_ok)
    else:
        print(f"FAILED: Could not process {req_db.title} - {msg}")
        db.session.commit()
        return (False, False)


def add_pending_from_web(item):
    """
    Add or update a pending request from cloud webhook (event=new_pending).
    item is a dict with id, title, media_type, tmdb_id, year, requested_by, notes.
    Returns True if added/updated.
    """
    cloud_id = str((item.get('id') or '')).strip()
    if not cloud_id:
        return False
    existing = CloudRequest.query.filter_by(cloud_id=cloud_id).first()
    title = (item.get('title') or 'Request')[:255]
    media_type = (item.get('media_type') or 'movie')[:20]
    tmdb_id = int(item.get('tmdb_id') or 0)
    requested_by = (item.get('requested_by') or '')[:100]
    year_val = item.get('year')
    year_str = str(year_val)[:4] if year_val is not None else None
    notes = (item.get('notes') or '') if isinstance(item.get('notes'), str) else None
    if existing:
        existing.title = title
        existing.media_type = media_type
        existing.tmdb_id = tmdb_id
        existing.requested_by = requested_by
        existing.year = year_str
        existing.notes = notes
        existing.status = 'pending'
        db.session.commit()
        log_cloud_import('webhook_pending', title, media_type, True)
        return True
    req = CloudRequest(
        cloud_id=cloud_id,
        title=title,
        media_type=media_type,
        tmdb_id=tmdb_id,
        requested_by=requested_by,
        year=year_str,
        notes=notes,
        status='pending',
    )
    db.session.add(req)
    db.session.commit()
    log_cloud_import('webhook_pending', title, media_type, True)
    return True


def process_approved_from_web(settings, item, source='webhook_approved'):
    """
    Process an item that was approved on the web app: add to Radarr/Sonarr/Overseerr,
    then call mark_synced so the cloud stops returning it. item is a dict with id, title, media_type, tmdb_id, year, requested_by, notes.
    source: 'webhook_approved' when called from webhook, 'poll_approved' when from poll.
    Returns (success: bool, mark_synced_ok: bool).
    """
    cloud_id = str((item.get('id') or '')).strip()
    title = item.get('title') or 'Request'
    media_type = item.get('media_type') or 'movie'
    tmdb_id = item.get('tmdb_id') or 0
    handler_to_use = 'direct'
    if media_type == 'movie':
        handler_to_use = getattr(settings, 'cloud_movie_handler', None) or 'direct'
    elif media_type == 'tv':
        handler_to_use = getattr(settings, 'cloud_tv_handler', None) or 'direct'

    success = False
    try:
        if handler_to_use == 'overseerr':
            success, _ = send_to_overseerr(settings, media_type, tmdb_id)
        else:
            success, _ = send_to_radarr_sonarr(settings, media_type, tmdb_id)
    except Exception as e:
        print(f"Error processing approved item {title}: {e}")
        log_cloud_import(source, title, media_type, False)
        return (False, False)

    mark_synced_ok = False
    if success:
        log_cloud_import(source, title, media_type, True)
        print(f"SUCCESS: Added {title} (approved on web)")
        if settings and getattr(settings, 'user_id', None):
            requested_via = 'Overseerr' if handler_to_use == 'overseerr' else ('Radarr' if media_type == 'movie' else 'Sonarr')
            try:
                app_req = AppRequest(
                    user_id=settings.user_id,
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    title=title,
                    requested_via=requested_via
                )
                db.session.add(app_req)
                db.session.commit()
            except Exception as e:
                print(f"Warning: Could not add to Requested list: {e}")

        if cloud_id:
            try:
                base = get_cloud_base_url(settings)
                r = requests.post(
                    f"{base}/api/mark_synced.php",
                    headers={
                        'X-Server-Key': settings.cloud_api_key,
                        'Content-Type': 'application/json',
                    },
                    json={'request_id': cloud_id},
                    timeout=CLOUD_REQUEST_TIMEOUT
                )
                mark_synced_ok = (r.status_code == 200)
                if not mark_synced_ok:
                    print(f"Warning: mark_synced returned {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"Warning: Could not mark_synced: {e}")
    if not success:
        log_cloud_import(source, title, media_type, False)
    return (success, mark_synced_ok)


def sync_deletions(settings):
    """
    Checks the cloud for the 'Master List' of active requests.
    If we have a request locally that is NOT in the master list, delete it.
    Returns the response on success so caller can read X-Poll-Interval; None otherwise.
    """
    try:
        base = get_cloud_base_url(settings)
        headers = {'X-Server-Key': settings.cloud_api_key}
        response = requests.get(f"{base}/api/sync.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
        
        if response.status_code != 200:
            return None

        data = response.json()
        raw_ids = data.get('active_ids', [])
        # Normalize to strings: cloud requests.id is char(36) UUID; Python stores cloud_id as string
        active_cloud_ids = {str(i) for i in raw_ids}

        # Get all local requests that came from the cloud
        local_requests = CloudRequest.query.filter(CloudRequest.cloud_id.isnot(None)).all()

        deleted_count = 0
        for local_req in local_requests:
            # If the local request has a Cloud ID, but that ID is missing from the Cloud's active list...
            if str(local_req.cloud_id or '') not in active_cloud_ids:
                print(f"Sync: Removing '{local_req.title}' (It was deleted on Cloud)")
                db.session.delete(local_req)
                deleted_count += 1
        
        if deleted_count > 0:
            db.session.commit()

        return response
    except requests.exceptions.Timeout:
        print(f"Sync Warning: Cloud sync timed out after {CLOUD_REQUEST_TIMEOUT}s.")
        return None
    except Exception as e:
        print(f"Sync Warning: {e}")
        return None

def fetch_cloud_requests(settings):
    """
    On-demand sync + poll: fetch active list from cloud, remove local requests no longer on cloud,
    then poll for new pending requests and merge into local DB. Call from requests_page when user
    opens the Requests page. Returns (success: bool, message: str).
    """
    if not settings or not settings.cloud_enabled or not settings.cloud_api_key:
        return (False, "Cloud not configured. Add your API key in Requests Settings.")
    if not getattr(settings, 'cloud_sync_owned_enabled', True):
        return (False, "Cloud sync is disabled in Requests Settings.")

    try:
        # 1. Sync deletions: remove local requests that are no longer on the cloud
        sync_deletions(settings)

        # 2. Poll for new pending requests (no If-Modified-Since so we get fresh data)
        base = get_cloud_base_url(settings)
        headers = {'X-Server-Key': settings.cloud_api_key}
        response = requests.get(
            f"{base}/api/poll.php",
            headers=headers,
            timeout=CLOUD_REQUEST_TIMEOUT
        )

        if response.status_code == 304:
            return (True, "No new requests.")
        if response.status_code == 429:
            return (False, "Rate limited. Try again in a minute.")
        if response.status_code == 401:
            return (False, "Invalid API key. Check Requests Settings.")
        if response.status_code != 200:
            return (False, f"Cloud returned {response.status_code}. Try again.")

        try:
            data = response.json()
        except ValueError:
            return (False, "Cloud returned invalid data. Try again.")

        approved_list = data.get('approved_to_sync', []) if isinstance(data, dict) else []
        synced_count = 0
        for item in (approved_list or []):
            ok, _ = process_approved_from_web(settings, item, source='poll_approved')
            if ok:
                synced_count += 1

        if synced_count > 0:
            return (True, f"Synced {synced_count} approved request(s).")
        return (True, "No approved items to sync.")
    except requests.exceptions.Timeout:
        return (False, "Cloud request timed out. Try again.")
    except requests.exceptions.ConnectionError:
        return (False, "Could not reach the cloud. Check your connection.")
    except Exception:
        return (False, "Could not sync with the cloud. Check your internet connection and that your API key in Requests Settings is correct.")


def _record_last_poll(settings, ok):
    """Update last_cloud_poll_at and last_cloud_poll_ok for UI indicator."""
    if not settings:
        return
    try:
        settings.last_cloud_poll_at = datetime.utcnow()
        settings.last_cloud_poll_ok = ok
        db.session.commit()
    except Exception:
        pass


def process_cloud_queue():
    global last_modified_header, backoff_remaining, recommended_poll_interval_sec, recommended_poll_interval_min_sec, recommended_poll_interval_max_sec

    with app.app_context():
        # 1. Get Local Settings (use config user when set for multi-user isolation)
        if SCHEDULER_USER_ID is not None:
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
        else:
            settings = Settings.query.first()

        # Basic checks to see if we should run (cloud_sync_owned_enabled = "Enable Cloud API" in UI)
        if not settings or not settings.cloud_enabled or not settings.cloud_api_key or not settings.cloud_sync_owned_enabled:
            return

        base = get_cloud_base_url(settings)
        headers = {'X-Server-Key': settings.cloud_api_key}
        
        # OPTIMIZATION: Send If-Modified-Since if we have a previous timestamp
        if last_modified_header:
            headers['If-Modified-Since'] = last_modified_header
            
        # Do not log API key or any part of it (security: clear-text logging)
        
        # sync deletions (and pick up X-Poll-Interval from sync response if present)
        sync_response = sync_deletions(settings)
        if sync_response is not None:
            try:
                xi = int(sync_response.headers.get('X-Poll-Interval', 0) or 0)
                recommended_poll_interval_sec = max(0, min(300, xi))
                xmin = int(sync_response.headers.get('X-Poll-Interval-Min', 0) or 0)
                xmax = int(sync_response.headers.get('X-Poll-Interval-Max', 0) or 0)
                if xmin > 0 and xmax >= xmin:
                    recommended_poll_interval_min_sec = max(30, min(300, xmin))
                    recommended_poll_interval_max_sec = max(recommended_poll_interval_min_sec, min(300, xmax))
                else:
                    recommended_poll_interval_min_sec = 0
                    recommended_poll_interval_max_sec = 0
            except (ValueError, TypeError):
                pass

        try:
            # 2. Poll the Cloud for new Mail
            response = requests.get(f"{base}/api/poll.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
            
            # handle 304 (not modified)
            if response.status_code == 304:
                _record_last_poll(settings, True)
                try:
                    xi = int(response.headers.get('X-Poll-Interval', 0) or 0)
                    recommended_poll_interval_sec = max(0, min(300, xi))
                    xmin = int(response.headers.get('X-Poll-Interval-Min', 0) or 0)
                    xmax = int(response.headers.get('X-Poll-Interval-Max', 0) or 0)
                    if xmin > 0 and xmax >= xmin:
                        recommended_poll_interval_min_sec = max(30, min(300, xmin))
                        recommended_poll_interval_max_sec = max(recommended_poll_interval_min_sec, min(300, xmax))
                    else:
                        recommended_poll_interval_min_sec = 0
                        recommended_poll_interval_max_sec = 0
                except (ValueError, TypeError):
                    pass
                return

            # handle 429 (throttled), respect Retry-After and back off next cycles
            if response.status_code == 429:
                _record_last_poll(settings, False)
                retry_after = int(response.headers.get('Retry-After', 60))
                retry_after = min(max(1, retry_after), 300)
                backoff_remaining = BACKOFF_CYCLES
                print(f"Cloud throttle: waiting {retry_after}s (Retry-After). Next {BACKOFF_CYCLES} cycles will use longer intervals.")
                time.sleep(retry_after)
                return

            if response.status_code == 401:
                _record_last_poll(settings, False)
                print("Cloud Error: Invalid API Key. Please check your settings.")
                return
            elif response.status_code != 200:
                _record_last_poll(settings, False)
                print(f"Cloud Error: Server returned status {response.status_code}")
                return
            
            # If we got 200 OK, save the new Last-Modified header, decay backoff, and respect X-Poll-Interval (and Min/Max)
            if 'Last-Modified' in response.headers:
                last_modified_header = response.headers['Last-Modified']
            if backoff_remaining > 0:
                backoff_remaining -= 1
            try:
                xi = int(response.headers.get('X-Poll-Interval', 0) or 0)
                recommended_poll_interval_sec = max(0, min(300, xi))
                xmin = int(response.headers.get('X-Poll-Interval-Min', 0) or 0)
                xmax = int(response.headers.get('X-Poll-Interval-Max', 0) or 0)
                if xmin > 0 and xmax >= xmin:
                    recommended_poll_interval_min_sec = max(30, min(300, xmin))
                    recommended_poll_interval_max_sec = max(recommended_poll_interval_min_sec, min(300, xmax))
                else:
                    recommended_poll_interval_min_sec = 0
                    recommended_poll_interval_max_sec = 0
            except (ValueError, TypeError):
                recommended_poll_interval_sec = 0
                recommended_poll_interval_min_sec = 0
                recommended_poll_interval_max_sec = 0

            try:
                data = response.json()
            except ValueError:
                _record_last_poll(settings, False)
                print("Cloud Error: Non-JSON response received (response body not logged).")
                return

            # handle poll: approved_to_sync = items owner approved on web; add to Radarr/Sonarr and mark_synced
            approved_list = data.get('approved_to_sync', []) if isinstance(data, dict) else []
            for item in (approved_list or []):
                process_approved_from_web(settings, item, source='poll_approved')
            _record_last_poll(settings, True)

        except requests.exceptions.Timeout:
            _record_last_poll(settings, False)
            print(f"Cloud poll timed out after {CLOUD_REQUEST_TIMEOUT}s. Next cycle in {get_poll_sleep_seconds()}s.")
        except requests.exceptions.ConnectionError:
            _record_last_poll(settings, False)
            print("Network Error: Could not reach SeekAndWatch Cloud.")
        except Exception as e:
            _record_last_poll(settings, False)
            print(f"Worker Unexpected Error: {e}")

if __name__ == "__main__":
    print("Starting Cloud Worker...")
    with app.app_context():
        s = Settings.query.first()
        base = get_cloud_base_url(s) if s else "(not configured)"
        webhook_on = bool(s and (getattr(s, 'cloud_webhook_url', None) or '').strip())
    if webhook_on:
        print(f"Polling {base} (webhook on: backup poll every 30-45 min). Backoff after 429.")
    else:
        print(f"Polling {base} with jitter ({POLL_INTERVAL_MIN}-{POLL_INTERVAL_MAX}s). Backoff after 429.")
    while True:
        process_cloud_queue()
        time.sleep(get_poll_sleep_seconds())