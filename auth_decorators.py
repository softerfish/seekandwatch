"""shared auth decorators; use after @login_required so current_user is set"""

from functools import wraps
from flask import request, jsonify, redirect, url_for, flash
from flask_login import current_user


def admin_required(f):
    """restrict route to admin users; use after @login_required; returns 403 json for api requests, redirect+flash for browser"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            if request.is_json or (request.accept_mimetypes.best and 'application/json' in str(request.accept_mimetypes.best)):
                return jsonify({'status': 'error', 'message': 'Unauthorized'}), 403
            flash('Only admins can access this page.', 'error')
            return redirect(url_for('web_pages.dashboard'))
        return f(*args, **kwargs)
    return decorated
