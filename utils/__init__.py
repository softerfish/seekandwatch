"""
utils package

modular utility functions for SeekAndWatch

this package contains refactored utility modules:
- helpers: logging and title normalization (core functions)
- system: lock management and system operations
- cache: caching operations
- validators: input validation and security
- backup: backup and restore operations

and services (in services/ directory):
- plex_service: plex library integration
- tmdb_service: TMDB API integration
- media_service: media matching and ownership

note: many functions still live in utils.py (parent directory) for backward compatibility
this will be fully migrated in a future phase
"""

# import from new modular files
from utils.helpers import write_log, normalize_title
from utils.system import (
    is_system_locked, set_system_lock, remove_system_lock,
    get_lock_status, reset_stuck_locks,
    check_for_updates, is_docker, is_unraid, is_git_repo,
    get_app_root, is_app_dir_writable, perform_git_update, perform_release_update
)
from utils.cache import (
    load_results_cache, save_results_cache,
    get_results_cache, set_results_cache,
    get_history_cache, set_history_cache,
    get_tmdb_rec_cache, set_tmdb_rec_cache,
    score_recommendation, diverse_sample,
    get_cache_stats,
    RESULTS_CACHE
)
from utils.validators import validate_url, validate_path, get_session_filters
from utils.backup import create_backup, list_backups, restore_backup, prune_backups, BACKUP_DIR

# import phase 3 helper modules (for blueprint migration)
from utils.session_helpers import *
from utils.user_helpers import *
from utils.template_helpers import *
from utils.db_helpers import *
from utils.message_helpers import *

# import from services (these are in services/ directory, not utils/)
# NOTE: import these AFTER utils.helpers to avoid circular imports
# Delay import of services until they're actually needed
def _get_service_exports():
    """Lazy load service exports to avoid circular imports"""
    from services.plex_service import PlexService
    from services.tmdb_service import TmdbService
    from services.media_service import MediaService
    return PlexService, TmdbService, MediaService

# Export service classes (will be imported on first access)
def __getattr__(name):
    """Lazy load services to avoid circular imports"""
    if name in ('PlexService', 'TmdbService', 'MediaService'):
        PlexService, TmdbService, MediaService = _get_service_exports()
        globals()['PlexService'] = PlexService
        globals()['TmdbService'] = TmdbService
        globals()['MediaService'] = MediaService
        globals()['fetch_omdb_ratings'] = TmdbService.fetch_omdb_ratings
        globals()['sync_remote_aliases'] = TmdbService.sync_remote_aliases
        globals()['get_tmdb_aliases'] = TmdbService.get_tmdb_aliases
        globals()['is_duplicate'] = MediaService.is_duplicate
        globals()['is_owned_item'] = MediaService.is_owned_item
        globals()['get_owned_tmdb_ids_for_cloud'] = MediaService.get_owned_tmdb_ids_for_cloud
        return globals()[name]
    elif name in ('fetch_omdb_ratings', 'sync_remote_aliases', 'get_tmdb_aliases', 
                  'is_duplicate', 'is_owned_item', 'get_owned_tmdb_ids_for_cloud'):
        # Trigger service loading
        _get_service_exports()
        __getattr__('PlexService')  # This will populate all the globals
        return globals()[name]
    raise AttributeError(f"module 'utils' has no attribute '{name}'")

# import from config
from config import CUSTOM_POSTER_DIR

# import remaining functions from utils/legacy.py (being phased out)
from utils.legacy import (
    get_tautulli_trending,
    handle_lucky_mode,
    write_scanner_log,
    read_scanner_log,
    validate_url_safety,
    prefetch_tv_states_parallel,
    prefetch_ratings_parallel,
    prefetch_omdb_parallel,
    prefetch_runtime_parallel,
    sync_plex_library,
    refresh_radarr_sonarr_cache,
    get_radarr_sonarr_cache,
    prefetch_keywords_parallel,
    item_matches_keywords,
)

__all__ = [
    # from utils.helpers
    'write_log',
    'normalize_title',
    # from utils.system
    'is_system_locked',
    'set_system_lock',
    'remove_system_lock',
    'get_lock_status',
    'reset_stuck_locks',
    'check_for_updates',
    'is_docker',
    'is_unraid',
    'is_git_repo',
    'get_app_root',
    'is_app_dir_writable',
    'perform_git_update',
    'perform_release_update',
    # from utils.cache
    'load_results_cache',
    'save_results_cache',
    'get_results_cache',
    'set_results_cache',
    'get_history_cache',
    'set_history_cache',
    'get_tmdb_rec_cache',
    'set_tmdb_rec_cache',
    'score_recommendation',
    'diverse_sample',
    'get_cache_stats',
    'RESULTS_CACHE',
    # from utils.validators
    'validate_url',
    'validate_path',
    'get_session_filters',
    # from utils.backup
    'create_backup',
    'list_backups',
    'restore_backup',
    'prune_backups',
    'BACKUP_DIR',
    # from services
    'PlexService',
    'TmdbService',
    'MediaService',
    'fetch_omdb_ratings',
    'sync_remote_aliases',
    'get_tmdb_aliases',
    'is_duplicate',
    'is_owned_item',
    'get_owned_tmdb_ids_for_cloud',
    # from config
    'CUSTOM_POSTER_DIR',
    # from utils.py (not yet migrated)
    'get_tautulli_trending',
    'handle_lucky_mode',
    'write_scanner_log',
    'read_scanner_log',
    'validate_url_safety',
    'get_results_cache',
    'set_results_cache',
    'prefetch_tv_states_parallel',
    'prefetch_ratings_parallel',
    'prefetch_omdb_parallel',
    'prefetch_runtime_parallel',
    'sync_plex_library',
    'refresh_radarr_sonarr_cache',
    'get_radarr_sonarr_cache',
    'prefetch_keywords_parallel',
    'item_matches_keywords',
]
