import requests
import time
import random
from datetime import datetime
from app import app, db
from models import Settings, CloudRequest, AppRequest, DeletedCloudId

# cloud processing uses these (defined in utils.py only; api.py has HTTP endpoints, not these helpers)
from config import CLOUD_URL, CLOUD_REQUEST_TIMEOUT, SCHEDULER_USER_ID
from utils import send_to_radarr_sonarr, send_to_overseerr

# CONFIGURATION
# Base interval ranges (jitter between these so installs don't all hit at once)
POLL_INTERVAL_MIN = 75
POLL_INTERVAL_MAX = 120
# After 429 we back off: next N cycles use interval * BACKOFF_MULT; then decay back to 1
BACKOFF_MULT_AFTER_429 = 2.0
BACKOFF_CYCLES = 3
BACKOFF_CAP_SEC = 300

# Global state
last_modified_header = None
backoff_remaining = 0  # cycles left to use longer sleep after 429
recommended_poll_interval_sec = 0  # set from X-Poll-Interval when cloud suggests longer interval (e.g. high traffic)


def get_poll_sleep_seconds():
    """Return how many seconds to sleep before next poll (jitter + backoff + cloud recommendation). Use from app or __main__."""
    base = random.randint(POLL_INTERVAL_MIN, POLL_INTERVAL_MAX)
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

        # so it shows on the Media → Requested tab (that tab lists AppRequest + Overseerr)
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
                r = requests.post(
                    f"{CLOUD_URL}/api/acknowledge.php",
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

def sync_deletions(settings):
    """
    Checks the cloud for the 'Master List' of active requests.
    If we have a request locally that is NOT in the master list, delete it.
    Returns the response on success so caller can read X-Poll-Interval; None otherwise.
    """
    try:
        headers = {'X-Server-Key': settings.cloud_api_key}
        response = requests.get(f"{CLOUD_URL}/api/sync.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
        
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
        headers = {'X-Server-Key': settings.cloud_api_key}
        response = requests.get(
            f"{CLOUD_URL}/api/poll.php",
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

        requests_list = []
        if isinstance(data, list):
            requests_list = data
        elif isinstance(data, dict):
            if data.get('error'):
                return (False, data.get('error', "Cloud error."))
            requests_list = data.get('pending_requests', [])

        new_count = 0
        for r in (requests_list or []):
            rid = r.get('id')
            rid_str = str(rid) if rid is not None else None
            if not rid_str:
                continue
            if CloudRequest.query.filter_by(cloud_id=rid_str).first():
                continue
            if DeletedCloudId.query.filter_by(cloud_id=rid_str).first():
                continue

            new_req = CloudRequest(
                cloud_id=rid_str,
                title=r.get('title', ''),
                media_type=r.get('media_type', 'movie'),
                tmdb_id=r.get('tmdb_id') or 0,
                requested_by=r.get('requested_by', 'Unknown'),
                year=r.get('year'),
                status='pending'
            )
            db.session.add(new_req)
            new_count += 1
            db.session.commit()

            if getattr(settings, 'cloud_auto_approve', False):
                process_item(settings, new_req)

        if new_count > 0:
            db.session.commit()
            return (True, f"{new_count} new request(s) added.")
        return (True, "No new requests.")
    except requests.exceptions.Timeout:
        return (False, "Cloud request timed out. Try again.")
    except requests.exceptions.ConnectionError:
        return (False, "Could not reach the cloud. Check your connection.")
    except Exception as e:
        return (False, f"Error: {getattr(e, 'message', str(e))}")


def process_cloud_queue():
    global last_modified_header, backoff_remaining, recommended_poll_interval_sec

    with app.app_context():
        # 1. Get Local Settings (use config user when set for multi-user isolation)
        if SCHEDULER_USER_ID is not None:
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
        else:
            settings = Settings.query.first()

        # Basic checks to see if we should run (cloud_sync_owned_enabled = "Enable Cloud API" in UI)
        if not settings or not settings.cloud_enabled or not settings.cloud_api_key or not settings.cloud_sync_owned_enabled:
            return

        headers = {'X-Server-Key': settings.cloud_api_key}
        
        # OPTIMIZATION: Send If-Modified-Since if we have a previous timestamp
        if last_modified_header:
            headers['If-Modified-Since'] = last_modified_header
            
        # Do not log API key or any part of it (security: clear-text logging)
        
        # --- NEW STEP: Sync Deletions (and pick up X-Poll-Interval from sync response if present) ---
        sync_response = sync_deletions(settings)
        if sync_response is not None:
            try:
                xi = int(sync_response.headers.get('X-Poll-Interval', 0) or 0)
                recommended_poll_interval_sec = max(0, min(300, xi))
            except (ValueError, TypeError):
                pass

        try:
            # 2. Poll the Cloud for new Mail
            response = requests.get(f"{CLOUD_URL}/api/poll.php", headers=headers, timeout=CLOUD_REQUEST_TIMEOUT)
            
            # --- HANDLE 304 (Not Modified) ---
            if response.status_code == 304:
                try:
                    xi = int(response.headers.get('X-Poll-Interval', 0) or 0)
                    recommended_poll_interval_sec = max(0, min(300, xi))
                except (ValueError, TypeError):
                    pass
                return

            # --- HANDLE 429 (Throttled): respect Retry-After and back off next cycles ---
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                retry_after = min(max(1, retry_after), 300)
                backoff_remaining = BACKOFF_CYCLES
                print(f"Cloud throttle: waiting {retry_after}s (Retry-After). Next {BACKOFF_CYCLES} cycles will use longer intervals.")
                time.sleep(retry_after)
                return

            if response.status_code == 401:
                print("Cloud Error: Invalid API Key. Please check your settings.")
                return
            elif response.status_code != 200:
                print(f"Cloud Error: Server returned status {response.status_code}")
                return
            
            # If we got 200 OK, save the new Last-Modified header, decay backoff, and respect X-Poll-Interval
            if 'Last-Modified' in response.headers:
                last_modified_header = response.headers['Last-Modified']
            if backoff_remaining > 0:
                backoff_remaining -= 1
            try:
                xi = int(response.headers.get('X-Poll-Interval', 0) or 0)
                recommended_poll_interval_sec = max(0, min(300, xi))
            except (ValueError, TypeError):
                recommended_poll_interval_sec = 0

            try:
                data = response.json()
            except ValueError:
                print("Cloud Error: Non-JSON response received (response body not logged).")
                return

            # --- Handle poll response: object { pending_requests } or legacy array (library sync is done via Plex API on cloud)
            requests_list = []
            if isinstance(data, list):
                requests_list = data
            elif isinstance(data, dict):
                if 'error' in data:
                    print(f"Cloud Error: {data['error']}")
                    return
                requests_list = data.get('pending_requests', [])

            # 3. Process the list of requests
            new_count = 0
            for r in (requests_list or []):
                # Normalize cloud id to string so we match our DB (cloud may send int or string in JSON)
                rid = r.get('id')
                rid_str = str(rid) if rid is not None else None
                if not rid_str:
                    continue
                exists = CloudRequest.query.filter_by(cloud_id=rid_str).first()
                if exists:
                    continue
                # Never re-import a request we deleted locally (in case cloud still returns it)
                if DeletedCloudId.query.filter_by(cloud_id=rid_str).first():
                    continue

                # Create the local record
                new_req = CloudRequest(
                    cloud_id=rid_str,
                    title=r['title'],
                    media_type=r['media_type'],
                    tmdb_id=r['tmdb_id'],
                    requested_by=r.get('requested_by', 'Unknown'),
                    year=r.get('year'),
                    status='pending'
                )
                db.session.add(new_req)
                new_count += 1
                print(f"Imported New Request: {new_req.title} ({new_req.media_type})")

                # 4. Check Auto-Approve Setting
                db.session.commit()
                
                if settings.cloud_auto_approve:
                    print(f"Auto-Approving {new_req.title}...")
                    process_item(settings, new_req)

            if new_count > 0:
                db.session.commit()

        except requests.exceptions.Timeout:
            print(f"Cloud poll timed out after {CLOUD_REQUEST_TIMEOUT}s. Next cycle in {get_poll_sleep_seconds()}s.")
        except requests.exceptions.ConnectionError:
            print("Network Error: Could not reach SeekAndWatch Cloud.")
        except Exception as e:
            print(f"Worker Unexpected Error: {e}")

if __name__ == "__main__":
    print("Starting Cloud Worker...")
    print(f"Polling {CLOUD_URL} with jitter ({POLL_INTERVAL_MIN}-{POLL_INTERVAL_MAX}s). Backoff after 429.")
    while True:
        process_cloud_queue()
        time.sleep(get_poll_sleep_seconds())