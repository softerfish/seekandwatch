"""
Flask API routes for Cloudflare Tunnel management.

Provides endpoints for enabling, disabling, testing, and managing tunnels.
"""

from flask import jsonify, current_app
from flask_login import login_required, current_user

from api import api_bp, rate_limit_decorator
from tunnel.manager import TunnelManager
from tunnel.exceptions import TunnelCreationError, AuthenticationError
from models import db, Settings


def get_tunnel_manager():
    """Get or create TunnelManager instance."""
    if not hasattr(current_app, 'tunnel_manager'):
        current_app.tunnel_manager = TunnelManager(current_app, db)
    return current_app.tunnel_manager


@api_bp.route('/tunnel/enable', methods=['POST'])
@login_required
@rate_limit_decorator("10 per hour")
def enable_tunnel():
    """
    Enable Cloudflare tunnel for the current user.
    
    Steps:
    1. Download cloudflared binary if needed
    2. Authenticate with Cloudflare (or reuse credentials)
    3. Create named tunnel
    4. Start tunnel process
    5. Register webhook with cloud app
    
    Returns:
        JSON with success status and tunnel details
    """
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({
                'success': False,
                'error': 'Settings not found for user'
            }), 404
        
        # check if already enabled
        if settings.tunnel_enabled:
            return jsonify({
                'success': True,
                'message': 'Tunnel already enabled',
                'status': 'already_enabled'
            })
        
        manager = get_tunnel_manager()
        
        # check if user has provided cloudflare API token
        cloudflare_api_token = settings.cloudflare_api_token if hasattr(settings, 'cloudflare_api_token') else None
        
        if not cloudflare_api_token:
            # Fallback: Try Quick Tunnel (trycloudflare.com)
            current_app.logger.info(f"No Cloudflare API token found for user {user_id}, attempting Quick Tunnel")
            
            try:
                tunnel_url = manager.start_quick_tunnel(user_id)
                
                if not tunnel_url:
                    return jsonify({
                        'success': False,
                        'error': 'Failed to start Quick Tunnel',
                        'guidance': 'To use a persistent tunnel, you need a Cloudflare API token. Get one from https://dash.cloudflare.com/profile/api-tokens with "Cloudflare Tunnel" permissions.',
                        'step': 'quick_tunnel_start'
                    }), 500
                
                # register webhook with cloud app
                if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
                    webhook_secret = settings.cloud_webhook_secret or ''
                    
                    # save webhook URL to local settings
                    webhook_url = f"{tunnel_url}/api/webhook"
                    settings.cloud_webhook_url = webhook_url
                    
                    # register in background
                    manager.register_webhook(
                        tunnel_url=tunnel_url,
                        api_key=settings.cloud_api_key,
                        cloud_base_url=settings.cloud_base_url,
                        user_id=user_id,
                        webhook_secret=webhook_secret
                    )
                
                # mark tunnel as enabled
                settings.tunnel_enabled = True
                db.session.commit()
                
                return jsonify({
                    'success': True,
                    'message': 'Quick Tunnel enabled successfully',
                    'tunnel_url': tunnel_url,
                    'status': 'connected',
                    'is_quick': True
                })
                
            except Exception as e:
                current_app.logger.error(f"Error starting quick tunnel: {str(e)}")
                return jsonify({
                    'success': False,
                    'error': 'Failed to start Quick Tunnel. Please check the logs.',
                    'step': 'quick_tunnel_logic'
                }), 500
        
        # create tunnel via cloudflare API (no browser needed!)
        current_app.logger.info(f"Creating Cloudflare tunnel via API for user {user_id}")
        
        try:
            tunnel_result = manager.create_tunnel_via_api(
                user_id=user_id,
                api_token=cloudflare_api_token,
                account_id=settings.cloudflare_account_id if hasattr(settings, 'cloudflare_account_id') else None
            )
            
            if not tunnel_result:
                return jsonify({
                    'success': False,
                    'error': 'Failed to create tunnel via Cloudflare API',
                    'guidance': 'Check that your API token has the correct permissions and your account ID is correct.',
                    'step': 'api_creation'
                }), 500
            
            # wait a moment for configuration to propagate in Cloudflare's system
            import time
            time.sleep(2)
            
            # start tunnel using the token (no authentication needed!)
            current_app.logger.info(f"Starting tunnel with token for user {user_id}")
            if not manager.start_tunnel_with_token(user_id, tunnel_result['token']):
                return jsonify({
                    'success': False,
                    'error': 'Failed to start tunnel process',
                    'step': 'process_start'
                }), 500
            
            # register webhook with cloud app
            if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
                tunnel_url = tunnel_result['url']
                webhook_secret = settings.cloud_webhook_secret or ''
                
                # save webhook URL to local settings so polling knows to use failsafe interval
                webhook_url = f"{tunnel_url}/api/webhook"
                settings.cloud_webhook_url = webhook_url
                
                # register in background
                manager.register_webhook(
                    tunnel_url=tunnel_url,
                    api_key=settings.cloud_api_key,
                    cloud_base_url=settings.cloud_base_url,
                    user_id=user_id,
                    webhook_secret=webhook_secret
                )
            
            # mark tunnel as enabled
            settings.tunnel_enabled = True
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Tunnel enabled successfully',
                'tunnel_url': tunnel_result['url'],
                'status': 'connected'
            })
            
        except Exception as e:
            current_app.logger.error(f"Error creating tunnel: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Failed to create tunnel. Please check the logs.',
                'step': 'tunnel_creation'
            }), 500
        
        # the code below is old implementation that required browser auth
        if not manager.ensure_binary():
            return jsonify({
                'success': False,
                'error': 'Failed to download cloudflared binary',
                'step': 'binary_download'
            }), 500
        
        # authenticate (or reuse existing credentials)
        # note: for now, we'll skip the interactive auth flow since it requires browser access
        # cloudflared can create tunnels without explicit login in some cases
        current_app.logger.info(f"Checking credentials for user {user_id}")
        
        # skip authentication for now - cloudflared tunnel create will handle it
        # credentials = manager.get_or_authenticate(user_id)
        # if not credentials:
        #     return jsonify({
        #         'success': False,
        #         'error': 'Failed to authenticate with Cloudflare',
        #         'step': 'authentication',
        #         'guidance': 'Cloudflare authentication requires browser access. This feature is not yet supported in Docker environments.'
        #     }), 500
        
        # create tunnel
        current_app.logger.info(f"Creating tunnel for user {user_id}")
        try:
            tunnel_url = manager.create_tunnel(user_id)
        except TunnelCreationError as e:
            return jsonify({
                'success': False,
                'error': f'Failed to create tunnel: {str(e)}',
                'step': 'tunnel_creation'
            }), 500
        
        # start tunnel process
        current_app.logger.info(f"Starting tunnel process for user {user_id}")
        if not manager.start_tunnel(user_id):
            return jsonify({
                'success': False,
                'error': 'Failed to start tunnel process',
                'step': 'process_start'
            }), 500
        
        # register webhook if cloud integration is enabled
        if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
            current_app.logger.info(f"Registering webhook for user {user_id}")
            webhook_secret = settings.cloud_webhook_secret or ''
            
            # register in background (don't block on this)
            # the register_webhook method has its own retry logic
            success = manager.register_webhook(
                tunnel_url=tunnel_url,
                api_key=settings.cloud_api_key,
                cloud_base_url=settings.cloud_base_url,
                user_id=user_id,
                webhook_secret=webhook_secret
            )
            
            if not success:
                current_app.logger.warning(f"Webhook registration failed for user {user_id}, but tunnel is running")
        
        # mark tunnel as enabled
        settings.tunnel_enabled = True
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Tunnel enabled successfully',
            'tunnel_url': tunnel_url,
            'status': 'connected'
        })
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error enabling tunnel: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred',
            'step': 'unknown'
        }), 500


@api_bp.route('/tunnel/disable', methods=['POST'])
@login_required
@rate_limit_decorator("20 per hour")
def disable_tunnel():
    """
    Disable Cloudflare tunnel for the current user.
    
    Stops the tunnel process but preserves credentials for future use.
    
    Returns:
        JSON with success status
    """
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({
                'success': False,
                'error': 'Settings not found for user'
            }), 404
        
        # check if already disabled
        if not settings.tunnel_enabled:
            return jsonify({
                'success': True,
                'message': 'Tunnel already disabled',
                'status': 'already_disabled'
            })
        
        manager = get_tunnel_manager()
        
        # stop the tunnel process
        current_app.logger.info(f"Stopping tunnel for user {user_id}")
        if not manager.stop_tunnel(user_id):
            current_app.logger.warning(f"Failed to stop tunnel cleanly for user {user_id}")
        
        # unregister webhook from cloud (clear webhook URL on cloud side)
        if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
            try:
                manager.unregister_webhook(
                    api_key=settings.cloud_api_key,
                    cloud_base_url=settings.cloud_base_url,
                    user_id=user_id
                )
            except Exception as e:
                current_app.logger.warning(f"Failed to unregister webhook: {str(e)}")
        
        # clear webhook URL from local settings (so polling goes back to normal interval)
        settings.cloud_webhook_url = None
        
        # mark tunnel as disabled (but keep credentials)
        settings.tunnel_enabled = False
        settings.tunnel_status = 'disconnected'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Tunnel disabled successfully',
            'status': 'disconnected'
        })
        
    except Exception as e:
        current_app.logger.error(f"Unexpected error disabling tunnel: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


@api_bp.route('/tunnel/status', methods=['GET'])
@login_required
@rate_limit_decorator("60 per hour")
def tunnel_status():
    """
    Get current tunnel status for the current user.
    
    Returns:
        JSON with tunnel status, URL, errors, etc.
    """
    try:
        user_id = current_user.id
        manager = get_tunnel_manager()
        
        status = manager.get_status(user_id)
        
        return jsonify({
            'success': True,
            'status': status
        })
        
    except Exception:
        current_app.logger.error("Error in tunnel status route")
        return jsonify({
            'success': False,
            'error': 'Failed to grab tunnel status'
        }), 500


@api_bp.route('/tunnel/test', methods=['POST'])
@login_required
@rate_limit_decorator("10 per hour")
def test_tunnel():
    """
    Test tunnel connection by sending a test request.
    
    Returns:
        JSON with test results
    """
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({
                'success': False,
                'error': 'Settings not found for user'
            }), 404
        
        if not settings.tunnel_enabled or not settings.tunnel_url:
            return jsonify({
                'success': False,
                'error': 'Tunnel is not enabled or URL not available'
            }), 400
        
        if not settings.cloud_enabled or not settings.cloud_api_key or not settings.cloud_base_url:
            return jsonify({
                'success': False,
                'error': 'Cloud integration not configured'
            }), 400
        
        # test the connection
        from tunnel.registrar import WebhookRegistrar
        registrar = WebhookRegistrar(settings.cloud_base_url, settings.cloud_api_key)
        
        success, message = registrar.test_connection(settings.tunnel_url)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'status': 'connection_ok'
            })
        else:
            return jsonify({
                'success': False,
                'error': message,
                'status': 'connection_failed'
            }), 400
        
    except Exception:
        current_app.logger.error("Error testing tunnel connection")
        return jsonify({
            'success': False,
            'error': 'Failed to test connection. Please check the logs.'
        }), 500


@api_bp.route('/tunnel/reset', methods=['POST'])
@login_required
@rate_limit_decorator("5 per hour")
def reset_tunnel():
    """
    Reset tunnel configuration for the current user.
    
    Clears all tunnel data, stops process, deletes config files.
    
    Returns:
        JSON with success status
    """
    try:
        user_id = current_user.id
        manager = get_tunnel_manager()
        
        current_app.logger.info(f"Resetting tunnel configuration for user {user_id}")
        
        if manager.reset_configuration(user_id):
            return jsonify({
                'success': True,
                'message': 'Tunnel configuration reset successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to reset tunnel configuration'
            }), 500
        
    except Exception as e:
        current_app.logger.error(f"Error resetting tunnel configuration: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred. Please check the logs.'
        }), 500
