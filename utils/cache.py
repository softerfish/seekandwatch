"""
cache utilities

caching functions for results, history, and TMDB recommendations,
extracted from utils.py to reduce file size and improve maintainability
"""

import json
import logging
import math
import os
import threading
import time
from config import get_results_cache_file, get_history_cache_file

log = logging.getLogger(__name__)

# cache file paths
RESULTS_CACHE_FILE = get_results_cache_file()
HISTORY_CACHE_FILE = get_history_cache_file()

# in-memory caches (also persisted to disk)
RESULTS_CACHE = {}
HISTORY_CACHE = {}
TMDB_REC_CACHE = {}

# Thread locks for cache safety
RESULTS_CACHE_LOCK = threading.Lock()
TMDB_REC_CACHE_LOCK = threading.Lock()

# Cache configuration
MAX_CACHE_ENTRIES = 100  # max users in cache at once
MAX_CACHE_AGE = 3600  # 1 hour

# Cache statistics for monitoring
CACHE_STATS = {
    'hits': 0,
    'misses': 0,
    'sets': 0,
    'clears': 0,
    'prunes': 0,
    'lock_wait_times': []
}

# cache TTLs (time to live in seconds)
RESULTS_CACHE_TTL = 60 * 60 * 24  # 24 hours
HISTORY_CACHE_TTL = 60 * 60  # 1 hour
TMDB_REC_CACHE_TTL = 60 * 60 * 24  # 24 hours


def _now_ts():
    """grab current timestamp in seconds"""
    return int(time.time())


def _load_cache_file(path, ttl):
    """
    load cache from file and clean expired entries
    
    args:
        path: path to cache file
        ttl: time to live in seconds
        
    returns:
        dict: cleaned cache data
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.loads(f.read())
    except Exception as e:
        log.debug(f"Load cache {path} failed: {e}")
        return {}
    
    now = _now_ts()
    cleaned = {}
    for k, v in (raw or {}).items():
        if not isinstance(v, dict):
            continue
        ts = v.get('ts', 0)
        if ts and now - ts <= ttl:
            cleaned[k] = v
    return cleaned


def _save_cache_file(path, payload):
    """
    save cache to file
    
    args:
        path: path to cache file
        payload: cache data to save
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except Exception as e:
        log.warning(f"Save cache {path} failed: {e}")


def load_results_cache():
    """load results cache from disk"""
    global RESULTS_CACHE
    RESULTS_CACHE = _load_cache_file(RESULTS_CACHE_FILE, RESULTS_CACHE_TTL)


def save_results_cache():
    """save results cache to disk"""
    _save_cache_file(RESULTS_CACHE_FILE, RESULTS_CACHE)


def get_results_cache(user_id):
    """get results cache for user (thread-safe with metrics)"""
    start = time.time()
    with RESULTS_CACHE_LOCK:
        wait_time = time.time() - start
        if wait_time > 0.001:  # only track if wait was significant
            CACHE_STATS['lock_wait_times'].append(wait_time)
            # keep only last 1000 measurements
            if len(CACHE_STATS['lock_wait_times']) > 1000:
                CACHE_STATS['lock_wait_times'] = CACHE_STATS['lock_wait_times'][-1000:]
        
        result = RESULTS_CACHE.get(user_id)
        if result:
            CACHE_STATS['hits'] += 1
        else:
            CACHE_STATS['misses'] += 1
        return result


def set_results_cache(user_id, data):
    """set results cache for user (thread-safe with size limits)"""
    with RESULTS_CACHE_LOCK:
        # add timestamp if not present
        if isinstance(data, dict) and '_cached_at' not in data:
            data['_cached_at'] = time.time()
        
        # prune old entries if cache is full
        if len(RESULTS_CACHE) >= MAX_CACHE_ENTRIES:
            _prune_old_cache_entries()
        
        RESULTS_CACHE[user_id] = data
        CACHE_STATS['sets'] += 1


def clear_results_cache(user_id):
    """clear results cache for user (thread-safe)"""
    with RESULTS_CACHE_LOCK:
        RESULTS_CACHE.pop(user_id, None)
        CACHE_STATS['clears'] += 1


def _prune_old_cache_entries():
    """remove oldest cache entries (must be called with lock held)"""
    now = time.time()
    to_remove = []
    
    # find entries older than MAX_CACHE_AGE
    for user_id, data in RESULTS_CACHE.items():
        if isinstance(data, dict):
            cached_at = data.get('_cached_at', 0)
            if now - cached_at > MAX_CACHE_AGE:
                to_remove.append(user_id)
    
    # if still too many, remove oldest entries
    if len(RESULTS_CACHE) - len(to_remove) >= MAX_CACHE_ENTRIES:
        # sort by age and remove oldest
        entries_with_age = []
        for user_id, data in RESULTS_CACHE.items():
            if user_id not in to_remove and isinstance(data, dict):
                cached_at = data.get('_cached_at', 0)
                entries_with_age.append((user_id, cached_at))
        
        entries_with_age.sort(key=lambda x: x[1])  # sort by timestamp
        excess = (len(RESULTS_CACHE) - len(to_remove)) - (MAX_CACHE_ENTRIES - 10)  # keep 10 slots free
        if excess > 0:
            to_remove.extend([user_id for user_id, _ in entries_with_age[:excess]])
    
    # remove entries
    for user_id in to_remove:
        RESULTS_CACHE.pop(user_id, None)
    
    if to_remove:
        CACHE_STATS['prunes'] += len(to_remove)


def get_cache_stats():
    """get cache performance statistics"""
    with RESULTS_CACHE_LOCK:
        total_requests = CACHE_STATS['hits'] + CACHE_STATS['misses']
        hit_rate = CACHE_STATS['hits'] / total_requests if total_requests > 0 else 0
        
        wait_times = CACHE_STATS['lock_wait_times']
        avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0
        max_wait = max(wait_times) if wait_times else 0
        
        return {
            'hits': CACHE_STATS['hits'],
            'misses': CACHE_STATS['misses'],
            'sets': CACHE_STATS['sets'],
            'clears': CACHE_STATS['clears'],
            'prunes': CACHE_STATS['prunes'],
            'hit_rate': round(hit_rate * 100, 2),
            'cache_size': len(RESULTS_CACHE),
            'max_cache_size': MAX_CACHE_ENTRIES,
            'avg_lock_wait_ms': round(avg_wait * 1000, 3),
            'max_lock_wait_ms': round(max_wait * 1000, 3),
            'lock_wait_samples': len(wait_times)
        }


def load_history_cache():
    """load history cache from disk"""
    global HISTORY_CACHE
    HISTORY_CACHE = _load_cache_file(HISTORY_CACHE_FILE, HISTORY_CACHE_TTL)


def save_history_cache():
    """save history cache to disk"""
    _save_cache_file(HISTORY_CACHE_FILE, HISTORY_CACHE)


def get_history_cache(key):
    """
    grab entry from history cache
    
    args:
        key: cache key
        
    returns:
        cached candidates or none if expired/missing
    """
    entry = HISTORY_CACHE.get(key)
    if not entry:
        return None
    if _now_ts() - entry.get('ts', 0) > HISTORY_CACHE_TTL:
        HISTORY_CACHE.pop(key, None)
        return None
    return entry.get('candidates')


def set_history_cache(key, candidates):
    """
    set entry in history cache
    
    args:
        key: cache key
        candidates: data to cache
    """
    HISTORY_CACHE[key] = {'candidates': candidates, 'ts': _now_ts()}
    save_history_cache()


def get_tmdb_rec_cache(key):
    """
    grab entry from TMDB recommendation cache (thread-safe)
    
    args:
        key: cache key
        
    returns:
        cached results or none if expired/missing
    """
    with TMDB_REC_CACHE_LOCK:
        entry = TMDB_REC_CACHE.get(key)
        if not entry:
            return None
        if _now_ts() - entry.get('ts', 0) > TMDB_REC_CACHE_TTL:
            TMDB_REC_CACHE.pop(key, None)
            return None
        results = entry.get('results')
        # treat empty list as cache miss so we refetch / try similar endpoint
        if not results:
            TMDB_REC_CACHE.pop(key, None)
            return None
        return results


def set_tmdb_rec_cache(key, results):
    """
    set entry in TMDB recommendation cache (thread-safe)
    
    args:
        key: cache key
        results: data to cache
    """
    with TMDB_REC_CACHE_LOCK:
        TMDB_REC_CACHE[key] = {'results': results, 'ts': _now_ts()}


def score_recommendation(item):
    """
    score a recommendation item based on vote average, count, and popularity
    
    args:
        item: TMDB item dict
        
    returns:
        float: recommendation score
    """
    vote_avg = item.get('vote_average', 0) or 0
    vote_count = item.get('vote_count', 0) or 0
    popularity = item.get('popularity', 0) or 0
    return (vote_avg * math.log1p(vote_count)) + (popularity * 0.5)


def diverse_sample(items, limit, bucket_fn=None):
    """
    sample items diversely across buckets
    
    ensures variety by taking items from different buckets in round-robin fashion
    
    args:
        items: list of items to sample
        limit: maximum number of items to return
        bucket_fn: optional function to determine bucket for each item
        
    returns:
        list: sampled items
    """
    if not items or limit <= 0:
        return []
    
    buckets = {}
    for item in items:
        key = bucket_fn(item) if bucket_fn else None
        buckets.setdefault(key, []).append(item)
    
    for key in list(buckets.keys()):
        buckets[key].sort(key=lambda x: x.get('score', 0), reverse=True)
    
    result = []
    keys = list(buckets.keys())
    while len(result) < limit and keys:
        next_keys = []
        for key in keys:
            bucket = buckets.get(key, [])
            if bucket:
                result.append(bucket.pop(0))
                if len(result) >= limit:
                    break
            if bucket:
                next_keys.append(key)
        keys = next_keys
    
    return result


# initialize caches on import
load_results_cache()
load_history_cache()

