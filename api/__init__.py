"""
api blueprint for seekandwatch, async/ajax endpoints.
routes are split across modules under api/, this module creates the blueprint
and imports route modules so they register.
"""

from flask import Blueprint
from flask_limiter.util import get_remote_address

api_bp = Blueprint('api', __name__)

# set from app.py after registration so rate_limit_decorator can use it
limiter = None


def rate_limit_decorator(limit_str):
    """rate limiting decorator for api endpoints"""
    def decorator(func):
        if limiter:
            return limiter.limit(limit_str, key_func=get_remote_address)(func)
        return func
    return decorator


# import route modules so they register routes on api_bp
# order doesn't matter, each module uses "from api import api_bp, rate_limit_decorator"
from api import routes_backup, routes_main, routes_tunnel, routes_webhook, routes_pair, routes_health, routes_monitoring  # noqa: E402,F401
