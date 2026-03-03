"""
Lightweight health check endpoint for tunnel monitoring.
No authentication, no database logging, fast response.
"""
import time
from flask import jsonify
from api import api_bp, rate_limit_decorator


@api_bp.route('/health', methods=['GET'])
@rate_limit_decorator("60 per hour")
def health_check():
    """
    Lightweight health check for tunnel monitoring.
    
    Returns simple status without authentication or database writes.
    Used by tunnel health monitor to verify connectivity.
    """
    return jsonify({
        'status': 'ok',
        'timestamp': time.time()
    }), 200
