"""
cache service for user-specific temporary data.
thread-safe, with automatic expiration and memory management.
"""

import threading
import time
from typing import Any, Optional, Dict

class CacheService:
    """thread-safe cache for user-specific data"""
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._expiry: Dict[str, float] = {}
    
    def set(self, user_id: int, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        """set a value in the cache for a specific user"""
        with self._lock:
            cache_key = f"{user_id}:{key}"
            self._cache[cache_key] = value
            self._expiry[cache_key] = time.time() + ttl_seconds
    
    def get(self, user_id: int, key: str, default: Any = None) -> Any:
        """grab a value from the cache for a specific user, returns default if not found or expired"""
        with self._lock:
            cache_key = f"{user_id}:{key}"
            
            # check if expired
            if cache_key in self._expiry:
                if time.time() > self._expiry[cache_key]:
                    # expired, remove it
                    self._cache.pop(cache_key, None)
                    self._expiry.pop(cache_key, None)
                    return default
            
            return self._cache.get(cache_key, default)
    
    def delete(self, user_id: int, key: str) -> None:
        """delete a value from the cache"""
        with self._lock:
            cache_key = f"{user_id}:{key}"
            self._cache.pop(cache_key, None)
            self._expiry.pop(cache_key, None)
    
    def clear_user(self, user_id: int) -> None:
        """clear all cache entries for a specific user"""
        with self._lock:
            prefix = f"{user_id}:"
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                self._cache.pop(key, None)
                self._expiry.pop(key, None)
    
    def cleanup_expired(self) -> int:
        """remove all expired entries, returns number of entries removed"""
        with self._lock:
            now = time.time()
            expired_keys = [k for k, exp_time in self._expiry.items() if now > exp_time]
            for key in expired_keys:
                self._cache.pop(key, None)
                self._expiry.pop(key, None)
            return len(expired_keys)
    
    def get_size(self) -> int:
        """grab number of entries in cache"""
        with self._lock:
            return len(self._cache)

# global instance
_cache_service = CacheService()

def get_cache_service() -> CacheService:
    """grab the global cache service instance"""
    return _cache_service

# convenience functions for results cache
def set_results_cache(user_id: int, candidates: list, next_index: int = 0) -> None:
    """set results cache for a user"""
    _cache_service.set(user_id, 'results', {
        'candidates': candidates,
        'next_index': next_index
    })

def get_results_cache(user_id: int) -> Optional[Dict]:
    """grab results cache for a user"""
    return _cache_service.get(user_id, 'results')

def clear_results_cache(user_id: int) -> None:
    """clear results cache for a user"""
    _cache_service.delete(user_id, 'results')
