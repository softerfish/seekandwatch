"""
Health monitoring and automatic recovery for tunnel connections.
"""

import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import TunnelManager


class HealthMonitor:
    """Monitors tunnel health and triggers automatic recovery."""
    
    # restart limits: max 5 attempts within 10-minute window
    MAX_RESTART_ATTEMPTS = 5
    RESTART_WINDOW_MINUTES = 10
    
    def __init__(self, tunnel_manager: 'TunnelManager', check_interval: int = 900):
            """
            Initialize health monitor.

            Args:
                tunnel_manager: TunnelManager instance to monitor
                check_interval: Seconds between health checks (default 900 / 15 minutes)
            """
            self.tunnel_manager = tunnel_manager
            self.check_interval = check_interval
            self.running = False
            self.thread = None
            self.failure_timestamps = []  # track failures for backoff logic
            self.app = tunnel_manager.app  # grab app reference for logging
            self.db = tunnel_manager.db  # grab db reference for updates
            
            # phase 2: consecutive failure tracking for auto-recovery
            self.consecutive_failures = 0  # track consecutive failures (reset on success)
    
    def start(self):
        """Start health monitoring in background thread."""
        if self.running:
            self.app.logger.warning("Health monitor already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._check_loop, daemon=True)
        self.thread.start()
        self.app.logger.info(f"Health monitor started (check interval: {self.check_interval}s)")
    
    def stop(self):
        """Stop health monitoring gracefully."""
        if not self.running:
            return
        
        self.running = False
        
        # wait for thread to finish (with timeout)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            
        self.app.logger.info("Health monitor stopped")
    
    def force_check(self) -> bool:
        """
        Trigger immediate health check.
        
        Returns:
            True if healthy, False otherwise
        """
        return self._check_process_health()
    
    def _check_loop(self):
        """
        Main monitoring loop running in background thread.
        
        Checks tunnel health every check_interval seconds.
        Updates database with tunnel_last_health_check timestamp.
        Phase 2: tracks consecutive failures and triggers auto-recovery on 2nd failure.
        """
        while self.running:
            try:
                # phase 7: skip health checks for external tunnels
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    # if using an external tunnel, we don't manage it - but we do keep the timestamp
                    if settings and getattr(settings, 'tunnel_provider', None) == 'external':
                        settings.tunnel_last_health_check = datetime.utcnow()
                        self.db.session.commit()
                        
                        # sleep and continue
                        sleep_remaining = self.check_interval
                        while sleep_remaining > 0 and self.running:
                            time.sleep(min(1, sleep_remaining))
                            sleep_remaining -= 1
                        continue

                # check if process is healthy
                is_healthy = self._check_process_health()
                
                # update database with health check timestamp
                self._update_health_check_timestamp()
                
                if not is_healthy:
                    # increment consecutive failures
                    self.consecutive_failures += 1
                    
                    # record failure for backoff tracking
                    self._record_failure()
                    
                    # update database with failure info
                    try:
                        with self.app.app_context():
                            from models import Settings
                            from datetime import datetime
                            
                            settings = Settings.query.filter_by(tunnel_enabled=True).first()
                            if settings:
                                settings.tunnel_last_error = f"Health check failed (DNS resolution error)"
                                settings.tunnel_last_failure = datetime.utcnow()
                                if hasattr(settings, 'tunnel_consecutive_failures'):
                                    settings.tunnel_consecutive_failures = self.consecutive_failures
                                self.db.session.commit()
                    except Exception:
                        self.app.logger.error("Failed to update database with failure info")
                    
                    self.app.logger.warning(
                        f"Tunnel health check failed, process not running "
                        f"(consecutive failures: {self.consecutive_failures})"
                    )
                    
                    # phase 2: check if we should trigger auto-recovery
                    if self.consecutive_failures >= 2:
                        # check feature flag
                        from config import ENABLE_AUTO_RECOVERY
                        
                        if ENABLE_AUTO_RECOVERY:
                            self.app.logger.info(
                                f"2 consecutive failures detected, triggering auto-recovery"
                            )
                            
                            # trigger auto-recovery (stub for now)
                            recovery_success = self._trigger_auto_recovery()
                            
                            if recovery_success:
                                # reset consecutive failures on success
                                self.consecutive_failures = 0
                                self.app.logger.info("Auto-recovery succeeded, reset failure counter")
                            else:
                                self.app.logger.warning("Auto-recovery failed or not applicable")
                        else:
                            self.app.logger.debug(
                                "Auto-recovery disabled by feature flag, not triggering"
                            )
                    
                    # attempt restart if allowed by backoff logic (existing behavior)
                    if self._should_attempt_restart():
                        self.app.logger.info("Attempting automatic tunnel restart")
                        
                        restart_success = self._attempt_restart()
                        
                        if restart_success:
                            self._record_success()
                            # reset consecutive failures on successful restart
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
                    # health check passed, reset consecutive failures
                    if self.consecutive_failures > 0:
                        self.app.logger.info(
                            f"Health check passed, resetting consecutive failures "
                            f"(was {self.consecutive_failures})"
                        )
                        self.consecutive_failures = 0
                
                # sleep until next check (but check running flag periodically)
                # this allows stop() to work quickly
                sleep_remaining = self.check_interval
                while sleep_remaining > 0 and self.running:
                    time.sleep(min(1, sleep_remaining))
                    sleep_remaining -= 1
                    
            except Exception:
                self.app.logger.error("Error in health monitor loop")
                # sleep a bit before retrying to avoid tight error loop
                time.sleep(5)
    
    def _check_process_health(self) -> bool:
        """
        Check if cloudflared process is running and tunnel is reachable.
        
        Phase 5 Enhancement 1: Uses dedicated /api/health endpoint for faster checks.
        Falls back to checking process status if HTTP check fails.
        
        Returns:
            True if process is running and healthy, False otherwise
        """
        try:
            # phase 5 enhancement 1: try HTTP health check first
            from config import USE_DEDICATED_HEALTH_ENDPOINT, TUNNEL_HEALTH_ENDPOINT
            
            if USE_DEDICATED_HEALTH_ENDPOINT:
                # get tunnel URL from database
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    
                    if settings and settings.tunnel_url:
                        import requests
                        
                        # construct health check URL
                        health_url = f"{settings.tunnel_url}{TUNNEL_HEALTH_ENDPOINT}"
                        
                        try:
                            # make HTTP request to health endpoint (10 second timeout)
                            response = requests.get(health_url, timeout=10)
                            
                            if response.status_code == 200:
                                # health check passed
                                return True
                            else:
                                self.app.logger.warning(
                                    f"Health endpoint returned {response.status_code}, "
                                    "tunnel is unhealthy"
                                )
                                return False
                        except requests.RequestException as e:
                            # DNS resolution errors, connection errors, etc. mean tunnel is down
                            error_str = str(e)
                            if 'Failed to resolve' in error_str or 'Name or service not known' in error_str or 'NameResolutionError' in error_str:
                                self.app.logger.error(
                                    f"Health endpoint DNS resolution failed: {e}, "
                                    "tunnel URL is not reachable"
                                )
                                return False
                            else:
                                self.app.logger.warning(
                                    f"Health endpoint request failed: {e}, "
                                    "falling back to process check"
                                )

            
            # fallback: use TunnelManager's _is_process_running method
            return self.tunnel_manager._is_process_running()
            
        except Exception:
            self.app.logger.error("Error checking process health")
            return False
    
    def _attempt_restart(self) -> bool:
        """
        Attempt to restart failed tunnel.
        
        Stops the existing process (if any) and starts a new one.
        Updates database status on success/failure.
        
        Returns:
            True if restart succeeded, False otherwise
        """
        try:
            # ensure we're in app context for database operations
            with self.app.app_context():
                # get user_id from settings (find any enabled tunnel)
                from models import Settings
                
                settings = Settings.query.filter_by(tunnel_enabled=True).first()
                
                if not settings:
                    self.app.logger.error("No enabled tunnel found for restart")
                    return False
                
                user_id = settings.user_id
                
                # stop existing process if running
                self.tunnel_manager.stop_tunnel(user_id)
                
                # wait a moment for cleanup
                time.sleep(2)
                
                # start tunnel again
                if settings.tunnel_name == 'quick-tunnel':
                    # quick tunnels need special handling because URL changes
                    success = self.tunnel_manager.start_quick_tunnel(user_id)
                    
                    if success and settings.cloud_enabled and settings.cloud_api_key:
                        # Ensure we have a secret locally
                        if not settings.cloud_webhook_secret:
                            import secrets
                            settings.cloud_webhook_secret = secrets.token_urlsafe(32)
                            self.db.session.commit()

                        # re-register webhook with new URL
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
                    # update status to connected
                    settings.tunnel_status = 'connected'
                    settings.tunnel_last_error = None
                    settings.tunnel_restart_count = (settings.tunnel_restart_count or 0) + 1
                    self.db.session.commit()
                    
                    self.app.logger.info(f"Tunnel restarted successfully for user {user_id}")
                    return True
                else:
                    # update status to error
                    settings.tunnel_status = 'error'
                    settings.tunnel_last_error = 'Automatic restart failed'
                    self.db.session.commit()
                    
                    self.app.logger.error(f"Failed to restart tunnel for user {user_id}")
                    return False
                
        except Exception:
            self.app.logger.error("Error during tunnel restart")
            
            # update database with error
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
        """
        Check if restart should be attempted based on backoff logic.
        
        Limits restart attempts to MAX_RESTART_ATTEMPTS within RESTART_WINDOW_MINUTES.
        If attempts are exhausted, updates status to "error" and returns False.
        
        Returns:
            True if restart is allowed, False if attempts exhausted
        """
        # clean up old failure timestamps (outside the window)
        cutoff_time = datetime.utcnow() - timedelta(minutes=self.RESTART_WINDOW_MINUTES)
        self.failure_timestamps = [
            ts for ts in self.failure_timestamps 
            if ts > cutoff_time
        ]
        
        # check if we've hit the limit
        if len(self.failure_timestamps) >= self.MAX_RESTART_ATTEMPTS:
            # attempts exhausted, update status to error
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
        
        # restart is allowed
        return True
    
    def _record_failure(self):
        """
        Record failure timestamp for backoff calculation.
        
        Adds current timestamp to failure history for restart limiting.
        """
        self.failure_timestamps.append(datetime.utcnow())
        self.app.logger.debug(
            f"Recorded failure (total in window: {len(self.failure_timestamps)})"
        )
    
    def _record_success(self):
        """
        Clear failure history on successful recovery.
        
        Resets failure counter after successful tunnel restart.
        """
        self.failure_timestamps.clear()
        self.app.logger.debug("Cleared failure history after successful recovery")
    
    def _trigger_auto_recovery(self) -> bool:
        """
        Trigger auto-recovery by calling TunnelManager's auto_recover_tunnel method.
        
        Checks if webhook is being processed before triggering recovery.
        
        Returns:
            True if recovery succeeded, False otherwise
        """
        try:
            # check if webhook is being processed
            try:
                from api.routes_webhook import is_webhook_processing
                if is_webhook_processing():
                    self.app.logger.info("Webhook processing active, delaying recovery")
                    return False
            except (ImportError, AttributeError) as e:
                # webhook module not available or function missing, proceed anyway
                self.app.logger.debug(f"Webhook lock check skipped: {e}")
            
            # ensure we're in app context for database operations
            with self.app.app_context():
                from models import Settings
                
                # find enabled tunnel to get user_id
                settings = Settings.query.filter_by(tunnel_enabled=True).first()
                
                if not settings:
                    self.app.logger.error("No enabled tunnel found for auto-recovery")
                    return False
                
                user_id = settings.user_id
                
                # update database with consecutive failures count
                if hasattr(settings, 'tunnel_consecutive_failures'):
                    settings.tunnel_consecutive_failures = self.consecutive_failures
                    self.db.session.commit()
                
                # call TunnelManager's auto_recover_tunnel method
                return self.tunnel_manager.auto_recover_tunnel(user_id)
                
        except Exception as e:
            self.app.logger.error(f"Error triggering auto-recovery: {e}")
            return False
    
    def _update_health_check_timestamp(self):
        """
        Update database with tunnel_last_health_check timestamp.
        
        Updates all enabled tunnels with the current check time.
        """
        try:
            # ensure we're in app context for database operations
            with self.app.app_context():
                from models import Settings
                
                # update all enabled tunnels
                settings_list = Settings.query.filter_by(tunnel_enabled=True).all()
                
                for settings in settings_list:
                    settings.tunnel_last_health_check = datetime.utcnow()
                
                if settings_list:
                    self.db.session.commit()
                
        except Exception:
            self.app.logger.error("Failed to update health check timestamp")
