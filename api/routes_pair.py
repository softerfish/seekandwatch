"""pairing routes - link local app to cloud account without manual key entry"""

import secrets
import json
import base64
from datetime import datetime, timedelta
from urllib.parse import urlencode
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
            
        # grab transition state from UI (if they haven't saved yet)
        data = request.get_json() or {}
        ui_provider = data.get('tunnel_provider')
        ui_external_url = data.get('cloud_webhook_url')
        pairing_mode = ui_provider or (
            'external'
            if settings.tunnel_provider == 'external'
            else 'cloudflare_named'
            if settings.tunnel_provider == 'cloudflare' and settings.tunnel_name == 'named-tunnel'
            else 'cloudflare_quick'
        )
        
        # apply UI state temporarily for the handshake
        if ui_provider == 'external':
            settings.tunnel_provider = 'external'
        elif pairing_mode == 'cloudflare_quick':
            settings.tunnel_provider = 'cloudflare'
            settings.tunnel_name = 'quick-tunnel'
        elif pairing_mode == 'cloudflare_named':
            settings.tunnel_provider = 'cloudflare'
            settings.tunnel_name = 'named-tunnel'
        if ui_external_url:
            # FUTUREPROOFING: Basic safety validation on inputs
            if not ui_external_url.startswith('https://'):
                return jsonify({'success': False, 'error': 'External URL must be HTTPS.'}), 400
            settings.cloud_webhook_url = ui_external_url
            
        # generate unique token
        token = secrets.token_urlsafe(32)
        settings.pairing_token = token
        settings.pairing_token_expires = datetime.utcnow() + timedelta(minutes=15)
        
        # FUTUREPROOFING: Transactional guard - if we fail after this, we should rollback
        
        # make sure tunnel is running (quick tunnel fallback)
        manager = current_app.tunnel_manager
        tunnel_provider = settings.tunnel_provider
        
        # Use our new model helper to get the public URL
        tunnel_url = settings.get_public_url()
        
        # for external provider, ensure we have a URL and it's reachable
        if tunnel_provider == 'external':
            if not tunnel_url:
                with db.session.no_autoflush:
                    return jsonify({'success': False, 'error': 'External tunnel URL not configured. Please enter your external URL.'}), 400
            
            # Reachability Check
            import requests
            current_app.logger.info(f"[Tunnel Trace] Verifying reachability for external URL: {tunnel_url}")
            try:
                # use a short timeout for the pre-check
                resp = requests.get(tunnel_url, timeout=5)
                # 200/401/404 are all signs of life; 5xx or connection error means it's likely down
                if resp.status_code >= 500:
                    current_app.logger.warning(f"[Tunnel Trace] External URL returned {resp.status_code}")
                    return jsonify({'success': False, 'error': f'Your external URL is returning an error ({resp.status_code}). Please verify it is working.'}), 400
            except Exception as e:
                current_app.logger.error(f"[Tunnel Trace] Reachability check failed: {str(e)}")
                return jsonify({'success': False, 'error': 'Could not reach your external URL. Please verify your tunnel is running and accessible from the internet.'}), 400
                
            is_public = True
        else:
            if pairing_mode == 'cloudflare_quick':
                # quick tunnels change often, so pairing should always use a fresh url
                current_app.logger.info("[Tunnel Trace] Starting fresh quick tunnel for pairing...")
                tunnel_url = manager.start_quick_tunnel(user_id)
            else:
                # check if we should even be managing a tunnel
                needs_new_tunnel = False
                
                if not tunnel_url:
                    needs_new_tunnel = True
                else:
                    # validation - only accept public urls for pairing
                    local_ip_patterns = [r'^https?://127\.', r'^https?://192\.168\.', r'^https?://10\.', r'^https?://172\.(1[6-9]|2[0-9]|3[0-1])\.', r'^https?://localhost']
                    import re
                    is_local = any(re.match(p, tunnel_url) for p in local_ip_patterns)
                    is_public = '.' in tunnel_url and not is_local
                    
                    if not is_public or not manager._is_process_running():
                        needs_new_tunnel = True
                
                if needs_new_tunnel:
                    current_app.logger.info("[Tunnel Trace] Starting managed tunnel for pairing...")
                    
                    if pairing_mode == 'cloudflare_named':
                        if not (hasattr(settings, 'cloudflare_api_token') and settings.cloudflare_api_token):
                            return jsonify({'success': False, 'error': 'Named Tunnel requires a saved Cloudflare token.'}), 400

                        creds = manager._decrypt_credentials(settings.tunnel_credentials_encrypted)
                        if not (creds and 'tunnel_token' in creds):
                            return jsonify({'success': False, 'error': 'Named Tunnel credentials are missing. Save your Named Tunnel settings first.'}), 400

                        if not manager.start_tunnel_with_token(user_id, creds['tunnel_token']):
                            return jsonify({'success': False, 'error': 'Failed to start your Named Tunnel.'}), 500
                        tunnel_url = settings.get_public_url()
        
        if not tunnel_url:
            return jsonify({'success': False, 'error': 'Could not establish a public tunnel for pairing.'}), 500
            
        # successfully prepared for pairing
        db.session.commit()
        
        # construct web app link
        cloud_base = settings.cloud_base_url or CLOUD_URL
        pair_base = Router.get_cloud_url(cloud_base, Router.CLOUD_PAIR_PAGE)
        
        pair_payload = {
            'url': tunnel_url,
            'local_url': tunnel_url,
            'token': token,
            'pairing_token': token,
            'webhook_url': Router.get_local_webhook_url(tunnel_url),
            'v': '1',
        }
        pair_blob = base64.urlsafe_b64encode(json.dumps(pair_payload).encode('utf-8')).decode('ascii').rstrip('=')
        pair_query = urlencode({
            **pair_payload,
            'pair': pair_blob,
        })
        pair_url = f"{pair_base}?{pair_query}"
        current_app.logger.info(
            "[Tunnel Trace] Pair URL built base=%s has_url=%s has_token=%s has_pair=%s len=%s",
            pair_base,
            'url=' in pair_url,
            'token=' in pair_url,
            'pair=' in pair_url,
            len(pair_url),
        )
        
        return jsonify({
            'success': True,
            'pair_url': pair_url
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[Tunnel Trace] Pairing start failed: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to initiate pairing'}), 500

@api_bp.route('/pair/receive_key', methods=['POST'])
def pair_receive_key():
    """public endpoint (via tunnel) for web app to send the api key"""
    current_app.logger.info("[Tunnel Trace] Received pairing key request from cloud app")
    
    try:
        data = request.get_json()
        token = data.get('token')
        api_key = data.get('api_key')
        version = data.get('v', '0') # protocol version
        
        if not token or not api_key:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
            
        # Find settings by token
        settings = Settings.query.filter_by(pairing_token=token).first()
        
        if not settings:
            return jsonify({'success': False, 'error': 'Invalid or expired token'}), 401
            
        if settings.pairing_token_expires < datetime.utcnow():
            return jsonify({'success': False, 'error': 'Token expired'}), 401
            
        settings.cloud_api_key = api_key
        settings.cloud_enabled = True
        
        # FUTUREPROOFING: Log protocol version for diagnostics
        if int(version) > 1:
            current_app.logger.warning(f"[Tunnel Trace] Cloud is using a newer protocol (v{version}). Basic pairing will continue.")
        
        # save secret if provided (restored from cloud)
        webhook_secret = data.get('webhook_secret')
        if webhook_secret:
            settings.cloud_webhook_secret = webhook_secret
        
        # make sure we have a secret locally
        if not settings.cloud_webhook_secret:
            settings.cloud_webhook_secret = secrets.token_urlsafe(32)
        
        # clear token
        settings.pairing_token = None
        settings.pairing_token_expires = None
        
        db.session.commit()
        current_app.logger.info(f"[Tunnel Trace] Successfully paired with cloud for user {settings.user_id} (proto v{version})")
        
        # Use our model helper to get the BEST public URL available right now
        current_pub_url = settings.get_public_url()
        
        # verify tunnel is still running and restart if needed (skip for external)
        manager = current_app.tunnel_manager
        if settings.tunnel_provider != 'external' and not manager._is_process_running():
            current_app.logger.warning("[Tunnel Trace] Tunnel process not running after pairing, restarting...")
            if hasattr(settings, 'cloudflare_api_token') and settings.cloudflare_api_token:
                creds = manager._decrypt_credentials(settings.tunnel_credentials_encrypted)
                if creds and 'tunnel_token' in creds:
                    manager.start_tunnel_with_token(settings.user_id, creds['tunnel_token'])
                    current_pub_url = settings.get_public_url()
            else:
                new_url = manager.start_quick_tunnel(settings.user_id)
                if new_url:
                    settings.tunnel_url = new_url
                    db.session.commit()
                    current_pub_url = new_url
        
        # register webhook with cloud now that we have an api key
        if current_pub_url:
            cloud_base = settings.cloud_base_url or CLOUD_URL
            import threading
            def _register_bg(app_context, tunnel_url, api_key, cloud_base, user_id, secret):
                with app_context:
                    manager.register_webhook(tunnel_url, api_key, cloud_base, user_id, secret)
                    
            threading.Thread(
                target=_register_bg,
                args=(current_app.app_context(), current_pub_url, api_key, cloud_base, settings.user_id, settings.cloud_webhook_secret or ''),
                daemon=True
            ).start()
        
        # trigger initial sync to pull down any pending approved requests
        def _initial_sync(app_context, settings_id):
            import time
            time.sleep(3)  # wait for webhook registration to complete
            with app_context:
                from services.CloudService import CloudService
                s = Settings.query.get(settings_id)
                if s and s.cloud_enabled and s.cloud_api_key:
                    current_app.logger.info(f"[Tunnel Trace] Running initial sync after pairing for user {s.user_id}")
                    try:
                        success, message = CloudService.fetch_cloud_requests(s)
                    except Exception as e:
                        current_app.logger.error(f"[Tunnel Trace] Initial sync error: {e}")
        
        threading.Thread(
            target=_initial_sync,
            args=(current_app.app_context(), settings.id),
            daemon=True
        ).start()
        
        response = jsonify({'success': True, 'message': 'Pairing successful! Local app is now connected.'})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
        
    except Exception as e:
        current_app.logger.error(f"[Tunnel Trace] Pairing receive failed: {e}")
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
