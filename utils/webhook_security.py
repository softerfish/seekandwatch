"""webhook security utilities - request signing, validation, rate limiting"""

import hmac
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
from models import db
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
