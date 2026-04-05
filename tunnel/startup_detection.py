"""
Tunnel provider auto-detection on startup.
Runs once when the app starts to detect and set tunnel_provider for existing users.
Phase 5 Enhancement 2: Also verifies configuration on every startup.
"""
import logging
from models import db, Settings
from tunnel.provider_detection import detect_provider_from_url, detect_provider_from_process
from config import SCHEDULER_USER_ID

logger = logging.getLogger(__name__)

def _normalize_quick_tunnel_defaults(settings):
    """ensure quick tunnel users get the intended defaults on existing installs"""
    if not settings:
        return False
    changed = False
    if (
        getattr(settings, 'tunnel_enabled', False)
        and getattr(settings, 'tunnel_provider', None) == 'cloudflare'
        and getattr(settings, 'tunnel_name', None) == 'quick-tunnel'
    ):
        if hasattr(settings, 'tunnel_auto_recovery_enabled') and not settings.tunnel_auto_recovery_enabled:
            settings.tunnel_auto_recovery_enabled = True
            changed = True
    return changed

def auto_detect_and_set_provider():
    """
    Auto-detect tunnel provider on startup for existing users.
    Only runs if tunnel_provider is NULL (not set yet).
    """
    try:
        # Get settings for the scheduler user (or first user)
        if SCHEDULER_USER_ID is not None:
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
        else:
            settings = Settings.query.first()
        
        if not settings:
            logger.info("No settings found, skipping provider detection")
            return

        if _normalize_quick_tunnel_defaults(settings):
            db.session.commit()
            logger.info("Applied quick tunnel default settings on startup")
        
        # Only auto-detect if provider not set yet
        if settings.tunnel_provider:
            logger.info(f"Tunnel provider already set: {settings.tunnel_provider}")
            return
        
        # Check if tunnel is enabled
        if not settings.tunnel_enabled:
            logger.info("Tunnel not enabled, skipping provider detection")
            return
        
        # Try to detect from webhook URL first
        provider = None
        if settings.cloud_webhook_url:
            provider = detect_provider_from_url(settings.cloud_webhook_url)
            if provider:
                logger.info(f"Detected provider from webhook URL: {provider}")
        
        # If not detected from URL, try process detection
        if not provider:
            provider = detect_provider_from_process()
            if provider:
                logger.info(f"Detected provider from running process: {provider}")
        
        # Set the provider if detected
        if provider:
            settings.tunnel_provider = provider
            db.session.commit()
            logger.info(f"Auto-set tunnel_provider to: {provider}")
        else:
            logger.info("Could not auto-detect tunnel provider")
    
    except Exception as e:
        logger.error(f"Error during provider auto-detection: {e}")
        # Don't crash the app if detection fails


def verify_and_correct_provider():
    """
    Phase 5 Enhancement 2: Verify tunnel_provider matches reality on every startup.
    
    Compares stored provider with actual running process.
    If mismatch detected, logs warning and updates database.
    Helps users recover from database backup restores.
    """
    try:
        from config import os
        
        # check if verification is enabled
        verify_enabled = os.environ.get("VERIFY_TUNNEL_CONFIG_ON_STARTUP", "true").lower() == "true"
        if not verify_enabled:
            logger.debug("Startup verification disabled by config")
            return
        
        # get settings
        if SCHEDULER_USER_ID is not None:
            settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first()
        else:
            settings = Settings.query.first()
        
        if not settings:
            logger.debug("No settings found, skipping verification")
            return

        changed = _normalize_quick_tunnel_defaults(settings)
        
        # only verify if tunnel is enabled
        if not settings.tunnel_enabled:
            if changed:
                db.session.commit()
                logger.info("Applied quick tunnel default settings on startup")
            logger.debug("Tunnel not enabled, skipping verification")
            return
        
        # get stored provider
        stored_provider = settings.tunnel_provider
        
        if not stored_provider:
            if changed:
                db.session.commit()
                logger.info("Applied quick tunnel default settings on startup")
            logger.debug("No provider set, skipping verification (will be auto-detected)")
            return
        
        # skip verification for custom providers
        if stored_provider == 'custom':
            if changed:
                db.session.commit()
                logger.info("Applied quick tunnel default settings on startup")
            logger.debug("Custom provider, skipping verification")
            return
        
        # detect actual provider from running process
        actual_provider = detect_provider_from_process()
        
        if not actual_provider:
            if changed:
                db.session.commit()
                logger.info("Applied quick tunnel default settings on startup")
            # no process running, this is normal (tunnel not started yet)
            logger.debug(f"No tunnel process running (stored provider: {stored_provider})")
            return
        
        # compare stored vs actual
        if stored_provider != actual_provider:
            logger.warning(
                f"Provider mismatch detected! Stored: {stored_provider}, "
                f"Actual: {actual_provider}. Updating database."
            )
            
            # update database to match reality
            settings.tunnel_provider = actual_provider
            db.session.commit()
            
            logger.info(f"Updated tunnel_provider from {stored_provider} to {actual_provider}")
            
            # log event for debugging
            try:
                from services.CloudService import CloudService
                CloudService.log_webhook(
                    'tunnel_config_verification',
                    {
                        'stored_provider': stored_provider,
                        'actual_provider': actual_provider,
                        'action': 'corrected'
                    },
                    'warning',
                    f'Provider mismatch corrected on startup'
                )
            except:
                pass  # don't fail if logging fails
        else:
            if changed:
                db.session.commit()
                logger.info("Applied quick tunnel default settings on startup")
            logger.debug(f"Provider verification passed: {stored_provider}")
    
    except Exception as e:
        logger.error(f"Error during provider verification: {e}")
        # don't crash the app if verification fails
