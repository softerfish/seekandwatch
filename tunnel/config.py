"""
Tunnel configuration data structures.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class TunnelConfig:
    """Configuration for a Cloudflare tunnel."""
    
    tunnel_id: str
    tunnel_name: str
    tunnel_url: str
    credentials_path: str
    config_file_path: str
    created_at: datetime
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        data = asdict(self)
        # convert datetime to ISO format string
        data['created_at'] = self.created_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'TunnelConfig':
        """Deserialize from dictionary."""
        # convert ISO format string back to datetime
        if isinstance(data.get('created_at'), str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)
