"""webhook security utilities - request signing, validation, rate limiting"""

import hmac
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from models import db
from models_security import WebhookAttempt
from utils.helpers import write_log

# configuration
WEBHOOK_MAX_FAILURES = 5  # lock after 5 failures
WEBHOOK_LOCKOUT_DURATION = 3600  # 1 hour lockout
WEBHOOK_TIMESTAMP_TOLERANCE = 300  # 5 minutes

class WebhookSigner:
    """sign and verify webhook requests"""
    
    @staticmethod
    def sign_request(secret: str, timestamp: int, body: bytes) -> str:
        """create hmac signature for webhook request"""
        message = f"{timestamp}.{body.decode('utf-8')}"
        signature = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    @staticmethod
    def verify_request(secret: str, timestamp: str, body: bytes, 
                       provided_signature: str) -> tuple[bool, str]:
        """verify webhook request signature"""
        try:
            # check timestamp is recent (within 5 minutes)
            request_time = int(timestamp)
            current_time = int(time.time())
            
            if abs(current_time - request_time) > WEBHOOK_TIMESTAMP_TOLERANCE:
                return False, "timestamp expired or invalid"
            
            # verify signature
            expected = WebhookSigner.sign_request(secret, request_time, body)
            
            if not hmac.compare_digest(expected, provided_signature):
                return False, "invalid signature"
            
            return True, "ok"
            
        except (ValueError, TypeError) as e:
            return False, f"validation error: {str(e)}"

class WebhookRateLimiter:
    """rate limiting and lockout for webhook endpoint"""
    
    @staticmethod
    def is_ip_locked_out(ip_address: str) -> tuple[bool, str]:
        """check if ip is locked out due to failed attempts"""
        cutoff = datetime.utcnow() - timedelta(seconds=WEBHOOK_LOCKOUT_DURATION)
        
        try:
            recent_failures = WebhookAttempt.query.filter(
                WebhookAttempt.ip_address == ip_address,
                WebhookAttempt.timestamp > cutoff,
                WebhookAttempt.success == False
            ).count()
            
            if recent_failures >= WEBHOOK_MAX_FAILURES:
                return True, f"too many failed attempts, locked for {WEBHOOK_LOCKOUT_DURATION // 60} minutes"
            
            return False, ""
        except Exception as e:
            write_log("error", "WebhookSecurity", f"lockout check failed: {str(e)}")
            return False, ""
    
    @staticmethod
    def log_attempt(ip_address: str, success: bool, user_agent: str, 
                   failure_reason: Optional[str] = None):
        """log webhook authentication attempt"""
        try:
            attempt = WebhookAttempt(
                ip_address=ip_address,
                success=success,
                user_agent=user_agent,
                failure_reason=failure_reason
            )
            db.session.add(attempt)
            db.session.commit()
        except Exception as e:
            write_log("error", "WebhookSecurity", f"failed to log attempt: {str(e)}")
            db.session.rollback()
    
    @staticmethod
    def clear_attempts(ip_address: str):
        """clear failed attempts after successful authentication"""
        try:
            WebhookAttempt.query.filter_by(
                ip_address=ip_address,
                success=False
            ).delete()
            db.session.commit()
        except Exception as e:
            write_log("error", "WebhookSecurity", f"failed to clear attempts: {str(e)}")
            db.session.rollback()
