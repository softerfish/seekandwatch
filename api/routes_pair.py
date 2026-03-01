"""pairing routes - link local app to cloud account without manual key entry"""

import secrets
from datetime import datetime, timedelta
from flask import request, jsonify, current_app
from api import api_bp, rate_limit_decorator
from models import db, Settings
from config import CLOUD_URL, SCHEDULER_USER_ID
from flask_login import login_required, current_user
from services.Router import Router

@api_bp.route('/pair/start', methods=['POST'])
@login_required
@rate_limit_decorator("5 per hour")
def pair_start():
    """generate a pairing token, start a tunnel, and return the web app link"""
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({'success': False, 'error': 'Settings not found'}), 404
            
        # generate unique token
        token = secrets.token_urlsafe(32)
        settings.pairing_token = token
        settings.pairing_token_expires = datetime.utcnow() + timedelta(minutes=15)
        
        # make sure tunnel is running (quick tunnel fallback)
        manager = current_app.tunnel_manager
        tunnel_url = settings.tunnel_url
        
        # validation - only accept public urls for pairing
        is_public = False
        if tunnel_url:
            # must be https and NOT a local IP pattern
            local_ip_patterns = [r'^https?://127\.', r'^https?://192\.168\.', r'^https?://10\.', r'^https?://172\.(1[6-9]|2[0-9]|3[0-1])\.', r'^https?://localhost']
            import re
            is_local = any(re.match(p, tunnel_url) for p in local_ip_patterns)
            # must contain a dot (domain) and not be local
            is_public = '.' in tunnel_url and not is_local

        if not manager._is_process_running() or not tunnel_url or not is_public:
            current_app.logger.info("Starting tunnel for pairing (no valid public URL found)...")
            # reset stale local URL if it was there
            if not is_public:
                tunnel_url = None
                
            if hasattr(settings, 'cloudflare_api_token') and settings.cloudflare_api_token:
                # start persistent if they have a token
                creds = manager._decrypt_credentials(settings.tunnel_credentials_encrypted)
                if creds and 'tunnel_token' in creds:
                    manager.start_tunnel_with_token(user_id, creds['tunnel_token'])
                    tunnel_url = settings.tunnel_url
            
            if not tunnel_url:
                # fallback to quick tunnel
                tunnel_url = manager.start_quick_tunnel(user_id)
        
        if not tunnel_url:
            return jsonify({'success': False, 'error': 'Could not establish a public tunnel for pairing.'}), 500
            
        db.session.commit()
        
        # construct web app link
        # the web app should have a pair.php that accepts these
        cloud_base = settings.cloud_base_url or CLOUD_URL
        pair_base = Router.get_cloud_url(cloud_base, Router.CLOUD_PAIR_PAGE)
        pair_url = f"{pair_base}?url={tunnel_url}&token={token}"
        
        return jsonify({
            'success': True,
            'pair_url': pair_url
        })
        
    except Exception:
        current_app.logger.error("Pairing start failed")
        return jsonify({'success': False, 'error': 'Failed to initiate pairing'}), 500

@api_bp.route('/pair/receive_key', methods=['POST', 'OPTIONS'])
def pair_receive_key():
    """public endpoint (via tunnel) for web app to send the api key"""
    # handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response, 200
    
    try:
        data = request.get_json()
        token = data.get('token')
        api_key = data.get('api_key')
        
        if not token or not api_key:
            response = jsonify({'success': False, 'error': 'Missing data'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response, 400
            
        # Find settings by token
        settings = Settings.query.filter_by(pairing_token=token).first()
        
        if not settings:
            response = jsonify({'success': False, 'error': 'Invalid or expired token'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response, 401
            
        if settings.pairing_token_expires < datetime.utcnow():
            response = jsonify({'success': False, 'error': 'Token expired'})
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response, 401
            
        # save the key and enable cloud
        settings.cloud_api_key = api_key
        settings.cloud_enabled = True
        settings.cloud_sync_owned_enabled = True
        
        # save secret if provided (restored from cloud)
        webhook_secret = data.get('webhook_secret')
        if webhook_secret:
            settings.cloud_webhook_secret = webhook_secret
        
        # make sure we have a secret locally (generate if pairing didn't provide one)
        if not settings.cloud_webhook_secret:
            settings.cloud_webhook_secret = secrets.token_urlsafe(32)
        
        # clear token
        settings.pairing_token = None
        settings.pairing_token_expires = None
        
        db.session.commit()
        
        current_app.logger.info(f"successfully paired with cloud for user {settings.user_id}")
        
        # register webhook with cloud now that we have an api key
        if settings.tunnel_url:
            manager = current_app.tunnel_manager
            cloud_base = settings.cloud_base_url or CLOUD_URL
            import threading
            def _register_bg(app_context, tunnel_url, api_key, cloud_base, user_id, secret):
                with app_context:
                    manager.register_webhook(tunnel_url, api_key, cloud_base, user_id, secret)
                    
            threading.Thread(
                target=_register_bg,
                args=(current_app.app_context(), settings.tunnel_url, api_key, cloud_base, settings.user_id, settings.cloud_webhook_secret or ''),
                daemon=True
            ).start()
        
        response = jsonify({'success': True, 'message': 'Pairing successful! Local app is now connected.'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
        
    except Exception:
        current_app.logger.error("Pairing receive failed")
        response = jsonify({'success': False, 'error': 'Internal server error'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response, 500


@api_bp.route('/pair/status', methods=['GET'])
@login_required
def pair_status():
    """check if pairing completed (has api key now)"""
    settings = current_user.settings
    has_key = bool(settings and settings.cloud_api_key)
    return jsonify({'paired': has_key})
