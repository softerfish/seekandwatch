"""
system utilities

system-level stuff for lock management and environment detection,
extracted from utils.py to reduce file size and improve maintainability

critical: lock management is used in 4+ files, changes here affect concurrent operations
"""

import os
import json
import logging
from config import get_lock_file

log = logging.getLogger(__name__)

# lock file path
LOCK_FILE = get_lock_file()


def is_system_locked():
    """
    check if the system is locked (operation in progress)
    
    critical: used in 4+ files, don't change behavior
    
    returns:
        bool: true if locked, false otherwise
    """
    return os.path.exists(LOCK_FILE)


def set_system_lock(status_msg="Busy"):
    """
    set a system lock to prevent concurrent operations
    
    critical: used in 4+ files, don't change behavior
    
    args:
        status_msg: status message to store in lock file
        
    returns:
        bool: true if lock set successfully, false otherwise
    """
    try:
        with open(LOCK_FILE, 'w') as f:
            json.dump({'stage': status_msg}, f)
        return True
    except Exception as e:
        log.warning(f"Lock status write failed: {e}")
        return False


def remove_system_lock():
    """
    remove the system lock
    
    critical: used in 4+ files, don't change behavior
    """
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except OSError as e:
            log.warning(f"Could not remove lock file: {type(e).__name__}")


def get_lock_status():
    """
    grab the current lock status and progress message
    
    returns:
        dict: {'running': bool, 'progress': str}
    """
    if not os.path.exists(LOCK_FILE):
        return {'running': False}
    try:
        with open(LOCK_FILE, 'r') as f:
            data = json.load(f)
            return {'running': True, 'progress': data.get('stage', 'Busy')}
    except Exception as e:
        log.warning(f"Lock progress read failed: {e}")
        return {'running': True, 'progress': 'Unknown'}


def reset_stuck_locks():
    """
    reset stuck locks (for admin use)
    
    returns:
        tuple: (success: bool, message: str)
    """
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            return True, "Lock file removed"
        return True, "No lock file found"
    except Exception as e:
        return False, f"Failed to remove lock: {e}"

