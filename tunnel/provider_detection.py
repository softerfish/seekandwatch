"""
tunnel provider detection - passive detection for migration

detects which tunnel provider is currently running based on:
- tunnel URL pattern
- running processes
- configuration files

this is passive detection only (phase 1), doesn't change anything
"""

import logging
import subprocess
import os

log = logging.getLogger(__name__)


def detect_provider_from_url(tunnel_url: str) -> str:
    """
    detect tunnel provider from URL pattern
    
    args:
        tunnel_url: the tunnel URL (e.g. https://example.trycloudflare.com)
        
    returns:
        'cloudflare', 'ngrok', or None
    """
    if not tunnel_url:
        return None
    
    tunnel_url_lower = tunnel_url.lower()
    
    # use domain extraction to avoid substring bypass attacks
    if '.trycloudflare.com' in tunnel_url_lower or tunnel_url_lower.startswith('https://trycloudflare.com'):
        return 'cloudflare'
    elif '.ngrok' in tunnel_url_lower or 'ngrok.io' in tunnel_url_lower or 'ngrok.app' in tunnel_url_lower:
        return 'ngrok'
    elif '.cfargotunnel.com' in tunnel_url_lower or tunnel_url_lower.startswith('https://cfargotunnel.com'):
        return 'cloudflare'  # named tunnel
    
    return None


def detect_provider_from_process() -> str:
    """
    detect tunnel provider from running processes
    
    returns:
        'cloudflare', 'ngrok', or None
    """
    try:
        # check for cloudflared process
        result = subprocess.run(
            ['pgrep', '-f', 'cloudflared'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return 'cloudflare'
        
        # check for ngrok process
        result = subprocess.run(
            ['pgrep', '-f', 'ngrok'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return 'ngrok'
    except Exception as e:
        log.debug(f"Could not detect provider from process: {e}")
    
    return None


def detect_provider(tunnel_url: str = None, check_process: bool = True) -> str:
    """
    detect tunnel provider using multiple methods
    
    args:
        tunnel_url: optional tunnel URL to check
        check_process: whether to check running processes
        
    returns:
        'cloudflare', 'ngrok', or None
    """
    # try URL first (most reliable)
    if tunnel_url:
        provider = detect_provider_from_url(tunnel_url)
        if provider:
            log.info(f"Detected tunnel provider from URL: {provider}")
            return provider
    
    # try process detection
    if check_process:
        provider = detect_provider_from_process()
        if provider:
            log.info(f"Detected tunnel provider from process: {provider}")
            return provider
    
    log.debug("Could not detect tunnel provider")
    return None


def auto_detect_and_set_provider(settings, commit: bool = False):
    """
    auto-detect provider and set in settings if NULL
    
    this is called on startup for existing users who don't have
    tunnel_provider set yet (migration from old version)
    
    args:
        settings: Settings model instance
        commit: whether to commit changes to database
        
    returns:
        detected provider or None
    """
    # only auto-detect if provider is not set
    if hasattr(settings, 'tunnel_provider') and settings.tunnel_provider:
        log.debug(f"Provider already set: {settings.tunnel_provider}")
        return settings.tunnel_provider
    
    # try to detect from tunnel_url
    tunnel_url = getattr(settings, 'tunnel_url', None)
    provider = detect_provider(tunnel_url=tunnel_url, check_process=True)
    
    if provider and hasattr(settings, 'tunnel_provider'):
        log.info(f"Auto-detected tunnel provider: {provider}")
        settings.tunnel_provider = provider
        
        if commit:
            try:
                from models import db
                db.session.commit()
                log.info(f"Set tunnel_provider to {provider}")
            except Exception as e:
                log.error(f"Failed to commit provider detection: {e}")
    
    return provider
