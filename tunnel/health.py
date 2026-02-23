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
    
    def __init__(self, tunnel_manager: 'TunnelManager', check_interval: int = 60):
        """
        Initialize health monitor.
        
        Args:
            tunnel_manager: TunnelManager instance to monitor
            check_interval: Seconds between health checks (default 60)
        """
        self.tunnel_manager = tunnel_manager
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        self.failure_timestamps = []  # track failures for backoff logic
        self.app = tunnel_manager.app  # grab app reference for logging
        self.db = tunnel_manager.db  # grab db reference for updates
    
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
        """
        while self.running:
            try:
                # check if process is healthy
                is_healthy = self._check_process_health()
                
                # update database with health check timestamp
                self._update_health_check_timestamp()
                
                if not is_healthy:
                    self.app.logger.warning("Tunnel health check failed, process not running")
                    
                    # attempt restart if allowed by backoff logic
                    if self._should_attempt_restart():
                        self.app.logger.info("Attempting automatic tunnel restart")
                        
                        restart_success = self._attempt_restart()
                        
                        if restart_success:
                            self._record_success()
                            self.app.logger.info("Tunnel restarted successfully")
                        else:
                            self._record_failure()
                            self.app.logger.error("Tunnel restart failed")
                    else:
                        self.app.logger.warning(
                            "Restart attempts exhausted, not attempting restart "
                            f"({len(self.failure_timestamps)} failures in last {self.RESTART_WINDOW_MINUTES} minutes)"
                        )
                
                # sleep until next check (but check running flag periodically)
                # this allows stop() to work quickly
                sleep_remaining = self.check_interval
                while sleep_remaining > 0 and self.running:
                    time.sleep(min(1, sleep_remaining))
                    sleep_remaining -= 1
                    
            except Exception as e:
                self.app.logger.error(f"Error in health monitor loop: {str(e)}")
                # sleep a bit before retrying to avoid tight error loop
                time.sleep(5)
    
    def _check_process_health(self) -> bool:
        """
        Check if cloudflared process is running.
        
        Verifies process status by checking PID and process state.
        
        Returns:
            True if process is running and healthy, False otherwise
        """
        try:
            # use TunnelManager's _is_process_running method
            return self.tunnel_manager._is_process_running()
        except Exception as e:
            self.app.logger.error(f"Error checking process health: {str(e)}")
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
                    
                    if success and settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
                        # re-register webhook with new URL
                        self.app.logger.info(f"Re-registering webhook for restarted quick tunnel: {success}")
                        self.tunnel_manager.register_webhook(
                            tunnel_url=success,
                            api_key=settings.cloud_api_key,
                            cloud_base_url=settings.cloud_base_url,
                            user_id=user_id,
                            webhook_secret=settings.cloud_webhook_secret or ''
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
                
        except Exception as e:
            self.app.logger.error(f"Error during tunnel restart: {str(e)}")
            
            # update database with error
            try:
                with self.app.app_context():
                    from models import Settings
                    settings = Settings.query.filter_by(tunnel_enabled=True).first()
                    
                    if settings:
                        settings.tunnel_status = 'error'
                        settings.tunnel_last_error = f'Restart error: {str(e)}'
                        self.db.session.commit()
            except Exception as db_error:
                self.app.logger.error(f"Failed to update database with restart error: {str(db_error)}")
            
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
            except Exception as e:
                self.app.logger.error(f"Failed to update status after exhausting restarts: {str(e)}")
            
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
                
        except Exception as e:
            self.app.logger.error(f"Failed to update health check timestamp: {str(e)}")
