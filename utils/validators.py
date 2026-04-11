"""
validation utilities

validation and security functions,
extracted from utils.py to reduce file size and improve maintainability
"""

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse
from flask import session

log = logging.getLogger(__name__)


def get_session_filters():
    """
    grab all filter settings from the user's session

    returns:
        tuple: (min_year, min_rating, genre_filter, critic_enabled, threshold)
    """
    try:
        min_year = int(session.get('min_year', 0))
    except (TypeError, ValueError):
        min_year = 0

    try:
        min_rating = float(session.get('min_rating', 0))
    except (TypeError, ValueError):
        min_rating = 0

    genre = session.get('genre_filter')
    genre_filter = genre if genre and genre != 'all' else None

    critic_enabled = session.get('critic_filter') == 'true'
    try:
        threshold = int(session.get('critic_threshold', 70))
    except (TypeError, ValueError):
        threshold = 70

    return min_year, min_rating, genre_filter, critic_enabled, threshold


def validate_service_url(url):
    """
    Validate a user-configured self-hosted service URL.

    This is for trusted local integrations like Plex, Radarr, Sonarr, and Tautulli.
    It intentionally allows loopback and private LAN targets. Do not use this for
    arbitrary external fetches.

    args:
        url: URL to validate

    returns:
        tuple: (is_valid: bool, message: str)
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False, "Invalid protocol (only HTTP/HTTPS allowed)"

        hostname = parsed.hostname
        if not hostname:
            return False, "Invalid hostname"

        # resolve all IPs for this host
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, OSError) as e:
            return False, f"Could not resolve hostname ({type(e).__name__})"

        # check all resolved IPs
        for res in addr_info:
            family, socktype, proto, canonname, sockaddr = res
            ip_str = sockaddr[0]

            if not ip_str:
                continue

            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            # allow loopback IPs for self-hosted usage
            if ip.is_loopback:
                continue

            if ip.is_link_local:
                return False, f"Access to Link-Local ({ip_str}) is denied."

            if ip.is_multicast:
                return False, "Access to Multicast is denied."

            if str(ip) == "0.0.0.0" or str(ip) == "::":
                # Plex relay (*.plex.direct) can resolve to 0.0.0.0/:: on some systems; allow it
                if hostname and hostname.lower().endswith('.plex.direct'):
                    continue
                return False, "Access to 0.0.0.0/:: is denied."

        # allow private IPs (for self-hosted setups)
        return True, "OK"

    except Exception as e:
        log.error(f"Service URL validation error: {e}")
        return False, "Invalid URL format. Please check your configuration."


def validate_external_fetch_url(url):
    """
    Validate that an externally fetched URL is safe to request.

    This is for arbitrary or user-supplied external URLs. It blocks localhost,
    private ranges, and link-local/metadata-style targets.

    args:
        url: URL to validate

    returns:
        tuple: (is_safe: bool, ip: str or None)
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False, None

        # Block schemes other than http/https
        if parsed.scheme not in ('http', 'https'):
            return False, None

        # Check against blacklist
        blacklist = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
        if hostname.lower() in blacklist:
            return False, None

        # Resolve hostname to IP
        try:
            ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            return False, None  # Can't resolve, safer to block

        # Check private IP ranges
        ip_addr = ipaddress.ip_address(ip)
        if ip_addr.is_loopback or ip_addr.is_private or ip_addr.is_link_local:
            return False, None

        # Block AWS metadata specifically (169.254.169.254)
        if str(ip_addr) == "169.254.169.254":
            return False, None

        return True, ip
    except Exception:
        return False, None


def validate_url(url):
    """Backward-compatible alias for validate_service_url."""
    return validate_service_url(url)


def validate_url_safety(url):
    """Backward-compatible alias for validate_external_fetch_url."""
    return validate_external_fetch_url(url)


def validate_path(path, allowed_dirs, description="path"):
    """
    validate that a path is within allowed directories and doesn't contain traversal

    args:
        path: path to validate
        allowed_dirs: list of allowed directory prefixes
        description: description for error messages

    returns:
        tuple: (is_valid: bool, normalized_path: str or None, error_message: str or None)
    """
    if not path:
        return False, None, f"Invalid {description}: path is empty"

    # make it absolute so we can compare properly
    abs_path = os.path.abspath(path)

    # check for .. attempts (path traversal)
    normalized_path = path.replace('\\', '/')
    normalized_abs = abs_path.replace('\\', '/')
    if '..' in normalized_path or '..' in normalized_abs or '/../' in normalized_abs or normalized_abs.endswith('/..'):
        return False, None, f"Invalid {description}: path traversal detected"

    # make sure it's actually inside one of the allowed directories
    for allowed in allowed_dirs:
        allowed_abs = os.path.abspath(allowed)
        try:
            # Check if the path is within the allowed directory
            common = os.path.commonpath([allowed_abs, abs_path])
            if common == allowed_abs:
                return True, abs_path, None
        except ValueError:
            # Paths on different drives (Windows) or invalid
            continue

    return False, None, f"Invalid {description}: path outside allowed directories"


def should_verify_tls(url):
    """
    Return True for public HTTPS targets and False for local/private hosts.

    This preserves compatibility with common self-hosted installs while avoiding
    unconditional TLS verification bypass for public services.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme != 'https':
            return True

        hostname = parsed.hostname
        if not hostname:
            return True

        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, OSError):
            return True

        for res in addr_info:
            ip_str = res[4][0]
            if not ip_str:
                continue
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False

        return True
    except Exception:
        return True

