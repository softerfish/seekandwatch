"""
Custom exceptions for tunnel operations.
"""


class TunnelError(Exception):
    """Base exception for all tunnel-related errors."""
    pass


class BinaryDownloadError(TunnelError):
    """Raised when cloudflared binary download or verification fails."""
    pass


class AuthenticationError(TunnelError):
    """Raised when Cloudflare authentication fails."""
    pass


class TunnelCreationError(TunnelError):
    """Raised when tunnel creation or configuration fails."""
    pass


class ProcessManagementError(TunnelError):
    """Raised when cloudflared process management fails."""
    pass


class WebhookRegistrationError(TunnelError):
    """Raised when webhook URL registration with cloud app fails."""
    pass
