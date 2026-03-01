"""
utils package

modular utility functions for SeekAndWatch

this package contains refactored utility modules:
- helpers: logging and title normalization
- system: lock management
- cache: caching operations
- validators: input validation and security

and services:
- plex_service: plex library integration
- tmdb_service: TMDB API integration
- media_service: media matching and ownership

important: this __init__.py re-exports ALL functions from both:
1. new modular files (utils/helpers.py, utils/system.py, etc.)
2. new services (services/plex_service.py, etc.)
3. original utils.py file (for functions not yet migrated)

this ensures backward compatibility during the migration
"""

# import from new modular files (migrated functions)
from utils.helpers import write_log, normalize_title
from utils.system import (
    is_system_locked, set_system_lock, remove_system_lock,
    get_lock_status, reset_stuck_locks
)
from utils.cache import (
    load_results_cache, save_results_cache,
    get_history_cache, set_history_cache,
    get_tmdb_rec_cache, set_tmdb_rec_cache,
    score_recommendation, diverse_sample,
    RESULTS_CACHE
)
from utils.validators import validate_url, validate_path, get_session_filters

# import phase 3 helper modules (for blueprint migration)
from utils.session_helpers import *
from utils.user_helpers import *
from utils.template_helpers import *
from utils.db_helpers import *
from utils.message_helpers import *

# import from new services (service modules)
from services.plex_service import PlexService
from services.tmdb_service import TmdbService
from services.media_service import MediaService

# re-export service functions for backward compatibility
sync_plex_library = PlexService.sync_library
prefetch_keywords_parallel = TmdbService.prefetch_keywords_parallel
item_matches_keywords = TmdbService.item_matches_keywords
prefetch_omdb_parallel = TmdbService.prefetch_omdb_parallel
prefetch_runtime_parallel = TmdbService.prefetch_runtime_parallel
prefetch_tv_states_parallel = TmdbService.prefetch_tv_states_parallel
prefetch_ratings_parallel = TmdbService.prefetch_ratings_parallel
get_tmdb_aliases = TmdbService.get_tmdb_aliases
is_duplicate = MediaService.is_duplicate
is_owned_item = MediaService.is_owned_item
get_owned_tmdb_ids_for_cloud = MediaService.get_owned_tmdb_ids_for_cloud

# import everything else from the original utils.py file
# this is a wildcard import to ensure ALL functions are available
import sys
import os
# get the parent directory (where utils.py is located)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# import the original utils module (utils.py file, not utils/ package)
import importlib.util
utils_py_path = os.path.join(parent_dir, 'utils.py')
spec = importlib.util.spec_from_file_location("utils_original", utils_py_path)
utils_original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils_original)

# re-export everything from utils.py that's not already defined above
for name in dir(utils_original):
    if not name.startswith('_') and name not in globals():
        globals()[name] = getattr(utils_original, name)

# explicitly list commonly used exports for IDE autocomplete
__all__ = [
    # from new modular files
    'write_log',
    'normalize_title',
    'is_system_locked',
    'set_system_lock',
    'remove_system_lock',
    'get_lock_status',
    'reset_stuck_locks',
    'load_results_cache',
    'save_results_cache',
    'get_history_cache',
    'set_history_cache',
    'get_tmdb_rec_cache',
    'set_tmdb_rec_cache',
    'score_recommendation',
    'diverse_sample',
    'RESULTS_CACHE',
    'validate_url',
    'validate_path',
    'get_session_filters',
    # from new services
    'PlexService',
    'TmdbService',
    'MediaService',
    'sync_plex_library',
    'prefetch_keywords_parallel',
    'item_matches_keywords',
    'prefetch_omdb_parallel',
    'prefetch_runtime_parallel',
    'prefetch_tv_states_parallel',
    'prefetch_ratings_parallel',
    'get_tmdb_aliases',
    'is_duplicate',
    'is_owned_item',
    'get_owned_tmdb_ids_for_cloud',
    # from original utils.py (commonly used)
    'get_cloud_base_url',
    'fetch_omdb_ratings',
    'create_backup',
    'list_backups',
    'restore_backup',
    'prune_backups',
    'BACKUP_DIR',
    'CUSTOM_POSTER_DIR',
    'sync_remote_aliases',
    'refresh_radarr_sonarr_cache',
    'get_radarr_sonarr_cache',
    'write_scanner_log',
    'read_scanner_log',
    'check_for_updates',
    'handle_lucky_mode',
    'is_docker',
    'is_unraid',
    'is_git_repo',
    'is_app_dir_writable',
    'perform_git_update',
    'perform_release_update',
]
