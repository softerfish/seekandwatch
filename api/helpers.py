"""Shared helpers for API endpoints (error responses, logging, path/arr helpers)."""

from flask import current_app
from werkzeug.utils import secure_filename
import os
from urllib.parse import urlparse
import ipaddress

from utils import write_log, BACKUP_DIR


def validate_url_safety(url):
    """Validate URL to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)
        
        # Only allow http/https
        if parsed.scheme not in ['http', 'https']:
            return False
        
        # Block if no hostname
        if not parsed.hostname:
            return False
        
        # Block localhost and private IPs
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            # Not an IP, check hostname
            hostname_lower = parsed.hostname.lower()
            blocked_hosts = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
            if hostname_lower in blocked_hosts or hostname_lower.startswith('192.168.') or hostname_lower.startswith('10.') or hostname_lower.startswith('172.'):
                return False
        
        return True
    except Exception:
        return False


def _log_api_exception(context, exc):
    try:
        exc_type = type(exc).__name__ if exc else "Exception"
        write_log("error", "API", f"{context} failed ({exc_type})")
    except Exception:
        current_app.logger.exception("API logging failed")


def _error_response(message="Request failed", **extra):
    from flask import jsonify
    out = {'status': 'error', 'message': message}
    out.update(extra)
    return jsonify(out)


def _error_payload(message="Request failed"):
    from flask import jsonify
    return jsonify({'error': message})


def _safe_backup_path(filename):
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return None
    root = os.path.abspath(BACKUP_DIR)
    full = os.path.abspath(os.path.join(root, safe_name))
    if os.path.commonpath([root, full]) != root:
        return None
    return full


def _arr_api_list(data):
    """Normalize *arr API response to a list (handles dict with records/data or plain list)."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get('records', data.get('data', []))
    return []


def _arr_error_message(resp, default="Request failed"):
    """Extract error message from a *arr API error response (dict, list of dicts, or text)."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data.get("message", default)
        if isinstance(data, list) and len(data) > 0:
            first = data[0]
            return first.get("message", default) if isinstance(first, dict) else str(first)
    except Exception:
        pass
    return resp.text[:200] if resp.text else default
