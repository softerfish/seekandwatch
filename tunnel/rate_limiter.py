"""
rate limiter config for flask app
extracted to avoid circular imports when used in blueprints
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# create limiter instance (will be initialized with app later)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["36000 per day", "1500 per hour"],
    storage_uri="memory://"
)
