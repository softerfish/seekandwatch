"""Helpers for code that may run outside a Flask app context.

These are mostly for background work and threads that still need database or
other Flask-bound access.
"""

import logging
import functools
from typing import Callable, Optional
from flask import Flask, has_app_context, current_app

log = logging.getLogger(__name__)


def with_app_context(func: Callable) -> Callable:
    """
    decorator to ensure function runs with flask app context
    
    automatically detects if context is needed and provides it,
    safe to use on functions that may or may not have context
    
    usage:
        @with_app_context
        def my_background_task():
            settings = Settings.query.first()
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Check if we already have context
        if has_app_context():
            return func(*args, **kwargs)
        
        # Try to get app from kwargs
        app = kwargs.get('app_obj') or kwargs.get('app')
        
        # Try to get app from args (common pattern: func(app, ...))
        if not app and args:
            for arg in args:
                if isinstance(arg, Flask):
                    app = arg
                    break
        
        # Try to get app from current_app (may fail)
        if not app:
            try:
                app = current_app._get_current_object()
            except RuntimeError:
                pass
        
        if not app:
            log.error(f"Cannot run {func.__name__} without app context. "
                     f"Pass app_obj=app or run within app.app_context()")
            raise RuntimeError(f"{func.__name__} requires Flask app context")
        
        # Run with context
        with app.app_context():
            return func(*args, **kwargs)
    
    return wrapper


class ensure_context:
    """
    context manager to ensure flask app context
    
    usage:
        with ensure_context(app):
            settings = Settings.query.first()
    """
    
    def __init__(self, app: Optional[Flask] = None):
        self.app = app
        self.pushed = False
        self.ctx = None
    
    def __enter__(self):
        # Check if we already have context
        if has_app_context():
            return
        
        # Get app
        app = self.app
        if not app:
            try:
                app = current_app._get_current_object()
            except RuntimeError:
                raise RuntimeError("No Flask app available. Pass app to ensure_context(app)")
        
        # Push context
        self.ctx = app.app_context()
        self.ctx.push()
        self.pushed = True
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.pushed and self.ctx:
            self.ctx.pop()


def check_context() -> bool:
    """
    check if we're currently in a flask app context
    
    returns:
        bool: true if in context, false otherwise
    """
    return has_app_context()


def require_context(func: Callable) -> Callable:
    """
    decorator that raises an error if function is called without app context
    
    use this for functions that MUST have context and shouldn't auto-create it
    
    usage:
        @require_context
        def critical_db_operation():
            # this will fail if called without context
            pass
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not has_app_context():
            raise RuntimeError(
                f"{func.__name__} must be called within Flask app context. "
                f"Use app.app_context() or @with_app_context decorator."
            )
        return func(*args, **kwargs)
    
    return wrapper


# example usage patterns:
"""
# pattern 1: decorator (recommended)
@with_app_context
def sync_plex_library(app_obj=None):
    settings = Settings.query.first()
    # ... rest of code

# pattern 2: context manager
def sync_plex_library(app):
    with ensure_context(app):
        settings = Settings.query.first()
        # ... rest of code

# pattern 3: manual (existing pattern, still works)
def sync_plex_library(app):
    with app.app_context():
        settings = Settings.query.first()
        # ... rest of code

# pattern 4: require context (for internal functions)
@require_context
def _internal_db_operation():
    # this assumes caller already has context
    settings = Settings.query.first()
"""

