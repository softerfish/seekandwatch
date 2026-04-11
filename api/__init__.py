"""
api blueprint for seekandwatch, async/ajax endpoints.
routes are split across modules under api/, this module creates the blueprint
and imports route modules so they register.
"""

import os
from urllib.parse import urlparse
from flask import Blueprint, request
from config import CLOUD_URL
from utils.rate_limiter import limiter as shared_limiter

api_bp = Blueprint('api', __name__)

# set from app.py after registration so rate_limit_decorator can use it
limiter = shared_limiter


def rate_limit_decorator(limit_str):
    """rate limiting decorator for api endpoints"""
    def decorator(func):
        return limiter.limit(limit_str)(func)
    return decorator


@api_bp.after_request
def add_cors_headers(response):
    """inject CORS headers into all api responses"""
    origin = request.headers.get('Origin', '').strip()
    request_netloc = urlparse(origin).netloc.lower() if origin else ''
    allowed_netlocs = set()

    if CLOUD_URL:
        allowed_netloc = urlparse(CLOUD_URL).netloc.lower()
        if allowed_netloc:
            allowed_netlocs.add(allowed_netloc)

    extra_origins = os.environ.get('SEEKANDWATCH_CORS_ORIGINS', '')
    for raw_origin in extra_origins.split(','):
        cleaned_origin = raw_origin.strip()
        if not cleaned_origin:
            continue
        extra_netloc = urlparse(cleaned_origin).netloc.lower()
        if extra_netloc:
            allowed_netlocs.add(extra_netloc)

    if origin and request_netloc in allowed_netlocs:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Server-Key, Authorization, X-Requested-With'
        response.headers['Access-Control-Expose-Headers'] = 'Content-Type, X-Server-Key'
    return response


# import route modules so they register routes on api_bp
# order doesn't matter, each module uses "from api import api_bp, rate_limit_decorator"
from api import routes_backup, routes_main, routes_tunnel, routes_webhook, routes_pair, routes_health, routes_monitoring  # noqa: E402,F401
