"""Pairing routes - link local app to cloud account without manual key entry."""

import secrets
from datetime import datetime, timedelta
from flask import request, jsonify, current_app
from api import api_bp, rate_limit_decorator
from models import db, Settings
from config import CLOUD_URL, SCHEDULER_USER_ID
from flask_login import login_required, current_user

@api_bp.route('/pair/start', methods=['POST'])
@login_required
@rate_limit_decorator("5 per hour")
def pair_start():
    """
    Generate a pairing token, start a tunnel, and return the web app link.
    """
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({'success': False, 'error': 'Settings not found'}), 404
            
        # generate unique token
        token = secrets.token_urlsafe(32)
        settings.pairing_token = token
        settings.pairing_token_expires = datetime.utcnow() + timedelta(minutes=15)
        
        # ensure tunnel is running (quick tunnel fallback)
        manager = current_app.tunnel_manager
        tunnel_url = settings.tunnel_url
        
        if not manager._is_process_running() or not tunnel_url:
            current_app.logger.info("Starting tunnel for pairing...")
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
        pair_url = f"{cloud_base.rstrip('/')}/pair.php?url={tunnel_url}&token={token}"
        
        return jsonify({
            'success': True,
            'pair_url': pair_url
        })
        
    except Exception:
        current_app.logger.error("Pairing start failed")
        return jsonify({'success': False, 'error': 'Failed to initiate pairing'}), 500

@api_bp.route('/pair/receive_key', methods=['POST'])
def pair_receive_key():
    """
    Public endpoint (via tunnel) for web app to send the API Key.
    Expects JSON: {'token': '...', 'api_key': '...'}
    """
    try:
        data = request.get_json()
        token = data.get('token')
        api_key = data.get('api_key')
        
        if not token or not api_key:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
            
        # Find settings by token
        settings = Settings.query.filter_by(pairing_token=token).first()
        
        if not settings:
            return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401
            
        if settings.pairing_token_expires < datetime.utcnow():
            return jsonify({'success': False, 'error': 'Token expired'}), 401
            
        # Save the key and enable cloud
        settings.cloud_api_key = api_key
        settings.cloud_enabled = True
        settings.cloud_sync_owned_enabled = True
        
        # Save secret if provided
        webhook_secret = data.get('webhook_secret')
        if webhook_secret:
            settings.cloud_webhook_secret = webhook_secret
        
        # Clear token
        settings.pairing_token = None
        settings.pairing_token_expires = None
        
        db.session.commit()
        
        current_app.logger.info(f"Successfully paired with cloud for user {settings.user_id}")
        
        return jsonify({'success': True, 'message': 'Pairing successful! Local app is now connected.'})
        
    except Exception:
        current_app.logger.error("Pairing receive failed")
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
