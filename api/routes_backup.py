"""Backup API: list, create, download, delete, restore, upload."""

import os
import tempfile
import zipfile

from flask import request, jsonify, send_from_directory
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from auth_decorators import admin_required
from models import db
from utils import (
    create_backup,
    list_backups,
    restore_backup,
    BACKUP_DIR,
)
from api import api_bp, rate_limit_decorator
from api.helpers import _safe_backup_path, _log_api_exception, _error_response


@api_bp.route('/api/backups')
@login_required
@admin_required
def get_backups_api():
    return jsonify(list_backups())


@api_bp.route('/api/backup/create', methods=['POST'])
@rate_limit_decorator("10 per hour")
@login_required
@admin_required
def trigger_backup():
    success, msg = create_backup()
    return jsonify({'status': 'success', 'message': msg}) if success else jsonify({'status': 'error', 'message': msg})


@api_bp.route('/api/backup/download/<filename>')
@login_required
@admin_required
def download_backup(filename):
    safe_path = _safe_backup_path(filename)
    if not safe_path or not os.path.exists(safe_path):
        return "Invalid", 400
    return send_from_directory(BACKUP_DIR, os.path.basename(safe_path), as_attachment=True)


@api_bp.route('/api/backup/delete/<filename>', methods=['DELETE'])
@login_required
@admin_required
def delete_backup_api(filename):
    safe_path = _safe_backup_path(filename)
    if not safe_path:
        return jsonify({'status': 'error'})
    if os.path.exists(safe_path):
        os.remove(safe_path)
    return jsonify({'status': 'success'})


@api_bp.route('/api/backup/restore/<filename>', methods=['POST'])
@rate_limit_decorator("5 per hour")
@login_required
@admin_required
def run_restore(filename):
    safe_path = _safe_backup_path(filename)
    if not safe_path:
        return jsonify({'status': 'error', 'message': 'Invalid filename'})
    success, msg = restore_backup(os.path.basename(safe_path))
    return jsonify({'status': 'success' if success else 'error', 'message': msg})


@api_bp.route('/api/backup/upload', methods=['POST'])
@rate_limit_decorator("5 per hour")
@login_required
@admin_required
def upload_backup():
    file = request.files.get('backup_file')
    if not file or not file.filename:
        return jsonify({'status': 'error', 'message': 'No file uploaded.'})

    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.zip'):
        return jsonify({'status': 'error', 'message': 'Only .zip backups are supported.'})

    max_upload_bytes = 50 * 1024 * 1024
    max_unzipped_bytes = 200 * 1024 * 1024
    max_entries = 10
    allowed_files = {'seekandwatch.db', 'plex_cache.json'}  # plex_cache.json optional (legacy)

    content_len = request.content_length
    if content_len and content_len > max_upload_bytes:
        return jsonify({'status': 'error', 'message': 'Backup is too large.'})

    os.makedirs(BACKUP_DIR, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=BACKUP_DIR, prefix="upload_", suffix=".zip") as tmp:
            tmp_path = tmp.name
            file.save(tmp_path)

        if not zipfile.is_zipfile(tmp_path):
            os.remove(tmp_path)
            return jsonify({'status': 'error', 'message': 'Invalid backup file (not a ZIP archive).'})

        total_size = 0
        found = set()
        with zipfile.ZipFile(tmp_path, 'r') as zipf:
            entries = zipf.infolist()
            if len(entries) > max_entries:
                os.remove(tmp_path)
                return jsonify({'status': 'error', 'message': 'Backup contains too many files.'})

            for info in entries:
                name = info.filename.replace('\\', '/')
                if not name or name.endswith('/'):
                    continue
                if name.startswith('/') or name.startswith('../') or '/..' in name:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains unsafe paths.'})
                if ':' in name.split('/')[0]:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains unsafe paths.'})

                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup contains a symbolic link.'})

                base = os.path.basename(name)
                if base in allowed_files:
                    found.add(base)
                else:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': f'Unexpected file in backup: {base}'})

                total_size += info.file_size
                if total_size > max_unzipped_bytes:
                    os.remove(tmp_path)
                    return jsonify({'status': 'error', 'message': 'Backup expands too large.'})

        if not found:
            os.remove(tmp_path)
            return jsonify({'status': 'error', 'message': 'Backup is missing required files.'})

        base, ext = os.path.splitext(filename)
        target = os.path.join(BACKUP_DIR, filename)
        counter = 1
        while os.path.exists(target):
            filename = f"{base}_{counter}{ext}"
            target = os.path.join(BACKUP_DIR, filename)
            counter += 1

        os.replace(tmp_path, target)
        tmp_path = None
        return jsonify({'status': 'success', 'message': f'Backup uploaded as {filename}.'})
    except Exception as e:
        _log_api_exception("upload_backup", e)
        return _error_response("Upload failed")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
