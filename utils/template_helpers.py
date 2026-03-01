"""
template context helpers to ensure consistent variable passing,
provides functions to build complete context for templates
"""

from flask import session
from flask_login import current_user
from typing import Dict, Any

def get_base_context() -> Dict[str, Any]:
    """
    grab base context variables that all templates need,
    ensures consistency across all routes
    """
    # get VERSION from app.py if available
    try:
        from app import VERSION
        app_version = VERSION
    except ImportError:
        app_version = "Unknown"
    
    context = {
        'app_version': app_version,
        'current_user': current_user,
    }
    
    # add pending requests count if authenticated
    if current_user.is_authenticated:
        try:
            # try to import Request model if it exists
            from models import Request
            count = Request.query.filter_by(status='pending').count()
            context['pending_requests_count'] = count
        except (ImportError, Exception):
            context['pending_requests_count'] = 0
    else:
        context['pending_requests_count'] = 0
    
    # add GitHub stats from session
    context['github_stars'] = session.get('github_stars', 0)
    context['github_forks'] = session.get('github_forks', 0)
    
    return context

def render_with_context(template_name: str, **kwargs) -> str:
    """
    render template with base context plus additional variables
    
    usage:
        return render_with_context('dashboard.html', 
                                   trending=trending_data,
                                   stats=stats_data)
    """
    from flask import render_template
    
    context = get_base_context()
    context.update(kwargs)
    return render_template(template_name, **context)

def get_settings_context() -> Dict[str, Any]:
    """grab context for settings-dependent pages"""
    from utils.user_helpers import get_current_user_settings
    
    context = get_base_context()
    context['settings'] = get_current_user_settings()
    return context
