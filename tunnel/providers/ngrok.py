"""
ngrok tunnel provider implementation (stub for future)

placeholder for ngrok support, to be implemented later
"""

import logging
from typing import Optional, Tuple
from .base import TunnelProvider

log = logging.getLogger(__name__)


class NgrokTunnelProvider(TunnelProvider):
    """ngrok tunnel provider (stub for future implementation)"""
    
    def get_provider_name(self) -> str:
        """get provider name"""
        return 'ngrok'
    
    def supports_auto_recovery(self) -> bool:
        """
        ngrok with static domain doesn't need auto-recovery
        (URL doesn't change)
        """
        return False
    
    def start(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """start ngrok tunnel (not implemented yet)"""
        log.warning("ngrok provider not implemented yet")
        return (False, None)
    
    def stop(self, user_id: int) -> bool:
        """stop ngrok tunnel (not implemented yet)"""
        log.warning("ngrok provider not implemented yet")
        return False
    
    def get_url(self, user_id: int) -> Optional[str]:
        """get ngrok tunnel URL (not implemented yet)"""
        log.warning("ngrok provider not implemented yet")
        return None
    
    def health_check(self, tunnel_url: str) -> bool:
        """check ngrok tunnel health (not implemented yet)"""
        log.warning("ngrok provider not implemented yet")
        return False
