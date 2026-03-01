"""
feature flag system

allows enabling/disabling new code paths without redeployment,
critical for safe rollout of refactored code

usage:
    from utils.feature_flags import is_enabled, FeatureFlags
    
    if is_enabled(FeatureFlags.NEW_MEDIA_SERVICE):
        # use new refactored code
        from services.media_service import MediaService
        result = MediaService.search_tmdb(query)
    else:
        # use old code path
        from utils import search_tmdb
        result = search_tmdb(query)
"""

import os
import json
import logging
from enum import Enum
from typing import Dict, Optional

log = logging.getLogger(__name__)


class FeatureFlags(Enum):
    """
    feature flags for gradual rollout of refactored code
    
    add new flags here as you refactor modules
    """
    # phase 2: modularization flags
    NEW_MEDIA_SERVICE = "new_media_service"
    NEW_PLEX_SERVICE = "new_plex_service"
    NEW_TMDB_SERVICE = "new_tmdb_service"
    NEW_CACHE_SYSTEM = "new_cache_system"
    NEW_VALIDATORS = "new_validators"
    NEW_SYSTEM_UTILS = "new_system_utils"
    
    # phase 3: API refactoring flags
    NEW_COLLECTIONS_API = "new_collections_api"
    NEW_MEDIA_API = "new_media_api"
    NEW_REQUESTS_API = "new_requests_api"
    NEW_SETTINGS_API = "new_settings_api"
    NEW_ADMIN_API = "new_admin_api"
    
    # phase 4: web refactoring flags
    NEW_AUTH_ROUTES = "new_auth_routes"
    NEW_PAGE_ROUTES = "new_page_routes"
    NEW_MEDIA_ROUTES = "new_media_routes"


class FeatureFlagManager:
    """
    manages feature flags with multiple sources:
    1. environment variables (highest priority)
    2. database settings (if available)
    3. config file (default)
    """
    
    def __init__(self):
        self._flags: Dict[str, bool] = {}
        self._config_file = os.path.join(
            os.environ.get('CONFIG_DIR', 'config'),
            'feature_flags.json'
        )
        self._load_flags()
    
    def _load_flags(self):
        """load flags from all sources"""
        # start with defaults (all disabled for safety)
        self._flags = {flag.value: False for flag in FeatureFlags}
        
        # load from config file if exists
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r') as f:
                    file_flags = json.load(f)
                    self._flags.update(file_flags)
                log.info(f"Loaded feature flags from {self._config_file}")
            except Exception as e:
                log.warning(f"Failed to load feature flags from file: {e}")
        
        # override with environment variables (highest priority)
        for flag in FeatureFlags:
            env_key = f"FEATURE_{flag.value.upper()}"
            env_value = os.environ.get(env_key)
            if env_value is not None:
                self._flags[flag.value] = env_value.lower() in ('true', '1', 'yes', 'on')
                log.info(f"Feature flag {flag.value} set to {self._flags[flag.value]} via environment")
    
    def is_enabled(self, flag: FeatureFlags) -> bool:
        """
        check if a feature flag is enabled
        
        args:
            flag: FeatureFlags enum value
            
        returns:
            bool: true if enabled, false otherwise
        """
        return self._flags.get(flag.value, False)
    
    def enable(self, flag: FeatureFlags):
        """enable a feature flag (runtime only, not persisted)"""
        self._flags[flag.value] = True
        log.info(f"Feature flag {flag.value} enabled")
    
    def disable(self, flag: FeatureFlags):
        """disable a feature flag (runtime only, not persisted)"""
        self._flags[flag.value] = False
        log.info(f"Feature flag {flag.value} disabled")
    
    def save_to_file(self):
        """save current flags to config file"""
        try:
            os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
            with open(self._config_file, 'w') as f:
                json.dump(self._flags, f, indent=2)
            log.info(f"Saved feature flags to {self._config_file}")
        except Exception as e:
            log.error(f"Failed to save feature flags: {e}")
    
    def get_all_flags(self) -> Dict[str, bool]:
        """grab all feature flags and their states"""
        return self._flags.copy()
    
    def reload(self):
        """reload flags from all sources"""
        self._load_flags()


# global instance
_manager: Optional[FeatureFlagManager] = None


def get_manager() -> FeatureFlagManager:
    """grab or create the global feature flag manager"""
    global _manager
    if _manager is None:
        _manager = FeatureFlagManager()
    return _manager


def is_enabled(flag: FeatureFlags) -> bool:
    """
    check if a feature flag is enabled
    
    this is the main function to use throughout the codebase
    
    args:
        flag: FeatureFlags enum value
        
    returns:
        bool: true if enabled, false otherwise
        
    example:
        if is_enabled(FeatureFlags.NEW_MEDIA_SERVICE):
            # use new code
        else:
            # use old code
    """
    return get_manager().is_enabled(flag)


def enable(flag: FeatureFlags):
    """enable a feature flag at runtime"""
    get_manager().enable(flag)


def disable(flag: FeatureFlags):
    """disable a feature flag at runtime"""
    get_manager().disable(flag)


def reload_flags():
    """reload feature flags from all sources"""
    get_manager().reload()


def get_all_flags() -> Dict[str, bool]:
    """grab all feature flags and their states"""
    return get_manager().get_all_flags()


# example usage in refactored code:
"""
# in api/media/routes.py (new refactored code)
from utils.feature_flags import is_enabled, FeatureFlags

@api_bp.route('/api/search')
def search():
    if is_enabled(FeatureFlags.NEW_MEDIA_API):
        # new refactored code path
        from services.media_service import MediaService
        results = MediaService.search(request.args.get('q'))
    else:
        # old code path (fallback)
        from utils import search_tmdb
        results = search_tmdb(request.args.get('q'))
    
    return jsonify(results)
"""

