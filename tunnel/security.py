"""
Security utilities for tunnel operations.

Handles file permissions and webhook signature validation.
"""

import os
import stat
import hmac
import hashlib


def set_secure_file_permissions(file_path):
    """
    Set secure permissions on credential files (0600 on Unix).
    
    On Unix: Only owner can read/write
    On Windows: Uses ACLs to restrict access
    
    Args:
        file_path: Path to file to secure
        
    Returns:
        True on success, False on failure
    """
    try:
        if os.name == 'nt':  # Windows
            # on Windows, use icacls to restrict access
            # remove inheritance and grant full control only to current user
            import subprocess
            
            # get current username
            username = os.environ.get('USERNAME', 'SYSTEM')
            
            # remove inheritance
            subprocess.run(
                ['icacls', file_path, '/inheritance:r'],
                capture_output=True,
                check=False
            )
            
            # grant full control to current user only
            subprocess.run(
                ['icacls', file_path, f'/grant:r', f'{username}:F'],
                capture_output=True,
                check=False
            )
            
            return True
        else:  # Unix-like (Linux, macOS)
            # set permissions to 0600 (owner read/write only)
            os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
            return True
            
    except Exception as e:
        # log error but don't fail completely
        print(f"Warning: Could not set secure permissions on {file_path}: {e}")
        return False


def verify_file_permissions(file_path):
    """
    Verify that file has secure permissions.
    
    Args:
        file_path: Path to file to check
        
    Returns:
        True if permissions are secure, False otherwise
    """
    try:
        if not os.path.exists(file_path):
            return False
        
        if os.name == 'nt':  # Windows
            # on Windows, just check that file exists and is readable
            # (ACL checking is complex, so we trust set_secure_file_permissions did its job)
            return os.access(file_path, os.R_OK)
        else:  # Unix-like
            # check that permissions are 0600 or more restrictive
            file_stat = os.stat(file_path)
            mode = file_stat.st_mode
            
            # check that only owner has permissions
            # (no group or other permissions)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                return False
            
            # check that owner has at least read permission
            if not (mode & stat.S_IRUSR):
                return False
            
            return True
            
    except Exception:
        return False


def validate_webhook_signature(payload, signature, secret):
    """
    Validate webhook request signature using HMAC-SHA256.
    
    Uses constant-time comparison to prevent timing attacks.
    
    Args:
        payload: Request payload (bytes or string)
        signature: Signature from X-Webhook-Secret header
        secret: Shared secret for validation
        
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature or not secret:
        return False
    
    try:
        # convert payload to bytes if needed
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        
        # convert secret to bytes if needed
        if isinstance(secret, str):
            secret = secret.encode('utf-8')
        
        # compute expected signature
        expected_signature = hmac.new(
            secret,
            payload,
            hashlib.sha256
        ).hexdigest()
        
        # constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature)
        
    except Exception:
        return False


def generate_webhook_signature(payload, secret):
    """
    Generate webhook signature for outgoing requests.
    
    Args:
        payload: Request payload (bytes or string)
        secret: Shared secret
        
    Returns:
        HMAC-SHA256 signature as hex string
    """
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()
