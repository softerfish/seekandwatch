import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import TunnelManager


class HealthMonitor:
    MAX_RESTART_ATTEMPTS = 5
    RESTART_WINDOW_MINUTES = 10
    
    def __init__(self, tunnel_manager: 'TunnelManager', check_interval: int = 900):
            self.tunnel_manager = tunnel_manager
            self.check_interval = check_interval
            self.running = False
            self.thread = None
            self.failure_timestamps = []
            self.app = tunnel_manager.app
            self.db = tunnel_manager.db
            
            self.consecutive_failures = 0

    def _get_active_settings(self):
        with self.app.app_context():
            from models import Settings
            return Settings.query.filter_by(tunnel_enabled=True).first()

    def _can_auto_restart(self, settings, health_result):
        if not settings:
            return False
        if getattr(settings, 'tunnel_provider', None) == 'external':
            return False
        if not getattr(settings, 'tunnel_auto_recovery_enabled', False):
            return False
        if getattr(settings, 'tunnel_recovery_disabled', False):
            return False
        if getattr(settings, 'tunnel_user_stopped', False):
            return False

        if (
            getattr(settings, 'tunnel_provider', None) == 'cloudflare'
            and getattr(settings, 'tunnel_name', None) == 'quick-tunnel'
            and health_result.get('failure_kind') == 'dns'
            and health_result.get('process_running')
        ):
            return False
        return True
    
    def start(self):
        if self.running:
            self.app.logger.warning("Health monitor already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._check_loop, daemon=True)
        self.thread.start()
        self.app.logger.info(f"Health monitor started (check interval: {self.check_interval}s)")
    
    def stop(self):
        if not self.running:
            return
        
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            
        self.app.logger.info("Health monitor stopped")
    
    def force_check(self) -> bool:
        return self._check_process_health().get('healthy', False)
    
    def _check_loop(self):
        while self.running:
            try:
                settings = self._get_active_settings()
                if settings and getattr(settings, 'tunnel_provider', None) == 'external':
                    with self.app.app_context():
                        current = self._get_active_settings()
                        if current:
                            current.tunnel_last_health_check = datetime.utcnow()
                            self.db.session.commit()
                    
                    sleep_remaining = self.check_interval
                    while sleep_remaining > 0 and self.running:
                        time.sleep(min(1, sleep_remaining))
                        sleep_remaining -= 1
                    continue

                health_result = self._check_process_health()
                is_healthy = health_result.get('healthy', False)
                
                self._update_health_check_timestamp()

                if (
                    not is_healthy
                    and settings
                    and getattr(settings, 'tunnel_provider', None) == 'cloudflare'
                    and getattr(settings, 'tunnel_name', None) == 'quick-tunnel'
                    and health_result.get('failure_kind') == 'dns'
                    and health_result.get('process_running')
                ):
                    try:
                        with self.app.app_context():
                            from models import Settings
                            current = Settings.query.filter_by(tunnel_enabled=True).first()
                            if current:
                                current.tunnel_status = 'connected'
                                current.tunnel_last_error = "Quick Tunnel DNS verification warning"
                                if hasattr(current, 'tunnel_consecutive_failures'):
                                    current.tunnel_consecutive_failures = 0
                                self.db.session.commit()
                    except Exception:
                        self.app.logger.error("Failed to update database with quick tunnel DNS warning")

                    if self.consecutive_failures > 0:
                        self.app.logger.info(
                            f"Quick Tunnel DNS warning cleared failure counter (was {self.consecutive_failures})"
                        )
                    self.consecutive_failures = 0
                    self.app.logger.warning(
                        "Quick Tunnel DNS verification failed from inside the app, "
                        "but cloudflared is still running. Treating tunnel as connected."
                    )
                    is_healthy = True
                
                if not is_healthy:
                    self.consecutive_failures += 1
                    
                    self._record_failure()
                    
                    try:
                        with self.app.app_context():
                            from models import Settings
                            
                            settings = Settings.query.filter_by(tunnel_enabled=True).first()
                            if settings:
                                settings.tunnel_last_error = health_result.get('message') or "Tunnel health check failed"
                                if hasattr(settings, 'tunnel_consecutive_failures'):
                                    settings.tunnel_consecutive_failures = self.consecutive_failures
                                self.db.session.commit()
                    except Exception:
                        self.app.logger.error("Failed to update database with failure info")
                    
                    self.app.logger.warning(
                        f"Tunnel health check failed ({health_result.get('summary', 'unhealthy')}) "
                        f"(consecutive failures: {self.consecutive_failures})"
                    )
                    
                    if self.consecutive_failures >= 2:
                        from config import ENABLE_AUTO_RECOVERY
                        
                        if ENABLE_AUTO_RECOVERY:
                            self.app.logger.info(
                                f"2 consecutive failures detected, triggering auto-recovery"
                            )
                            
                            recovery_success = self._trigger_auto_recovery()
                            
                            if recovery_success:
                                self.consecutive_failures = 0
                                self.app.logger.info("Auto-recovery succeeded, reset failure counter")
                            else:
                                self.app.logger.warning("Auto-recovery failed or not applicable")
                        else:
                            self.app.logger.debug(
                                "Auto-recovery disabled by feature flag, not triggering"
                            )
                    
                    if self._can_auto_restart(settings, health_result) and self._should_attempt_restart():
                        self.app.logger.info("Attempting automatic tunnel restart")
                        
                        restart_success = self._attempt_restart()
                        
                        if restart_success:
                            self._record_success()
                            self.consecutive_failures = 0
                            self.app.logger.info("Tunnel restarted successfully")
                        else:
                            self._record_failure()
                            self.app.logger.error("Tunnel restart failed")
                    else:
                        self.app.logger.warning(
                            "Restart attempts exhausted, not attempting restart "
                            f"({len(self.failure_timestamps)} failures in last {self.RESTART_WINDOW_MINUTES} minutes)"
                        )
                else:
                    if self.consecutive_failures > 0:
                        self.app.logger.info(
                            f"Health check passed, resetting consecutive failures "
                            f"(was {self.consecutive_failures})"
                        )
                        self.consecutive_failures = 0
                
                sleep_remaining = self.check_interval
                while sleep_remaining > 0 and self.running:
                    time.sleep(min(1, sleep_remaining))
                    sleep_remaining -= 1
                    
            except Exception:
                self.app.logger.error("Error in health monitor loop")
                time.sleep(5)
    
    def _check_process_health(self) -> dict:
        try:
            from config import USE_DEDICATED_HEALTH_ENDPOINT, TUNNEL_HEALTH_ENDPOINT
            process_running = self.tunnel_manager._is_process_running()
            
            if USE_DEDICATED_HEALTH_ENDPOINT:
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    
                    if settings and settings.tunnel_url:
                        import requests
                        
                        health_url = f"{settings.tunnel_url}{TUNNEL_HEALTH_ENDPOINT}"
                        
                        try:
                            response = requests.get(health_url, timeout=10)
                            
                            if response.status_code == 200:
                                return {
                                    'healthy': True,
                                    'process_running': process_running,
                                    'failure_kind': None,
                                    'message': None,
                                    'summary': 'reachable'
                                }
                            else:
                                self.app.logger.warning(
                                    f"Health endpoint returned {response.status_code}, "
                                    "tunnel is unhealthy"
                                )
                                return {
                                    'healthy': False,
                                    'process_running': process_running,
                                    'failure_kind': 'http',
                                    'message': f"Health check failed (HTTP {response.status_code})",
                                    'summary': f'http {response.status_code}'
                                }
                        except requests.RequestException as e:
                            error_str = str(e)
                            if 'Failed to resolve' in error_str or 'Name or service not known' in error_str or 'NameResolutionError' in error_str:
                                self.app.logger.error(
                                    f"Health endpoint DNS resolution failed: {e}, "
                                    "tunnel URL is not reachable"
                                )
                                return {
                                    'healthy': False,
                                    'process_running': process_running,
                                    'failure_kind': 'dns',
                                    'message': "Health check failed (DNS resolution error)",
                                    'summary': 'dns resolution error'
                                }
                            else:
                                self.app.logger.warning(
                                    f"Health endpoint request failed: {e}, "
                                    "falling back to process check"
                                )

            
            if process_running:
                return {
                    'healthy': True,
                    'process_running': True,
                    'failure_kind': None,
                    'message': None,
                    'summary': 'process running'
                }
            return {
                'healthy': False,
                'process_running': False,
                'failure_kind': 'process',
                'message': "Tunnel process is not running",
                'summary': 'process not running'
            }
            
        except Exception:
            self.app.logger.error("Error checking process health")
            return {
                'healthy': False,
                'process_running': False,
                'failure_kind': 'internal',
                'message': "Tunnel health check error",
                'summary': 'health check error'
            }
    
    def _attempt_restart(self) -> bool:
        try:
            with self.app.app_context():
                from models import Settings
                
                settings = Settings.query.filter_by(tunnel_enabled=True).first()
                
                if not settings:
                    self.app.logger.error("No enabled tunnel found for restart")
                    return False
                
                user_id = settings.user_id
                
                self.tunnel_manager.stop_tunnel(user_id)
                
                time.sleep(2)
                
                if settings.tunnel_name == 'quick-tunnel':
                    success = self.tunnel_manager.start_quick_tunnel(user_id)
                    
                    if success and settings.cloud_enabled and settings.cloud_api_key:
                        if not settings.cloud_webhook_secret:
                            import secrets
                            settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                            self.db.session.commit()

                        from services.CloudService import CloudService
                        from services.Router import Router
                        cloud_base = CloudService.get_cloud_base_url(settings)
                        self.app.logger.info(f"Re-registering webhook for restarted quick tunnel: {success} with {cloud_base}")
                        self.tunnel_manager.register_webhook(
                            tunnel_url=success,
                            api_key=settings.cloud_api_key,
                            cloud_base_url=cloud_base,
                            user_id=user_id,
                            webhook_secret=settings.cloud_webhook_secret
                        )
                else:
                    success = self.tunnel_manager.start_tunnel(user_id)
                
                if success:
                    settings.tunnel_status = 'connected'
                    settings.tunnel_last_error = None
                    settings.tunnel_restart_count = (settings.tunnel_restart_count or 0) + 1
                    self.db.session.commit()
                    
                    self.app.logger.info(f"Tunnel restarted successfully for user {user_id}")
                    return True
                else:
                    settings.tunnel_status = 'error'
                    settings.tunnel_last_error = 'Automatic restart failed'
                    self.db.session.commit()
                    
                    self.app.logger.error(f"Failed to restart tunnel for user {user_id}")
                    return False
                
        except Exception:
            self.app.logger.error("Error during tunnel restart")
            
            try:
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    
                    if settings:
                        settings.tunnel_status = 'error'
                        settings.tunnel_last_error = 'Restart error'
                        self.db.session.commit()
            except Exception:
                self.app.logger.error("Failed to update database with restart error")
            
            return False
    
    def _should_attempt_restart(self) -> bool:
        cutoff_time = datetime.utcnow() - timedelta(minutes=self.RESTART_WINDOW_MINUTES)
        self.failure_timestamps = [
            ts for ts in self.failure_timestamps 
            if ts > cutoff_time
        ]
        
        if len(self.failure_timestamps) >= self.MAX_RESTART_ATTEMPTS:
            try:
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    
                    if settings and settings.tunnel_status != 'error':
                        settings.tunnel_status = 'error'
                        settings.tunnel_last_error = (
                            f'Restart attempts exhausted ({self.MAX_RESTART_ATTEMPTS} failures '
                            f'in {self.RESTART_WINDOW_MINUTES} minutes)'
                        )
                        self.db.session.commit()
                        
                        self.app.logger.error(
                            f"Restart attempts exhausted for user {settings.user_id}, "
                            "manual intervention required"
                        )
            except Exception:
                self.app.logger.error("Failed to update status after exhausting restarts")
            
            return False
        
        return True
    
    def _record_failure(self):
        self.failure_timestamps.append(datetime.utcnow())
        self.app.logger.debug(
            f"Recorded failure (total in window: {len(self.failure_timestamps)})"
        )
    
    def _record_success(self):
        self.failure_timestamps.clear()
        self.app.logger.debug("Cleared failure history after successful recovery")
    
    def _trigger_auto_recovery(self) -> bool:
        try:
            try:
                from api.routes_webhook import is_webhook_processing
                if is_webhook_processing():
                    self.app.logger.info("Webhook processing active, delaying recovery")
                    return False
            except (ImportError, AttributeError) as e:
                self.app.logger.debug(f"Webhook lock check skipped: {e}")
            
            with self.app.app_context():
                from models import Settings
                
                settings = Settings.query.filter_by(tunnel_enabled=True).first()
                
                if not settings:
                    self.app.logger.error("No enabled tunnel found for auto-recovery")
                    return False
                
                user_id = settings.user_id
                
                if hasattr(settings, 'tunnel_consecutive_failures'):
                    settings.tunnel_consecutive_failures = self.consecutive_failures
                    self.db.session.commit()
                
                return self.tunnel_manager.auto_recover_tunnel(user_id)
                
        except Exception as e:
            self.app.logger.error(f"Error triggering auto-recovery: {e}")
            return False
    
    def _update_health_check_timestamp(self):
        try:
            with self.app.app_context():
                from models import Settings
                
                settings_list = Settings.query.filter_by(tunnel_enabled=True).all()
                
                for settings in settings_list:
                    settings.tunnel_last_health_check = datetime.utcnow()
                
                if settings_list:
                    self.db.session.commit()
                
        except Exception:
            self.app.logger.error("Failed to update health check timestamp")
