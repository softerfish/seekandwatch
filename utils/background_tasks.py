"""
background task utilities for flask app
handles threading with proper app context
"""

import threading
from flask import current_app


def run_in_background(func, *args, **kwargs):
    """
    run a function in a background thread with flask app context
    
    usage:
        run_in_background(my_function, arg1, arg2, kwarg1=value1)
    
    the function will have access to flask app context (db, current_app, etc.)
    """
    # Capture the app object BEFORE starting the thread (while we still have context)
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        # No app context available, can't run in background
        print(f"Warning: Cannot run {func.__name__} in background - no app context")
        return None
    
    def wrapper():
        # Run function with app context
        with app.app_context():
            try:
                func(*args, **kwargs)
            except Exception as e:
                # Log error but don't crash the thread
                try:
                    from utils import write_log
                    write_log("error", "Background Task", f"{func.__name__} failed: {type(e).__name__}: {e}")
                except:
                    print(f"Background task {func.__name__} failed: {e}")
    
    # Start the thread
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return thread


def run_in_background_with_app(app_obj, func, *args, **kwargs):
    """
    run a function in a background thread with explicit app object
    
    usage:
        run_in_background_with_app(app, my_function, arg1, arg2)
    
    use this when you don't have access to current_app (e.g., in scheduler)
    """
    def wrapper():
        with app_obj.app_context():
            try:
                func(*args, **kwargs)
            except Exception as e:
                try:
                    from utils import write_log
                    write_log("error", "Background Task", f"{func.__name__} failed: {type(e).__name__}: {e}")
                except:
                    print(f"Background task {func.__name__} failed: {e}")
    
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return thread


# convenience functions for common background tasks

def prefetch_runtime_background(items, tmdb_key):
    """prefetch runtime data in background"""
    from utils import prefetch_runtime_parallel
    run_in_background(prefetch_runtime_parallel, items, tmdb_key)


def prefetch_tv_states_background(items, tmdb_key):
    """prefetch TV state data in background"""
    from utils import prefetch_tv_states_parallel
    run_in_background(prefetch_tv_states_parallel, items, tmdb_key)


def prefetch_ratings_background(items, tmdb_key):
    """prefetch rating data in background"""
    from utils import prefetch_ratings_parallel
    run_in_background(prefetch_ratings_parallel, items, tmdb_key)


def prefetch_omdb_background(items, omdb_key):
    """prefetch OMDB data in background"""
    from utils import prefetch_omdb_parallel
    run_in_background(prefetch_omdb_parallel, items, omdb_key)
