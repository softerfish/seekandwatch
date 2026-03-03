"""
blueprint for main page routes
handles dashboard, builder, playlists, media pages, etc.
"""

import time
import json
import requests
import concurrent.futures
from pathlib import Path
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, flash
from flask_login import login_required, current_user
from auth_decorators import admin_required

from models import db, Settings, Blocklist, CollectionSchedule, TmdbAlias
from plexapi.server import PlexServer
from presets import PLAYLIST_PRESETS
from config import VERSION, UPDATE_CACHE

# create blueprint
web_pages_bp = Blueprint('web_pages', __name__)

def _get_plex_collection_titles(settings):
    """grab list of collection titles from plex"""
    if not settings or not settings.plex_url or not settings.plex_token:
        return None
    try:
        plex = PlexServer(settings.plex_url, settings.plex_token, timeout=5)
        collections = []
        for section in plex.library.sections():
            if section.type in ['movie', 'show']:
                try:
                    collections.extend([c.title for c in section.collections()])
                except Exception:
                    pass
        return collections
    except Exception:
        return None

def _get_test_description(test_file):
    """extract description from test file docstring"""
    try:
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # find first docstring
            import re
            match = re.search(r'"""(.+?)"""', content, re.DOTALL)
            if match:
                desc = match.group(1).strip().split('\n')[0]
                return desc[:100]
    except:
        pass
    return "No description available"

@web_pages_bp.route('/support')
@login_required
def support_us():
    """support/donation page"""
    return render_template('support.html')

@web_pages_bp.route('/kometa')
@login_required
def kometa():
    """kometa integration page"""
    s = current_user.settings
    return render_template('kometa.html', settings=s)

@web_pages_bp.route('/media')
@login_required
def media():
    """media management page (radarr/sonarr)"""
    s = current_user.settings
    return render_template('media.html', settings=s)

@web_pages_bp.route('/manage_blocklist')
@login_required
def manage_blocklist():
    """blocklist management page"""
    blocks = Blocklist.query.filter_by(user_id=current_user.id).all()
    return render_template('blocklist.html', blocks=blocks)

@web_pages_bp.route('/tests')
@login_required
def test_runner():
    """web-based test runner page"""
    tests_dir = Path('tests')
    test_files = []
    
    if tests_dir.exists():
        for test_file in sorted(tests_dir.glob('test_*.py')):
            test_files.append({
                'name': test_file.name,
                'path': str(test_file),
                'description': _get_test_description(test_file)
            })
    
    return render_template('test_runner.html', test_files=test_files)

@web_pages_bp.route('/scripts')
@login_required
@admin_required
def scripts_runner():
    """scripts runner page (admin only)"""
    scripts_dir = Path('scripts')
    scripts = []
    
    if scripts_dir.exists():
        for script_file in sorted(scripts_dir.glob('*.py')):
            scripts.append({
                'name': script_file.name,
                'path': str(script_file),
                'description': _get_test_description(script_file)
            })
    
    return render_template('scripts_runner.html', scripts=scripts)

@web_pages_bp.route('/playlists')
@login_required
def playlists():
    """playlists/collections management page"""
    s = current_user.settings
    current_time = s.schedule_time if s and s.schedule_time else "04:00"

    # two-way delete - if collection was deleted in plex, remove the sync from app
    plex_titles = _get_plex_collection_titles(s)
    if plex_titles is not None:
        for sch in list(CollectionSchedule.query.all()):
            title = None
            if sch.preset_key.startswith('custom_') and sch.configuration:
                try:
                    cfg = json.loads(sch.configuration)
                    title = cfg.get('title')
                except Exception:
                    pass
            else:
                preset = PLAYLIST_PRESETS.get(sch.preset_key, {})
                title = preset.get('title')
            if title and title not in plex_titles:
                CollectionSchedule.query.filter_by(preset_key=sch.preset_key).delete()
        db.session.commit()

    schedules = {}
    sync_modes = {}
    visibility = {}  # preset_key -> { home, library, friends }
    library_configs = {}  # preset_key -> { target_library_mode, target_libraries }
    for sch in CollectionSchedule.query.all():
        schedules[sch.preset_key] = sch.frequency
        if sch.configuration:
            try:
                config = json.loads(sch.configuration)
                sync_modes[sch.preset_key] = config.get('sync_mode', 'append')
                visibility[sch.preset_key] = {
                    'home': config.get('visibility_home', True),
                    'library': config.get('visibility_library', False),
                    'friends': config.get('visibility_friends', False)
                }
                library_configs[sch.preset_key] = {
                    'target_library_mode': config.get('target_library_mode', 'all'),
                    'target_libraries': config.get('target_libraries', [])
                }
            except Exception:
                sync_modes[sch.preset_key] = 'append'
                visibility[sch.preset_key] = {'home': True, 'library': False, 'friends': False}
                library_configs[sch.preset_key] = {'target_library_mode': 'all', 'target_libraries': []}

    custom_presets = {}
    for sch in CollectionSchedule.query.filter(CollectionSchedule.preset_key.like('custom_%')).all():
        if sch.configuration:
            try:
                config = json.loads(sch.configuration)
                custom_presets[sch.preset_key] = {
                    'title': config.get('title', 'Untitled'),
                    'description': config.get('description', 'Custom Builder Collection'),
                    'media_type': config.get('media_type', 'movie'),
                    'icon': config.get('icon', '🛠️'),
                    'sync_mode': config.get('sync_mode', 'append'),
                    'visibility_home': config.get('visibility_home', True),
                    'visibility_library': config.get('visibility_library', False),
                    'visibility_friends': config.get('visibility_friends', False)
                }
            except Exception:
                pass

    return render_template('playlists.html', 
                           presets=PLAYLIST_PRESETS, 
                           schedules=schedules, 
                           sync_modes=sync_modes,
                           visibility=visibility,
                           library_configs=library_configs,
                           custom_presets=custom_presets,
                           schedule_time=current_time,
                           has_tmdb_key=bool(s and s.tmdb_key),
                           has_plex=bool(s and s.plex_url and s.plex_token),
                           has_library_scan=bool(TmdbAlias.query.first()))

@web_pages_bp.route('/dashboard')
@login_required
def dashboard():
    """main dashboard page"""
    s = current_user.settings
    if not s:
        flash("please complete setup in settings", "error")
        return redirect(url_for('web_settings.settings'))
    
    # check for new versions every 4 hours (don't spam github)
    from utils import check_for_updates
    
    now = time.time()
    if UPDATE_CACHE['version'] is None or (now - UPDATE_CACHE['last_check'] > 14400):
        try:
            latest = check_for_updates(VERSION, "https://raw.githubusercontent.com/softerfish/seekandwatch/main/app.py")
            if latest:
                UPDATE_CACHE['version'] = latest
            UPDATE_CACHE['last_check'] = now
        except Exception:
            pass

    new_version = None
    if UPDATE_CACHE['version'] and UPDATE_CACHE['version'] != VERSION:
        new_version = UPDATE_CACHE['version']
        
    has_tautulli = bool(s.tautulli_url and s.tautulli_api_key)

    # grab plex libraries for display
    plex_libraries = []
    try:
        if s.plex_url and s.plex_token:
            p = PlexServer(s.plex_url, s.plex_token, timeout=2)
            plex_libraries = [sec.title for sec in p.library.sections() if sec.type in ['movie', 'show']]
    except Exception:
        pass
       
    return render_template('dashboard.html', 
                           settings=s, 
                           new_version=new_version,
                           has_omdb=bool(s.omdb_key if s else False),
                           has_tautulli=has_tautulli,
                           plex_libraries=plex_libraries)
