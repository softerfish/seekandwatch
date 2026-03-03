"""
base tunnel provider interface

defines the contract that all tunnel providers must implement
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple


class TunnelProvider(ABC):
    """abstract base class for tunnel providers"""
    
    def __init__(self, app, db):
        """
        initialize provider
        
        args:
            app: Flask application instance
            db: Database instance
        """
        self.app = app
        self.db = db
    
    @abstractmethod
    def start(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        start the tunnel
        
        args:
            user_id: user ID for database updates
            
        returns:
            tuple: (success: bool, tunnel_url: str or None)
        """
        pass
    
    @abstractmethod
    def stop(self, user_id: int) -> bool:
        """
        stop the tunnel
        
        args:
            user_id: user ID for database updates
            
        returns:
            bool: true if successful
        """
        pass
    
    @abstractmethod
    def get_url(self, user_id: int) -> Optional[str]:
        """
        get current tunnel URL
        
        args:
            user_id: user ID for database lookup
            
        returns:
            str: tunnel URL or None
        """
        pass
    
    @abstractmethod
    def health_check(self, tunnel_url: str) -> bool:
        """
        check if tunnel is healthy
        
        args:
            tunnel_url: URL to check
            
        returns:
            bool: true if healthy
        """
        pass
    
    @abstractmethod
    def supports_auto_recovery(self) -> bool:
        """
        check if this provider supports auto-recovery
        
        returns:
            bool: true if auto-recovery is supported
        """
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """
        get provider name
        
        returns:
            str: provider name ('cloudflare', 'ngrok', etc.)
        """
        pass
