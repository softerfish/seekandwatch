"""
user access helpers for consistent current_user access across blueprints,
ensures current_user is always available and provides safe accessors
"""

from flask_login import current_user
from models import Settings
from typing import Optional

def get_current_user_settings() -> Optional[Settings]:
    """
    safely grab current user's settings,
    returns none if user not authenticated or settings don't exist
    """
    if not current_user.is_authenticated:
        return None
    return current_user.settings

def get_current_user_id() -> Optional[int]:
    """
    safely grab current user's ID,
    returns none if user not authenticated
    """
    if not current_user.is_authenticated:
        return None
    return current_user.id

def is_user_authenticated() -> bool:
    """check if user is authenticated"""
    return current_user.is_authenticated

def is_user_admin() -> bool:
    """check if current user is admin"""
    if not current_user.is_authenticated:
        return False
    return current_user.is_admin

def require_settings(flash_message: str = "Please complete setup in Settings."):
    """
    decorator to ensure user has settings before accessing route,
    redirects to settings page if not configured
    """
    from functools import wraps
    from flask import flash, redirect, url_for
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            settings = get_current_user_settings()
            if not settings:
                flash(flash_message, "error")
                return redirect(url_for('web_settings.settings'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
