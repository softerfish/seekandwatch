"""Backup and restore functionality for SeekAndWatch"""

import datetime
import os
import threading
import time
import zipfile
from werkzeug.utils import secure_filename

from config import CONFIG_DIR, get_backup_dir, get_database_path
from utils.helpers import write_log

# backup directory
BACKUP_DIR = get_backup_dir()

# ensure backup directory exists (only if parent directory is writable)
try:
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR, exist_ok=True)
except (PermissionError, OSError):
    # in test environments or restricted environments, skip directory creation
    pass


def create_backup():
    """Create a backup of the database"""
    filename = f"backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    filepath = os.path.join(BACKUP_DIR, filename)
    
    with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        db_path = get_database_path()
        if os.path.exists(db_path):
            zipf.write(db_path, arcname='seekandwatch.db')
        # Plex "owned" index is now in TmdbAlias (DB); no longer backing up plex_cache.json
            
    prune_backups()
    return True, filename


def list_backups():
    """List all available backups"""
    if not os.path.exists(BACKUP_DIR):
        return []
    files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.zip')]
    files.sort(reverse=True)
    backups = []
    for f in files:
        path = os.path.join(BACKUP_DIR, f)
        try:
            sz = os.path.getsize(path)
            size_str = f"{round(sz / 1024, 2)} KB" if sz < 1024*1024 else f"{round(sz / (1024*1024), 2)} MB"
            date = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
            backups.append({'filename': f, 'size': size_str, 'date': date})
        except OSError as e:
            write_log("warning", "Utils", f"list_backups stat failed ({type(e).__name__}): {f}")
    return backups


def restore_backup(filename):
    """Restore from a backup file"""
    # Force filename to be just the name, preventing absolute path overrides.
    filename = os.path.basename(filename)
    safe_name = secure_filename(filename)
    if not safe_name or safe_name != filename:
        return False, "Invalid backup filename"

    filepath = os.path.abspath(os.path.join(BACKUP_DIR, filename))
    root = os.path.abspath(BACKUP_DIR)
    if os.path.commonpath([root, filepath]) != root:
        return False, "Invalid backup path"
    if not os.path.exists(filepath):
        return False, "File not found"
    try:
        target_dir = CONFIG_DIR

        # Validate it's actually a zip file.
        if not zipfile.is_zipfile(filepath):
            return False, "Invalid backup file (not a ZIP archive)"
        
        with zipfile.ZipFile(filepath, 'r') as zipf:
            # Check for required files.
            members = zipf.namelist()
            if not members:
                return False, "Backup file is empty"
            
            # Normalize member paths (remove leading slashes, handle subdirectories).
            normalized_members = {}
            for member in members:
                # Skip directories.
                if member.endswith('/'):
                    continue
                
                # Remove leading slashes and normalize.
                clean_member = member.lstrip('/').replace('\\', '/')
                
                # Handle files in subdirectories by extracting the filename.
                if '/' in clean_member:
                    # Backups may have different structures.
                    base_name = os.path.basename(clean_member)
                    # Only allow known backup files.
                    if base_name not in ['seekandwatch.db', 'plex_cache.json']:
                        continue
                    normalized_members[base_name] = member
                else:
                    # File at root. plex_cache.json allowed for old backups but not required
                    if clean_member in ['seekandwatch.db', 'plex_cache.json']:
                        normalized_members[clean_member] = member

            if 'seekandwatch.db' not in normalized_members:
                return False, "Backup file does not contain seekandwatch.db"
            
            # Extract files to target directory.
            for target_name, zip_member in normalized_members.items():
                # Security check: ensure we're not escaping the target directory.
                abs_target = os.path.abspath(os.path.join(target_dir, target_name))
                abs_root = os.path.abspath(target_dir)
                
                if not abs_target.startswith(abs_root + os.sep) and abs_target != abs_root:
                    return False, f"Security check failed for {target_name}"
                
                # Extract the file.
                with zipf.open(zip_member) as source:
                    target_path = os.path.join(target_dir, target_name)
                    with open(target_path, 'wb') as target:
                        target.write(source.read())
            
        # Signal all workers to reopen the DB (multi-worker: only the restoring worker disposed).
        _db_restored_flag = os.path.join(CONFIG_DIR, '.seekandwatch_db_restored')
        try:
            open(_db_restored_flag, 'w').close()
            # Remove flag after a delay so every worker gets a request and disposes; then we stop checking.
            def _remove_flag_later():
                time.sleep(30)
                try:
                    if os.path.exists(_db_restored_flag):
                        os.remove(_db_restored_flag)
                except OSError:
                    pass
            t = threading.Thread(target=_remove_flag_later, daemon=True)
            t.start()
        except OSError:
            pass
        return True, "Restored"
    except zipfile.BadZipFile:
        return False, "Invalid or corrupted ZIP file"
    except Exception:
        write_log("error", "Restore Backup", "Restore failed")
        return False, "Backup restoration failed. Please check the logs for details."


def prune_backups(days=7):
    """Remove old backups, keeping only the most recent"""
    if not os.path.exists(BACKUP_DIR):
        return
    cutoff = time.time() - (days * 86400)
    for f in os.listdir(BACKUP_DIR):
        if not f.endswith('.zip'):
            continue
        path = os.path.join(BACKUP_DIR, f)
        if os.path.getmtime(path) < cutoff:
            try:
                os.remove(path)
            except OSError as e:
                write_log("warning", "Utils", f"Prune backup remove failed ({type(e).__name__}): {path}")
