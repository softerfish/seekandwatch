"""
tunnel provider factory

creates the appropriate provider instance based on provider name
"""

import logging
from typing import Optional
from .base import TunnelProvider
from .cloudflare import CloudflareTunnelProvider
from .ngrok import NgrokTunnelProvider

log = logging.getLogger(__name__)


class TunnelFactory:
    """factory for creating tunnel provider instances"""
    
    @staticmethod
    def create(provider_name: str, app, db) -> Optional[TunnelProvider]:
        """
        create a tunnel provider instance
        
        args:
            provider_name: 'cloudflare' or 'ngrok'
            app: Flask application instance
            db: Database instance
            
        returns:
            TunnelProvider instance or None if unknown provider
        """
        if not provider_name:
            log.warning("No provider name specified")
            return None
        
        provider_name_lower = provider_name.lower()
        
        if provider_name_lower == 'cloudflare':
            log.debug("Creating Cloudflare tunnel provider")
            return CloudflareTunnelProvider(app, db)
        elif provider_name_lower == 'ngrok':
            log.debug("Creating ngrok tunnel provider")
            return NgrokTunnelProvider(app, db)
        else:
            log.warning(f"Unknown tunnel provider: {provider_name}")
            return None
    
    @staticmethod
    def get_supported_providers():
        """
        get list of supported provider names
        
        returns:
            list of provider names
        """
        return ['cloudflare', 'ngrok']
