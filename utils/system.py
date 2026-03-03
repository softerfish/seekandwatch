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


# update and environment detection functions

import re
import sys
import socket
import shutil
import zipfile
import tempfile
import subprocess
import ipaddress
import requests
from urllib.parse import urlparse

from config import CONFIG_DIR
from utils.helpers import write_log


def check_for_updates(current_version, url):
    """Check if a new version is available"""
    try:
        # github requires a user-agent header
        resp = requests.get(url, headers={'User-Agent': 'SeekAndWatch'}, timeout=3)
        
        if resp.status_code == 200:
            # try parsing as JSON first (github API format)
            try:
                data = resp.json()
                if 'tag_name' in data:
                    remote = data['tag_name'].lstrip('v').strip()
                    local = current_version.lstrip('v').strip()
                    
                    if remote != local:
                        return remote
            except Exception:
                # response may be raw file (e.g. app.py) not JSON; fallback to regex below
                pass

            # fallback: regex search in the raw file (for older releases)
            match = re.search(r'VERSION\s*=\s*"([^"]+)"', resp.text)
            if match:
                remote = match.group(1).lstrip('v').strip()
                local = current_version.lstrip('v').strip()
                if remote != local:
                    return remote
                    
    except Exception:
        print("Update Check Error")
        
    return None


def is_docker():
    """Check if we are running inside a Docker container"""
    path = '/proc/self/cgroup'
    try:
        if os.path.exists('/.dockerenv'):
            return True
        if os.path.isfile(path):
            with open(path, 'r') as f:
                return any('docker' in line for line in f)
    except Exception:
        log.debug("Docker check failed")
    return False


def is_unraid():
    """
    Detect if this is an Unraid App Store install (so we disable one-click updater and show "update via App Store").
    
    Revised Logic:
    - If .git folder exists and is writable, we are running from source (manual install), so allow updates regardless of OS.
    - Only flag as "Unraid App Store" if explicitly marked via env vars (set by template) AND we are not a git repo.
    """
    # if we are a git repo, we are NOT a locked-down App Store container.
    # we allow manual git pulls even on Unraid if the user mapped the volume.
    if is_git_repo():
        return False

    # check for explicit Unraid App Store markers
    if os.environ.get('SEEKANDWATCH_UNRAID') or os.environ.get('SEEKANDWATCH_SOURCE') == 'unraid':
        return True
    
    # check for injected Unraid paths (only if not git repo)
    if os.path.exists('/etc/unraid-version'):
        return True
        
    return False


def is_git_repo():
    """Check if .git exists in app dir or config dir"""
    app_dir = get_app_root()
    return os.path.isdir(os.path.join(app_dir, '.git')) or os.path.isdir(os.path.join(CONFIG_DIR, '.git'))


def get_app_root():
    """Figure out where the app code actually lives"""
    env_root = os.environ.get("APP_DIR")
    if env_root and os.path.isdir(env_root):
        return env_root
    app_subdir = os.path.join(CONFIG_DIR, "app")
    if os.path.isdir(app_subdir):
        return app_subdir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_app_dir_writable():
    """Check if we can write to the app directory (needed for updates)"""
    app_dir = get_app_root()
    return os.path.isdir(app_dir) and os.access(app_dir, os.W_OK)


def _validate_path(path, allowed_dirs, description="path"):
    """
    Validate that a path is within allowed directories and doesn't contain traversal.
    
    Args:
        path: Path to validate
        allowed_dirs: List of allowed directory prefixes
        description: Description for error messages
        
    Returns:
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


def validate_url_safety(url):
    """
    Validate that a URL is safe to fetch (SSRF protection).
    Blocks localhost, private IPs, and AWS metadata.
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


def _copy_tree(src, dst):
    """
    Copy a directory tree safely - validates paths to prevent traversal attacks.
    """
    # only allow copying from temp directories (for updates)
    allowed_src_dirs = []
    temp_dir = tempfile.gettempdir()
    if temp_dir:
        allowed_src_dirs.append(temp_dir)
    # Add common temp directories if they exist
    for temp_path in ['/tmp', '/var/tmp']:
        if os.path.exists(temp_path) and temp_path not in allowed_src_dirs:
            allowed_src_dirs.append(temp_path)
    
    # only allow copying to these directories
    allowed_dst_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
    app_root = get_app_root()
    if app_root and app_root not in allowed_dst_dirs:
        allowed_dst_dirs.append(app_root)
    
    # Validate source path
    src_valid, src_abs, src_error = _validate_path(src, allowed_src_dirs, "source")
    if not src_valid:
        raise ValueError(f"Copy tree validation failed: {src_error}")
    
    # Validate destination path
    dst_valid, dst_abs, dst_error = _validate_path(dst, allowed_dst_dirs, "destination")
    if not dst_valid:
        raise ValueError(f"Copy tree validation failed: {dst_error}")
    
    # Ensure source exists and is a directory
    if not os.path.isdir(src_abs):
        raise ValueError(f"Source path is not a directory: {src_abs}")
    
    # Perform the copy with additional safety checks
    for root, dirs, files in os.walk(src_abs):
        rel = os.path.relpath(root, src_abs)
        target_dir = dst_abs if rel == "." else os.path.join(dst_abs, rel)
        
        # Additional safety: ensure target_dir is still within allowed destination
        target_abs = os.path.abspath(target_dir)
        if not any(target_abs.startswith(os.path.abspath(d) + os.sep) or target_abs == os.path.abspath(d) 
                   for d in allowed_dst_dirs):
            raise ValueError(f"Path traversal detected in copy operation: {target_dir}")
        
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            # Validate filename doesn't contain path traversal
            if '..' in name or '/' in name or '\\' in name:
                continue  # Skip suspicious filenames
            src_file = os.path.join(root, name)
            dst_file = os.path.join(target_dir, name)
            shutil.copy2(src_file, dst_file)


def perform_git_update():
    """
    Update a git install - pulls latest code and reinstalls requirements.
    Has security checks to prevent path traversal attacks.
    """
    try:
        # only allow updates from these directories
        allowed_cwd_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
        app_root = get_app_root()
        if app_root and app_root not in allowed_cwd_dirs:
            allowed_cwd_dirs.append(app_root)
        
        # figure out where the git repo is
        cwd = None
        if os.path.isdir(os.path.join(CONFIG_DIR, '.git')):
            cwd = CONFIG_DIR
        elif app_root and os.path.isdir(os.path.join(app_root, '.git')):
            cwd = app_root
        
        # make sure the directory is safe
        if cwd:
            cwd_valid, cwd_abs, cwd_error = _validate_path(cwd, allowed_cwd_dirs, "working directory")
            if not cwd_valid:
                return False, f"Security validation failed: {cwd_error}"
            cwd = cwd_abs
        
        # Additional check: ensure .git directory exists in validated path
        if cwd and not os.path.isdir(os.path.join(cwd, '.git')):
            return False, "Git repository validation failed: .git directory not found"
            
        # fetch latest changes
        subprocess.check_call(['git', 'fetch'], cwd=cwd, shell=False)
        
        # hard reset to the remote default branch
        subprocess.check_call(['git', 'reset', '--hard', 'origin/main'], cwd=cwd, shell=False)
        
        # reinstall requirements if needed
        req_path = 'requirements.txt'
        if cwd: 
            req_path = os.path.join(cwd, 'requirements.txt')
        
        # Validate req_path is within allowed directories and is actually requirements.txt
        if os.path.exists(req_path):
            req_valid, req_abs, req_error = _validate_path(req_path, allowed_cwd_dirs, "requirements file")
            if not req_valid:
                return False, f"Security validation failed: {req_error}"
            
            # Ensure it's actually named requirements.txt (not a symlink or renamed file)
            if os.path.basename(req_abs) != 'requirements.txt':
                return False, "Security validation failed: requirements file name mismatch"
            
            # Ensure it's a regular file (not a directory or symlink)
            if not os.path.isfile(req_abs):
                return False, "Security validation failed: requirements path is not a file"
            
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', req_abs], shell=False)

        return True, "Update Successful! Restarting..."
    except Exception:
        write_log("error", "Git Update", "Update failed")
        return False, "Git update failed. Please check the logs for details."


def perform_release_update():
    """
    Download the latest release zip from github and extract it.
    Used for non-git installs.
    """
    try:
        app_dir = get_app_root()
        if not is_app_dir_writable():
            return False, "App directory is not writable. Mount the repo or rebuild the image."

        api_url = "https://api.github.com/repos/softerfish/seekandwatch/releases/latest"
        headers = {"User-Agent": "SeekAndWatch"}
        resp = requests.get(api_url, headers=headers, timeout=10)
        if not resp.ok:
            return False, f"GitHub release lookup failed: {resp.status_code}"

        data = resp.json()
        archive_url = data.get("zipball_url") or data.get("tarball_url")
        if not archive_url:
            return False, "GitHub release archive URL not found."

        with tempfile.TemporaryDirectory() as tmpdir:
            archive_path = os.path.join(tmpdir, "release.zip")
            with requests.get(archive_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(archive_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)

            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(tmpdir)

            extracted = [p for p in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, p))]
            if not extracted:
                return False, "Release archive did not contain files."

            release_root = os.path.join(tmpdir, extracted[0])
            _copy_tree(release_root, app_dir)

        req_path = os.path.join(app_dir, "requirements.txt")
        if os.path.exists(req_path):
            # Validate requirements.txt path
            allowed_dirs = [CONFIG_DIR, os.path.join(CONFIG_DIR, 'app')]
            if app_dir not in allowed_dirs:
                allowed_dirs.append(app_dir)
            
            req_valid, req_abs, req_error = _validate_path(req_path, allowed_dirs, "requirements file")
            if not req_valid:
                return False, f"Security validation failed: {req_error}"
            
            # Ensure it's actually named requirements.txt
            if os.path.basename(req_abs) != 'requirements.txt':
                return False, "Security validation failed: requirements file name mismatch"
            
            # Ensure it's a regular file
            if not os.path.isfile(req_abs):
                return False, "Security validation failed: requirements path is not a file"
            
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_abs], shell=False)

        return True, "Release Update Successful! Restarting..."
    except Exception:
        write_log("error", "Release Update", "Update failed")
        return False, "Release update failed. Please check the logs for details."
