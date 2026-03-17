"""
Blueprint for utility/API routes
Handles system updates, cloud testing, autodiscovery, and Plex metadata
"""

import json
import socket
import requests
import os
import hashlib
import datetime
from urllib.parse import urlparse, quote_plus
from flask import Blueprint, request, jsonify, Response, send_file
from flask_login import login_required, current_user
from plexapi.server import PlexServer

from models import db, Settings
from utils.helpers import write_log
from utils.system import check_for_updates, is_docker, is_unraid, is_git_repo, is_app_dir_writable, perform_git_update, perform_release_update
from utils.rate_limiter import limiter
from services.CloudService import CloudService
from config import VERSION, CLOUD_REQUEST_TIMEOUT

# Create blueprint
web_utility_bp = Blueprint('web_utility', __name__)

@web_utility_bp.route('/trigger_update', methods=['POST'])
@limiter.limit("10 per hour")
@login_required
def trigger_update_route():
    """One-click updater for git/release installs (CSRF required via X-CSRFToken in fetch)"""
    
    # Allow the confirm modal to force an update.
    force_update = request.args.get('force_git') == 'true'
    
    try:
        # Check latest release.
        current_version = "Unknown"
        try: current_version = VERSION
        except Exception: pass
        latest = check_for_updates(current_version, "https://api.github.com/repos/softerfish/seekandwatch/releases/latest")
        if not latest and not force_update:
             return Response(json.dumps({'status': 'success', 'message': 'Up to date', 'action': 'none'}), mimetype='application/json')

        # unraid users have to update through the app store, can't do it here
        if is_unraid():
            return Response(json.dumps({
                'status': 'success',
                'message': 'Update available!',
                'action': 'unraid_instruction',
                'version': str(latest)
            }), mimetype='application/json')

        if not is_git_repo() and not force_update:
            if is_app_dir_writable():
                return Response(json.dumps({
                    'status': 'success',
                    'message': 'Update available',
                    'action': 'release_update_available',
                    'version': str(latest)
                }), mimetype='application/json')
            if is_docker():
                return Response(json.dumps({
                    'status': 'success',
                    'message': 'Update available!',
                    'action': 'docker_instruction',
                    'version': str(latest)
                }), mimetype='application/json')
            return Response(json.dumps({'status': 'success', 'message': 'Manual update required', 'action': 'manual_instruction', 'version': str(latest)}), mimetype='application/json')

        # Manual (git) installs: ask for confirmation before pulling.
        if is_git_repo() and not force_update:
            return Response(json.dumps({
                'status': 'success',
                'message': 'Update available',
                'action': 'git_update_available',
                'version': str(latest)
            }), mimetype='application/json')

        # git updates are preferred if available
        if is_git_repo():
            print(f"--- Git Update Triggered (Force: {force_update}) ---", flush=True)
            success, msg = perform_git_update()
            action = 'restart_needed' if success else 'error'
            status = 'success' if success else 'error'
            return Response(json.dumps({'status': status, 'message': msg, 'action': action}), mimetype='application/json')

        # No git repo: try a release update when forced.
        if force_update:
            success, msg = perform_release_update()
            action = 'restart_needed' if success else 'error'
            status = 'success' if success else 'error'
            return Response(json.dumps({'status': status, 'message': msg, 'action': action}), mimetype='application/json')

        return Response(json.dumps({'status': 'error', 'message': 'Update failed to determine path.'}), mimetype='application/json')

    except Exception as e:
        try:
            # Do not log full traceback or exception message (clear-text logging of sensitive information)
            write_log("error", "Updater", f"Update failed: {type(e).__name__}")
        except Exception:
            pass
        print("Update Error (see logs).", flush=True)
        return Response(json.dumps({'status': 'error', 'message': 'Update failed. Check logs for details.'}), mimetype='application/json')

@web_utility_bp.route('/api/settings/autodiscover', methods=['POST'])
@login_required
def settings_autodiscover():
    """Probe common local ports to find co-located services."""
    services = {
        'Plex': {'port': 32400, 'paths': ['/identity', '/'], 'key': 'plex_url'},
        'Radarr': {'port': 7878, 'paths': ['/api/v3/system/status', '/login'], 'key': 'radarr_url'},
        'Sonarr': {'port': 8989, 'paths': ['/api/v3/system/status', '/login'], 'key': 'sonarr_url'},
        'Tautulli': {'port': 8181, 'paths': ['/api/v2', '/login', '/'], 'key': 'tautulli_url'},
    }
    
    # Identify all local IPs to check
    ips_to_check = set(['127.0.0.1'])
    
    # 1. Detected Server IP
    host_header = request.headers.get('Host', '')
    if host_header:
        detected_ip = host_header.split(':')[0].strip().lower()
        if detected_ip and detected_ip not in ['localhost', '127.0.0.1', '0.0.0.0'] and not detected_ip.endswith('.trycloudflare.com'):
            ips_to_check.add(detected_ip)
            
    # 2. All machine IPs (in case of multiple interfaces)
    try:
        hostname = socket.gethostname()
        for addr in socket.gethostbyname_ex(hostname)[2]:
            if not addr.startswith('127.'):
                ips_to_check.add(addr)
    except: pass

    found = {}
    for ip in ips_to_check:
        for name, info in services.items():
            if info['key'] in found: continue
            
            # Check both http and https
            for proto in ['http', 'https']:
                if info['key'] in found: break
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.3)
                        if s.connect_ex((ip, info['port'])) == 0:
                            url = f"{proto}://{ip}:{info['port']}"
                            for path in info['paths']:
                                try:
                                    r = requests.get(f"{url}{path}", timeout=0.8, verify=False)
                                    if r.status_code in [200, 401, 302, 403]: # 403 can also mean it's there but blocked
                                        found[info['key']] = url
                                        break
                                except: continue
                except: pass
            
    return jsonify({'status': 'success', 'found': found})

@web_utility_bp.route('/api/plex/metadata')
@login_required
def plex_metadata_api():
    """Asynchronously fetch Plex users and libraries for settings UI."""
    s = current_user.settings
    if not s or not s.plex_url or not s.plex_token:
        return jsonify({'users': [], 'libraries': []})
        
    plex_users = []
    plex_libraries = []
    
    try:
        p = PlexServer(s.plex_url, s.plex_token, timeout=5)
        # 1. Users
        try:
            account = p.myPlexAccount()
            plex_users = [u.title for u in account.users()]
            if account.username: plex_users.insert(0, account.username)
        except:
            # Fallback to current username if MyPlex fails
            try: plex_users.append(p.myPlexAccount().username)
            except: pass
            
        # 2. Libraries
        try:
            plex_libraries = [sec.title for sec in p.library.sections() if sec.type in ['movie', 'show']]
        except: pass
        
    except Exception:
        from utils.helpers import write_log
        write_log("error", "Utility", "Failed to fetch Plex users/libraries")
        return jsonify({'error': 'Failed to fetch Plex data', 'users': [], 'libraries': []})
        
    return jsonify({
        'users': plex_users, 
        'libraries': plex_libraries,
        'current_ignored': (s.ignored_users or "").split(','),
        'current_ignored_libs': (s.ignored_libraries or "").split(',')
    })

@web_utility_bp.route('/api/proxy/image')
@login_required
@limiter.limit("300 per minute")
def image_proxy():
    """Proxies images from TMDB or Plex to avoid Mixed Content / SSL issues."""
    target_url = request.args.get('url')
    if not target_url:
        return "Missing URL", 400

    # 1. SSRF Protection & Validation
    try:
        parsed = urlparse(target_url)
        s = current_user.settings
        
        is_tmdb = parsed.netloc == 'image.tmdb.org'
        is_plex = False
        
        if s and s.plex_url:
            plex_host = urlparse(s.plex_url).netloc
            if parsed.netloc == plex_host:
                is_plex = True
        
        if not is_tmdb and not is_plex:
            write_log("warning", "Security", f"Blocked proxy attempt to untrusted domain: {parsed.netloc}")
            return "Forbidden: Domain not in allowlist", 403
            
        # Reconstruct URL to prevent SSRF (CodeQL)
        if is_tmdb:
            target_url = f"https://image.tmdb.org{parsed.path}"
        elif is_plex:
            plex_base = s.plex_url.rstrip('/')
            target_url = f"{plex_base}{parsed.path}"
            
        if parsed.query:
            target_url += f"?{parsed.query}"
            
    except Exception as e:
        return f"Invalid URL: {type(e).__name__}", 400

    # 2. Caching Logic
    cache_dir = os.path.join('assets', 'cache', 'images')
    if not os.path.exists(cache_dir):
        try: os.makedirs(cache_dir, exist_ok=True)
        except: pass # fallback to no cache if cannot create dir
        
    cache_key = hashlib.md5(target_url.encode()).hexdigest()
    cache_path = os.path.join(cache_dir, cache_key)
    
    # Check if cached and not expired (7 days)
    use_cache = False
    if os.path.exists(cache_path):
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cache_path))
        if (datetime.datetime.now() - mtime).days < 7:
            use_cache = True
        else:
            try: os.remove(cache_path) # Expired
            except: pass

    if use_cache:
        try:
            return send_file(cache_path, conditional=True, max_age=86400) # 24h browser cache
        except: pass # fallback to fetch if file read fails

    # 3. Fetch from source
    try:
        headers = {'User-Agent': 'SeekAndWatch/1.0'}
        r = requests.get(target_url, headers=headers, stream=True, timeout=5, verify=False)
        
        if not r.ok:
            # Smart Fallback (TMDB): if Plex 404s, try fetching from TMDB if IDs provided
            tmdb_id = request.args.get('tmdb_id')
            media_type = request.args.get('media_type', 'movie')
            if is_plex and r.status_code == 404 and tmdb_id and s and s.tmdb_key:
                try:
                    # try to find the poster path on TMDB
                    t_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={s.tmdb_key}"
                    tr = requests.get(t_url, timeout=3)
                    if tr.ok:
                        p_path = tr.json().get('poster_path')
                        if p_path:
                            # Recurse with TMDB URL
                            return Response(f"<script>location.href='/api/proxy/image?url=https://image.tmdb.org/t/p/w500{p_path}'</script>", mimetype='text/html')
                except: pass
            
            return f"Source Error: {r.status_code}", 404
            
        # Verify Content-Type (Only images)
        content_type = r.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            return "Forbidden: Not an image", 403

        # 4. Stream and Cache
        image_data = r.content # Read into memory for caching
        
        # Check disk space safety (>5MB remaining on disk, simplified)
        try:
            if os.path.exists(cache_dir):
                # Write to cache
                with open(cache_path, 'wb') as f:
                    f.write(image_data)
        except: pass
        
        res = Response(image_data, content_type=content_type)
        res.headers['Cache-Control'] = 'public, max-age=86400' # 24h browser cache
        return res

    except Exception as e:
        return f"Fetch Failed: {type(e).__name__}", 500
