"""
Cloudflare Tunnel integration for SeekAndWatch.

This package manages the complete lifecycle of Cloudflare tunnels to enable
webhook notifications without manual network configuration.
"""

from .manager import TunnelManager
from .health import HealthMonitor
from .binary import BinaryManager
from .registrar import WebhookRegistrar
from .exceptions import (
    BinaryDownloadError,
    AuthenticationError,
    TunnelCreationError,
    ProcessManagementError,
    WebhookRegistrationError,
)

__all__ = [
    'TunnelManager',
    'HealthMonitor',
    'BinaryManager',
    'WebhookRegistrar',
    'BinaryDownloadError',
    'AuthenticationError',
    'TunnelCreationError',
    'ProcessManagementError',
    'WebhookRegistrationError',
]
