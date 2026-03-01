"""
helper utilities

core helper functions used throughout the app,
extracted from utils.py to reduce file size and improve maintainability

critical: this module is used in 6+ files, changes here affect the entire app
"""

import logging
import datetime
import re
from flask import has_app_context, current_app
from models import db, SystemLog, Settings

log = logging.getLogger(__name__)


def _sanitize_log_message(msg):
    """redact URLs and common secret patterns from log messages to avoid leaking credentials"""
    if msg is None:
        return ""
    s = str(msg)
    if not s:
        return s
    # Redact URL-like strings (may contain tokens, API keys)
    s = re.sub(r'https?://[^\s\'"]+', '[URL redacted]', s)
    s = re.sub(r'(password|token|api_key|apikey|secret)=[^\s&]+', r'\1=[REDACTED]', s, flags=re.I)
    return s


def write_log(level, module, message, app_obj=None):
    """
    write a log entry to the database
    
    critical: used in 6+ files, don't change signature
    
    args:
        level: log level (info, warning, error, success)
        module: module name (e.g., "Sync", "Utils", "API")
        message: log message
        app_obj: flask app object (for background tasks)
    """
    # need to handle app context since this might be called from background threads
    try:
        if app_obj:
            with app_obj.app_context():
                _write_log_internal(level, module, message)
        elif has_app_context():
            _write_log_internal(level, module, message)
        else:
            # Try to get app from current context.
            try:
                app = current_app._get_current_object()
                with app.app_context():
                    _write_log_internal(level, module, message)
            except RuntimeError:
                print(f"Logging Failed: No Flask application context available. Level: {level}, Module: {module}, Message: {message}")
    except Exception:
        print("Logging Failed")


def _write_log_internal(level, module, message):
    """internal logging logic, sanitize message to avoid logging URLs/tokens"""
    s = Settings.query.first()
    if s and (s.logging_enabled or level == 'error'):
        log_entry = SystemLog(level=level, category=module, message=_sanitize_log_message(message))
        db.session.add(log_entry)
        db.session.commit()
        
        # Check pruning every 50 logs
        if log_entry.id % 50 == 0:
            limit_mb = s.max_log_size if s.max_log_size is not None else 5
            if limit_mb <= 0:
                return
            
            count = SystemLog.query.count()
            # Average log is roughly 500 bytes with category/timestamp
            estimated_size_mb = (count * 500) / (1024 * 1024)
            
            if estimated_size_mb > limit_mb:
                # Keep roughly the most recent N rows that fit in limit_mb
                max_rows = int((limit_mb * 1024 * 1024) / 500)
                to_delete = count - max_rows
                if to_delete > 0:
                    # Delete in one go
                    subquery = db.session.query(SystemLog.id).order_by(SystemLog.timestamp.asc()).limit(to_delete).all()
                    ids_to_delete = [r[0] for r in subquery]
                    SystemLog.query.filter(SystemLog.id.in_(ids_to_delete)).delete(synchronize_session=False)
                    db.session.commit()
                    
                    # Add a notification that pruning happened
                    notif = SystemLog(level="warn", category="System", message=f"Log limit reached ({limit_mb}MB). Pruned {to_delete} oldest entries.")
                    db.session.add(notif)
                    db.session.commit()


def normalize_title(title):
    """
    normalize a title for matching
    
    critical: used in 4+ files, don't change behavior
    
    handles:
    - special characters
    - accents
    - number words to digits
    - leading "the"
    - case normalization
    
    args:
        title: title string to normalize
        
    returns:
        normalized title (lowercase, alphanumeric only)
    """
    if not title:
        return ""
    
    # Normalize special chars and accents.
    t = str(title).lower()
    replacements = {
        '¢': 'c', '$': 's', '@': 'a', '&': 'and', 
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
        'ñ': 'n', 'ç': 'c'
    }
    
    for char, rep in replacements.items():
        t = t.replace(char, rep)
    
    # Convert common number words to digits for better matching
    # This helps match "Fantastic Four" with "Fantastic 4"
    number_words = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
        'ten': '10', 'eleven': '11', 'twelve': '12', 'thirteen': '13',
        'fourteen': '14', 'fifteen': '15', 'sixteen': '16', 'seventeen': '17',
        'eighteen': '18', 'nineteen': '19', 'twenty': '20'
    }
    for word, num in number_words.items():
        # Match whole words only (with word boundaries)
        t = re.sub(r'\b' + word + r'\b', num, t)
    
    # Strip leading "the " to handle "The Fantastic 4" vs "Fantastic Four"
    t = re.sub(r'^the\s+', '', t)
    
    # Strip non-alphanumeric.
    return re.sub(r'[^a-z0-9]', '', t)

