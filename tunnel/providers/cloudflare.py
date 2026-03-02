"""
cloudflare tunnel provider implementation

wraps existing cloudflare tunnel functionality with the provider interface
"""

import logging
import requests
from typing import Optional, Tuple
from .base import TunnelProvider

log = logging.getLogger(__name__)


class CloudflareTunnelProvider(TunnelProvider):
    """cloudflare tunnel provider (quick tunnels and named tunnels)"""
    
    def get_provider_name(self) -> str:
        """get provider name"""
        return 'cloudflare'
    
    def supports_auto_recovery(self) -> bool:
        """
        cloudflare quick tunnels support auto-recovery
        named tunnels don't need it (they're permanent)
        """
        return True
    
    def start(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        start cloudflare tunnel
        
        delegates to existing tunnel.manager.TunnelManager
        """
        try:
            # import here to avoid circular dependency
            from tunnel.manager import TunnelManager
            
            manager = TunnelManager(self.app, self.db)
            success = manager.start_tunnel(user_id)
            
            if success:
                tunnel_url = self.get_url(user_id)
                return (True, tunnel_url)
            else:
                return (False, None)
        except Exception as e:
            log.error(f"Failed to start cloudflare tunnel: {e}")
            return (False, None)
    
    def stop(self, user_id: int) -> bool:
        """
        stop cloudflare tunnel
        
        delegates to existing tunnel.manager.TunnelManager
        """
        try:
            from tunnel.manager import TunnelManager
            
            manager = TunnelManager(self.app, self.db)
            return manager.stop_tunnel(user_id)
        except Exception as e:
            log.error(f"Failed to stop cloudflare tunnel: {e}")
            return False
    
    def get_url(self, user_id: int) -> Optional[str]:
        """get current tunnel URL from database"""
        try:
            from models import Settings
            
            with self.app.app_context():
                settings = Settings.query.filter_by(user_id=user_id).first()
                if settings:
                    return settings.tunnel_url
        except Exception as e:
            log.error(f"Failed to get tunnel URL: {e}")
        
        return None
    
    def health_check(self, tunnel_url: str) -> bool:
        """
        check if tunnel is responding
        
        makes HTTP request to tunnel URL + /api/webhook endpoint
        """
        if not tunnel_url:
            return False
        
        try:
            # construct health check URL
            health_url = f"{tunnel_url.rstrip('/')}/api/webhook"
            
            # make request with short timeout
            response = requests.get(
                health_url,
                timeout=10,
                allow_redirects=True
            )
            
            # consider 200-299 and 401 (auth required) as healthy
            # 401 means tunnel is up, just needs auth
            if 200 <= response.status_code < 300 or response.status_code == 401:
                log.debug(f"Tunnel health check passed: {response.status_code}")
                return True
            else:
                log.warning(f"Tunnel health check failed: {response.status_code}")
                return False
        except requests.exceptions.Timeout:
            log.warning("Tunnel health check timed out")
            return False
        except requests.exceptions.ConnectionError:
            log.warning("Tunnel health check connection error")
            return False
        except Exception as e:
            log.error(f"Tunnel health check error: {e}")
            return False
    
    def is_quick_tunnel(self, tunnel_url: str) -> bool:
        """
        check if this is a quick tunnel (vs named tunnel)
        
        quick tunnels have trycloudflare.com in the URL
        named tunnels have cfargotunnel.com or custom domain
        """
        if not tunnel_url:
            return False
        
        return 'trycloudflare.com' in tunnel_url.lower()
