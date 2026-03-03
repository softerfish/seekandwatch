"""
centralized configuration for seekandwatch local app
override via environment variables for non-docker installs and tests
"""
import os

# config directory: where db, secret key, backups, and cache files live
# default /config for docker; set SEEKANDWATCH_CONFIG for local or tests
CONFIG_DIR = os.environ.get("SEEKANDWATCH_CONFIG", "/config")

# seekandwatch cloud base url; set SEEKANDWATCH_CLOUD_URL for custom or staging
CLOUD_URL = os.environ.get("SEEKANDWATCH_CLOUD_URL", "https://seekandwatch.com").rstrip("/")

# timeout in seconds for http requests to the cloud (poll, sync, acknowledge); set SEEKANDWATCH_CLOUD_TIMEOUT to override
_def = os.environ.get("SEEKANDWATCH_CLOUD_TIMEOUT")
CLOUD_REQUEST_TIMEOUT = int(_def) if (_def and _def.isdigit()) else 25

# poll interval range (seconds); app picks a random value between min and max each cycle; set SEEKANDWATCH_POLL_INTERVAL_MIN / MAX to override
_def_min = os.environ.get("SEEKANDWATCH_POLL_INTERVAL_MIN")
_def_max = os.environ.get("SEEKANDWATCH_POLL_INTERVAL_MAX")
POLL_INTERVAL_MIN = max(30, int(_def_min)) if (_def_min and _def_min.isdigit()) else 75
POLL_INTERVAL_MAX = max(POLL_INTERVAL_MIN, int(_def_max)) if (_def_max and _def_max.isdigit()) else 120
if POLL_INTERVAL_MAX < POLL_INTERVAL_MIN:
    POLL_INTERVAL_MAX = POLL_INTERVAL_MIN

# database uri; set SEEKANDWATCH_DATABASE_URI for full override (e.g. postgres, or test db)
# otherwise uses sqlite in CONFIG_DIR
_default_db_path = os.path.join(CONFIG_DIR, "seekandwatch.db")
# sqlite uri: need three slashes for absolute path, and path with drive on windows
if _default_db_path.startswith("/"):
    _default_uri = "sqlite:///" + _default_db_path
else:
    _default_uri = "sqlite:///" + os.path.abspath(_default_db_path)
DATABASE_URI = os.environ.get("SEEKANDWATCH_DATABASE_URI", _default_uri)

# path to secret key file (used when SECRET_KEY env is not set)
SECRET_KEY_FILE = os.path.join(CONFIG_DIR, "secret.key")


def get_backup_dir():
    return os.path.join(CONFIG_DIR, "backups")


def get_cache_file():
    return os.path.join(CONFIG_DIR, "plex_cache.json")


def get_lock_file():
    return os.path.join(CONFIG_DIR, "cache.lock")


def get_scanner_log_file():
    return os.path.join(CONFIG_DIR, "scanner.log")


def get_results_cache_file():
    return os.path.join(CONFIG_DIR, "results_cache.json")


def get_history_cache_file():
    return os.path.join(CONFIG_DIR, "history_cache.json")


def get_database_path():
    return _default_db_path


# optional: comma-separated list of hosts allowed for plex url suggestion (from request)
# only request.host values in this list are used; avoids trusting spoofed host headers
# default includes localhost-style values; set PLEX_URL_SUGGESTION_ALLOWED_HOSTS to add more (e.g. my.server.local)
_allowed_hosts_raw = os.environ.get("PLEX_URL_SUGGESTION_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
PLEX_URL_SUGGESTION_ALLOWED_HOSTS = [h.strip().lower() for h in _allowed_hosts_raw.split(",") if h.strip()]

# optional: user id whose settings drive the scheduler and cloud worker (no request context)
# set SCHEDULER_USER_ID to a user id to use that user's settings; leave unset to use first row (legacy)
SCHEDULER_USER_ID = os.environ.get("SEEKANDWATCH_SCHEDULER_USER_ID")
if SCHEDULER_USER_ID is not None:
    try:
        SCHEDULER_USER_ID = int(SCHEDULER_USER_ID)
    except ValueError:
        SCHEDULER_USER_ID = None

# app version and update checking
VERSION = "1.6.4"

# shared cache for update checking (prevents duplicate github api calls)
UPDATE_CACHE = {
    'version': None,
    'last_check': 0
}

# tunnel auto-recovery feature flag (phase 1: disabled by default)
ENABLE_AUTO_RECOVERY = os.environ.get("ENABLE_AUTO_RECOVERY", "false").lower() == "true"

# tunnel health check interval (minimum 900 seconds / 15 minutes)
_tunnel_interval = os.environ.get("TUNNEL_HEALTH_CHECK_INTERVAL", "900")
TUNNEL_HEALTH_CHECK_INTERVAL = max(900, int(_tunnel_interval)) if _tunnel_interval.isdigit() else 900

# phase 5 enhancement 1: dedicated health check endpoint
USE_DEDICATED_HEALTH_ENDPOINT = os.environ.get("USE_DEDICATED_HEALTH_ENDPOINT", "true").lower() == "true"
TUNNEL_HEALTH_ENDPOINT = os.environ.get("TUNNEL_HEALTH_ENDPOINT", "/api/health")

# phase 5 enhancement 2: startup configuration verification
VERIFY_TUNNEL_CONFIG_ON_STARTUP = os.environ.get("VERIFY_TUNNEL_CONFIG_ON_STARTUP", "true").lower() == "true"


def get_custom_poster_dir():
    """Get custom poster directory path"""
    return os.path.join(CONFIG_DIR, 'custom_posters')


# custom poster directory constant
CUSTOM_POSTER_DIR = get_custom_poster_dir()
