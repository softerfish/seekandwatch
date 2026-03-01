"""
monitoring and metrics system

tracks performance, errors, and migration progress during refactoring,
helps spot issues early and measure impact of changes

usage:
    from utils.monitoring import track_performance, track_error, get_metrics
    
    @track_performance("search_tmdb")
    def search_tmdb(query):
        # your code here
        pass
    
    # or manual tracking
    with track_performance("complex_operation"):
        # your code here
        pass
"""

import time
import logging
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from functools import wraps

log = logging.getLogger(__name__)


class MetricsCollector:
    """
    collects and aggregates metrics for monitoring,
    thread-safe for concurrent operations
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._performance: Dict[str, List[float]] = defaultdict(list)
        self._errors: Dict[str, int] = defaultdict(int)
        self._calls: Dict[str, int] = defaultdict(int)
        self._last_reset = datetime.now()
        self._max_samples = 1000  # Keep last 1000 samples per metric
    
    def record_performance(self, operation: str, duration: float):
        """record performance metric for an operation"""
        with self._lock:
            samples = self._performance[operation]
            samples.append(duration)
            
            # keep only recent samples to prevent memory growth
            if len(samples) > self._max_samples:
                self._performance[operation] = samples[-self._max_samples:]
    
    def record_call(self, operation: str):
        """record a function call"""
        with self._lock:
            self._calls[operation] += 1
    
    def record_error(self, operation: str, error_type: str = "unknown"):
        """record an error"""
        with self._lock:
            key = f"{operation}:{error_type}"
            self._errors[key] += 1
    
    def get_stats(self, operation: str) -> Dict[str, Any]:
        """grab statistics for an operation"""
        with self._lock:
            samples = self._performance.get(operation, [])
            if not samples:
                return {
                    'operation': operation,
                    'calls': self._calls.get(operation, 0),
                    'errors': sum(v for k, v in self._errors.items() if k.startswith(operation)),
                    'avg_duration': 0,
                    'min_duration': 0,
                    'max_duration': 0,
                    'p95_duration': 0,
                    'p99_duration': 0,
                }
            
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            
            return {
                'operation': operation,
                'calls': self._calls.get(operation, 0),
                'errors': sum(v for k, v in self._errors.items() if k.startswith(operation)),
                'avg_duration': sum(samples) / n,
                'min_duration': sorted_samples[0],
                'max_duration': sorted_samples[-1],
                'p95_duration': sorted_samples[int(n * 0.95)] if n > 0 else 0,
                'p99_duration': sorted_samples[int(n * 0.99)] if n > 0 else 0,
                'sample_count': n,
            }
    
    def get_all_stats(self) -> List[Dict[str, Any]]:
        """grab statistics for all operations"""
        with self._lock:
            operations = set(self._performance.keys()) | set(self._calls.keys())
            return [self.get_stats(op) for op in operations]
    
    def get_error_summary(self) -> Dict[str, int]:
        """grab summary of all errors"""
        with self._lock:
            return dict(self._errors)
    
    def reset(self):
        """reset all metrics"""
        with self._lock:
            self._performance.clear()
            self._errors.clear()
            self._calls.clear()
            self._last_reset = datetime.now()
            log.info("Metrics reset")
    
    def get_uptime(self) -> timedelta:
        """grab time since last reset"""
        return datetime.now() - self._last_reset


# global metrics collector
_collector: Optional[MetricsCollector] = None


def get_collector() -> MetricsCollector:
    """grab or create the global metrics collector"""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


@contextmanager
def track_performance(operation: str):
    """
    context manager to track performance of a code block
    
    usage:
        with track_performance("search_tmdb"):
            results = search_tmdb(query)
    """
    collector = get_collector()
    collector.record_call(operation)
    
    start = time.time()
    try:
        yield
    except Exception as e:
        collector.record_error(operation, type(e).__name__)
        raise
    finally:
        duration = time.time() - start
        collector.record_performance(operation, duration)


def track_function(operation: Optional[str] = None):
    """
    decorator to track function performance
    
    usage:
        @track_function("search_tmdb")
        def search_tmdb(query):
            # your code here
            pass
        
        # or use function name automatically
        @track_function()
        def search_tmdb(query):
            pass
    """
    def decorator(func):
        op_name = operation or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            with track_performance(op_name):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def track_error(operation: str, error: Exception):
    """
    manually track an error
    
    usage:
        try:
            risky_operation()
        except Exception as e:
            track_error("risky_operation", e)
            raise
    """
    collector = get_collector()
    collector.record_error(operation, type(error).__name__)


def get_metrics(operation: Optional[str] = None) -> Any:
    """
    grab metrics for an operation or all operations
    
    args:
        operation: optional operation name, if none returns all metrics
        
    returns:
        dict or list of metrics
    """
    collector = get_collector()
    if operation:
        return collector.get_stats(operation)
    return collector.get_all_stats()


def get_error_summary() -> Dict[str, int]:
    """grab summary of all errors"""
    return get_collector().get_error_summary()


def reset_metrics():
    """reset all metrics"""
    get_collector().reset()


def get_uptime() -> timedelta:
    """grab monitoring uptime"""
    return get_collector().get_uptime()


# migration progress tracking
class MigrationTracker:
    """
    tracks progress of the refactoring migration,
    helps identify which code paths are being used
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._old_path_calls: Dict[str, int] = defaultdict(int)
        self._new_path_calls: Dict[str, int] = defaultdict(int)
    
    def track_old_path(self, feature: str):
        """track usage of old code path"""
        with self._lock:
            self._old_path_calls[feature] += 1
    
    def track_new_path(self, feature: str):
        """track usage of new code path"""
        with self._lock:
            self._new_path_calls[feature] += 1
    
    def get_migration_status(self) -> Dict[str, Dict[str, Any]]:
        """grab migration status for all features"""
        with self._lock:
            features = set(self._old_path_calls.keys()) | set(self._new_path_calls.keys())
            status = {}
            
            for feature in features:
                old_calls = self._old_path_calls.get(feature, 0)
                new_calls = self._new_path_calls.get(feature, 0)
                total = old_calls + new_calls
                
                status[feature] = {
                    'old_calls': old_calls,
                    'new_calls': new_calls,
                    'total_calls': total,
                    'new_percentage': (new_calls / total * 100) if total > 0 else 0,
                    'ready_to_remove_old': new_calls > 0 and old_calls == 0,
                }
            
            return status
    
    def reset(self):
        """reset migration tracking"""
        with self._lock:
            self._old_path_calls.clear()
            self._new_path_calls.clear()


# global migration tracker
_migration_tracker: Optional[MigrationTracker] = None


def get_migration_tracker() -> MigrationTracker:
    """grab or create the global migration tracker"""
    global _migration_tracker
    if _migration_tracker is None:
        _migration_tracker = MigrationTracker()
    return _migration_tracker


def track_old_path(feature: str):
    """track usage of old code path"""
    get_migration_tracker().track_old_path(feature)


def track_new_path(feature: str):
    """track usage of new code path"""
    get_migration_tracker().track_new_path(feature)


def get_migration_status() -> Dict[str, Dict[str, Any]]:
    """grab migration status for all features"""
    return get_migration_tracker().get_migration_status()


# example usage in refactored code:
"""
# in api/media/routes.py
from utils.monitoring import track_performance, track_old_path, track_new_path
from utils.feature_flags import is_enabled, FeatureFlags

@api_bp.route('/api/search')
@track_function("api.search")
def search():
    if is_enabled(FeatureFlags.NEW_MEDIA_API):
        track_new_path("media_search")
        from services.media_service import MediaService
        results = MediaService.search(request.args.get('q'))
    else:
        track_old_path("media_search")
        from utils import search_tmdb
        results = search_tmdb(request.args.get('q'))
    
    return jsonify(results)
"""

