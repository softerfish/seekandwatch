"""
flask api routes for cloudflare tunnel management.

provides endpoints for enabling, disabling, testing, and managing tunnels.
"""

from flask import jsonify, current_app
from flask_login import login_required, current_user

from api import api_bp, rate_limit_decorator
from tunnel.manager import TunnelManager
from tunnel.exceptions import TunnelCreationError, AuthenticationError
from models import db, Settings


def get_tunnel_manager():
    """grab or create tunnelmanager instance"""
    if not hasattr(current_app, 'tunnel_manager'):
        current_app.tunnel_manager = TunnelManager(current_app, db)
    return current_app.tunnel_manager


@api_bp.route('/tunnel/enable', methods=['POST'])
@login_required
@rate_limit_decorator("10 per hour")
def enable_tunnel():
    """enable cloudflare tunnel for the current user"""
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({
                'success': False,
                'error': 'Settings not found for user'
            }), 404
        
        # check if already enabled and has a URL (tunnel is running)
        if settings.tunnel_enabled and settings.tunnel_url:
            # check if it's a quick tunnel using proper domain validation
            is_quick = False
            if settings.tunnel_url:
                url_lower = settings.tunnel_url.lower()
                is_quick = url_lower.endswith('.trycloudflare.com') or url_lower.startswith('https://trycloudflare.com/')
            
            return jsonify({
                'success': True,
                'message': 'tunnel already enabled',
                'tunnel_url': settings.tunnel_url,
                'status': 'connected',
                'is_quick': is_quick
            })
        
        manager = get_tunnel_manager()
        
        # check if user has provided cloudflare api token
        cloudflare_api_token = settings.cloudflare_api_token if hasattr(settings, 'cloudflare_api_token') else None
        
        if not cloudflare_api_token:
            # fallback - try quick tunnel (trycloudflare.com)
            current_app.logger.info(f"no cloudflare api token found for user {user_id}, attempting quick tunnel")
            
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
                if settings.cloud_enabled and settings.cloud_api_key:
                    # make sure we have a secret locally
                    if not settings.cloud_webhook_secret:
                        import secrets
                        settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                        db.session.commit()

                    webhook_secret = settings.cloud_webhook_secret
                    
                    # save webhook URL to local settings
                    webhook_url = f"{tunnel_url}/api/webhook"
                    settings.cloud_webhook_url = webhook_url
                    
                    # get cloud base URL (uses config default if not set)
                    from services.CloudService import CloudService
                    cloud_base = CloudService.get_cloud_base_url(settings)
                    
                    # register in background
                    manager.register_webhook(
                        tunnel_url=tunnel_url,
                        api_key=settings.cloud_api_key,
                        cloud_base_url=cloud_base,
                        user_id=user_id,
                        webhook_secret=webhook_secret
                    )
                
                # mark tunnel as enabled
                settings.tunnel_enabled = True
                settings.cloud_sync_owned_enabled = True  # cloud sync requires tunnel
                db.session.commit()
                
                # trigger initial sync to pull down any pending approved requests
                if settings.cloud_enabled and settings.cloud_api_key:
                    def _initial_sync(app_context, settings_id):
                        import time
                        time.sleep(3)  # wait for webhook registration
                        with app_context:
                            from services.CloudService import CloudService
                            s = Settings.query.get(settings_id)
                            if s and s.cloud_enabled and s.cloud_api_key:
                                current_app.logger.info(f"Running initial sync after tunnel enable for user {s.user_id}")
                                try:
                                    success, message = CloudService.fetch_cloud_requests(s)
                                    if success:
                                        current_app.logger.info(f"Initial sync completed: {message}")
                                    else:
                                        current_app.logger.warning(f"Initial sync failed: {message}")
                                except Exception as e:
                                    current_app.logger.error(f"Initial sync error: {e}")
                    
                    import threading
                    threading.Thread(
                        target=_initial_sync,
                        args=(current_app.app_context(), settings.id),
                        daemon=True
                    ).start()
                
                return jsonify({
                    'success': True,
                    'message': 'quick tunnel enabled successfully',
                    'tunnel_url': tunnel_url,
                    'status': 'connected',
                    'is_quick': True
                })
                
            except Exception:
                current_app.logger.error("Error starting quick tunnel")
                return jsonify({
                    'success': False,
                    'error': 'Failed to start Quick Tunnel. Please check the logs.',
                    'step': 'quick_tunnel_logic'
                }), 500
        
        # create tunnel via cloudflare api (no browser needed!)
        current_app.logger.info(f"creating cloudflare tunnel via api for user {user_id}")
        
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
            
            # wait a moment for configuration to propagate in cloudflare's system
            import time
            time.sleep(2)
            
            # start tunnel using the token (no authentication needed!)
            current_app.logger.info(f"starting tunnel with token for user {user_id}")
            if not manager.start_tunnel_with_token(user_id, tunnel_result['token']):
                return jsonify({
                    'success': False,
                    'error': 'Failed to start tunnel process',
                    'step': 'process_start'
                }), 500
            
            # register webhook with cloud app
            if settings.cloud_enabled and settings.cloud_api_key:
                tunnel_url = tunnel_result['url']
                
                # make sure we have a secret locally
                if not settings.cloud_webhook_secret:
                    import secrets
                    settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                    db.session.commit()

                webhook_secret = settings.cloud_webhook_secret
                
                # save webhook URL to local settings so polling knows to use failsafe interval
                webhook_url = f"{tunnel_url}/api/webhook"
                settings.cloud_webhook_url = webhook_url
                
                # get cloud base URL (uses config default if not set)
                from services.CloudService import CloudService
                cloud_base = CloudService.get_cloud_base_url(settings)
                
                # register in background
                manager.register_webhook(
                    tunnel_url=tunnel_url,
                    api_key=settings.cloud_api_key,
                    cloud_base_url=cloud_base,
                    user_id=user_id,
                    webhook_secret=webhook_secret
                )
            
            # mark tunnel as enabled
            settings.tunnel_enabled = True
            settings.cloud_sync_owned_enabled = True  # cloud sync requires tunnel
            db.session.commit()
            
            # trigger initial sync to pull down any pending approved requests
            if settings.cloud_enabled and settings.cloud_api_key:
                def _initial_sync(app_context, settings_id):
                    import time
                    time.sleep(3)  # wait for webhook registration
                    with app_context:
                        from services.CloudService import CloudService
                        s = Settings.query.get(settings_id)
                        if s and s.cloud_enabled and s.cloud_api_key:
                            current_app.logger.info(f"Running initial sync after tunnel enable for user {s.user_id}")
                            try:
                                success, message = CloudService.fetch_cloud_requests(s)
                                if success:
                                    current_app.logger.info(f"Initial sync completed: {message}")
                                else:
                                    current_app.logger.warning(f"Initial sync failed: {message}")
                            except Exception as e:
                                current_app.logger.error(f"Initial sync error: {e}")
                
                import threading
                threading.Thread(
                    target=_initial_sync,
                    args=(current_app.app_context(), settings.id),
                    daemon=True
                ).start()
            
            return jsonify({
                'success': True,
                'message': 'tunnel enabled successfully',
                'tunnel_url': tunnel_result['url'],
                'status': 'connected'
            })
            
        except Exception:
            current_app.logger.error("Error creating tunnel")
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
        except TunnelCreationError:
            return jsonify({
                'success': False,
                'error': 'Failed to create tunnel. Please check the logs.',
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
        
    except Exception:
        current_app.logger.error("Unexpected error enabling tunnel")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred',
            'step': 'unknown'
        }), 500


@api_bp.route('/tunnel/disable', methods=['POST'])
@login_required
@rate_limit_decorator("20 per hour")
def disable_tunnel():
    """disable cloudflare tunnel for the current user (stops the process but keeps credentials for future use)"""
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
                'message': 'tunnel already disabled',
                'status': 'already_disabled'
            })
        
        manager = get_tunnel_manager()
        
        # stop the tunnel process
        current_app.logger.info(f"Stopping tunnel for user {user_id}")
        if not manager.stop_tunnel(user_id):
            current_app.logger.warning(f"Failed to stop tunnel cleanly for user {user_id}")
        
        # unregister webhook from cloud (clear webhook url on cloud side)
        if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
            try:
                manager.unregister_webhook(
                    api_key=settings.cloud_api_key,
                    cloud_base_url=settings.cloud_base_url,
                    user_id=user_id
                )
            except Exception:
                current_app.logger.warning("failed to unregister webhook")
        
        # clear webhook url from local settings (so polling goes back to normal interval)
        settings.cloud_webhook_url = None
        
        # mark tunnel as disabled (but keep credentials)
        settings.tunnel_enabled = False
        settings.tunnel_status = 'disconnected'
        settings.cloud_sync_owned_enabled = False  # cloud sync requires tunnel
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'tunnel disabled successfully',
            'status': 'disconnected'
        })
        
    except Exception:
        current_app.logger.error("Unexpected error disabling tunnel")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


@api_bp.route('/tunnel/status', methods=['GET'])
@login_required
@rate_limit_decorator("60 per hour")
def tunnel_status():
    """grab current tunnel status for the current user"""
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
    """test tunnel connection by sending a test request"""
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
        
        success, message = registrar.test_connection(timeout=30)
        
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


@api_bp.route('/tunnel/restart', methods=['POST'])
@login_required
@rate_limit_decorator("10 per hour")
def restart_tunnel():
    """restart tunnel for the current user (stops and starts the process, useful if tunnel died)"""
    try:
        user_id = current_user.id
        settings = Settings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({
                'success': False,
                'error': 'Settings not found for user'
            }), 404
        
        if not settings.tunnel_enabled:
            return jsonify({
                'success': False,
                'error': 'Tunnel is not enabled'
            }), 400
        
        manager = get_tunnel_manager()
        
        current_app.logger.info(f"restarting tunnel for user {user_id}")
        
        # stop existing process
        manager.stop_tunnel(user_id)
        
        # wait a moment
        import time
        time.sleep(2)
        
        # restart based on tunnel type
        tunnel_url = None
        if settings.tunnel_name == 'quick-tunnel' or not hasattr(settings, 'cloudflare_api_token') or not settings.cloudflare_api_token:
            # restart quick tunnel
            tunnel_url = manager.start_quick_tunnel(user_id)
        else:
            # restart API-based tunnel
            if settings.tunnel_credentials_encrypted:
                credentials = manager._decrypt_credentials(settings.tunnel_credentials_encrypted)
                if credentials and 'tunnel_token' in credentials:
                    if manager.start_tunnel_with_token(user_id, credentials['tunnel_token']):
                        tunnel_url = settings.tunnel_url
        
        if not tunnel_url:
            return jsonify({
                'success': False,
                'error': 'Failed to restart tunnel'
            }), 500
        
        # re-register webhook if cloud is enabled
        if settings.cloud_enabled and settings.cloud_api_key:
            from services.CloudService import CloudService
            cloud_base = CloudService.get_cloud_base_url(settings)
            
            if not settings.cloud_webhook_secret:
                import secrets
                settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                db.session.commit()
            
            manager.register_webhook(
                tunnel_url=tunnel_url,
                api_key=settings.cloud_api_key,
                cloud_base_url=cloud_base,
                user_id=user_id,
                webhook_secret=settings.cloud_webhook_secret
            )
        
        return jsonify({
            'success': True,
            'message': 'tunnel restarted successfully',
            'tunnel_url': tunnel_url,
            'status': 'connected'
        })
        
    except Exception:
        current_app.logger.error("error restarting tunnel")
        return jsonify({
            'success': False,
            'error': 'an unexpected error occurred, please check the logs'
        }), 500


@api_bp.route('/tunnel/reset', methods=['POST'])
@login_required
@rate_limit_decorator("5 per hour")
def reset_tunnel():
    """reset tunnel configuration for the current user (clears all tunnel data, stops process, deletes config files)"""
    try:
        user_id = current_user.id
        manager = get_tunnel_manager()
        
        current_app.logger.info(f"resetting tunnel configuration for user {user_id}")
        
        if manager.reset_configuration(user_id):
            return jsonify({
                'success': True,
                'message': 'tunnel configuration reset successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'failed to reset tunnel configuration'
            }), 500
        
    except Exception:
        current_app.logger.error("error resetting tunnel configuration")
        return jsonify({
            'success': False,
            'error': 'an unexpected error occurred, please check the logs'
        }), 500
