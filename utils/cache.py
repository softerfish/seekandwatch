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
TMDB_REC_CACHE_LOCK = threading.Lock()

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

