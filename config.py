"""
Centralized configuration for SeekAndWatch local app.
Override via environment variables for non-Docker installs and tests.
"""
import os

# Config directory: where DB, secret key, backups, and cache files live.
# Default /config for Docker; set SEEKANDWATCH_CONFIG for local or tests.
CONFIG_DIR = os.environ.get("SEEKANDWATCH_CONFIG", "/config")

# SeekAndWatch Cloud base URL. Set SEEKANDWATCH_CLOUD_URL for custom or staging.
CLOUD_URL = os.environ.get("SEEKANDWATCH_CLOUD_URL", "https://seekandwatch.com").rstrip("/")

# Database URI. Set SEEKANDWATCH_DATABASE_URI for full override (e.g. postgres, or test DB).
# Otherwise uses SQLite in CONFIG_DIR.
_default_db_path = os.path.join(CONFIG_DIR, "seekandwatch.db")
# SQLite URI: need three slashes for absolute path, and path with drive on Windows
if _default_db_path.startswith("/"):
    _default_uri = "sqlite:///" + _default_db_path
else:
    _default_uri = "sqlite:///" + os.path.abspath(_default_db_path)
DATABASE_URI = os.environ.get("SEEKANDWATCH_DATABASE_URI", _default_uri)

# Path to secret key file (used when SECRET_KEY env is not set).
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


# Optional: comma-separated list of hosts allowed for Plex URL suggestion (from request).
# Only request.host values in this list are used; avoids trusting spoofed Host headers.
# Default includes localhost-style values; set PLEX_URL_SUGGESTION_ALLOWED_HOSTS to add more (e.g. my.server.local).
_allowed_hosts_raw = os.environ.get("PLEX_URL_SUGGESTION_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0")
PLEX_URL_SUGGESTION_ALLOWED_HOSTS = [h.strip().lower() for h in _allowed_hosts_raw.split(",") if h.strip()]

# Optional: user id whose settings drive the scheduler and cloud worker (no request context).
# Set SCHEDULER_USER_ID to a user id to use that user's settings; leave unset to use first row (legacy).
SCHEDULER_USER_ID = os.environ.get("SEEKANDWATCH_SCHEDULER_USER_ID")
if SCHEDULER_USER_ID is not None:
    try:
        SCHEDULER_USER_ID = int(SCHEDULER_USER_ID)
    except ValueError:
        SCHEDULER_USER_ID = None
