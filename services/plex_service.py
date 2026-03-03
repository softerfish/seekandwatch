"""
Plex Service
============

Handles Plex library syncing and GUID resolution.

Functions:
- sync_library() - Sync Plex library to TMDB index
- parse_guid_to_tmdb() - Extract TMDB ID from Plex GUID
- parse_guid_to_imdb() - Extract IMDb ID from Plex GUID
- parse_guid_to_tvdb() - Extract TVDB ID from Plex GUID
- resolve_imdb_to_tmdb() - Resolve IMDb ID to TMDB ID
- resolve_tvdb_to_tmdb() - Resolve TVDB ID to TMDB ID
- resolve_title_year_to_tmdb() - Resolve title+year to TMDB ID
"""

import re
import time
import logging
import os
import requests
from plexapi.server import PlexServer

from models import db, Settings, TmdbAlias
from utils.helpers import write_log, normalize_title
from utils.system import is_system_locked, set_system_lock, remove_system_lock
from config import get_cache_file

log = logging.getLogger(__name__)

# In-memory cache for TVDB->TMDB to avoid repeated API calls in one sync run
_TVDB_TMDB_CACHE = {}

# Cache file path
CACHE_FILE = get_cache_file()


class PlexService:
    """Service for Plex library integration and GUID resolution."""

    @staticmethod
    def parse_guid_to_tmdb(guid_str):
        """Extract TMDB id from a Plex guid string. Returns int or None."""
        if not guid_str:
            return None
        s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
        if not s or 'tmdb' not in s.lower():
            return None
        m = re.search(r'themoviedb\.org/(?:movie|tv)/(\d+)', s) or \
            re.search(r'themoviedb\.org/\?/(?:movie|tv(?:\/show)?)/(\d+)', s) or \
            re.search(r'tmdb://(\d+)', s) or \
            re.search(r'com\.plexapp\.agents\.themoviedb://(\d+)', s)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def parse_guid_to_imdb(guid_str):
        """Extract IMDb id (tt1234567) from a Plex guid string. Returns str or None."""
        if not guid_str:
            return None
        s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
        m = re.search(r'imdb://(tt\d+)', s, re.I) or \
            re.search(r'com\.plexapp\.agents\.imdb://(tt\d+)', s, re.I)
        return m.group(1) if m else None

    @staticmethod
    def parse_guid_to_tvdb(guid_str):
        """Extract TVDB id from a Plex guid string. Returns int or None."""
        if not guid_str:
            return None
        s = (getattr(guid_str, 'id', None) or str(guid_str)).strip()
        m = re.search(r'tvdb://(\d+)', s) or \
            re.search(r'com\.plexapp\.agents\.thetvdb://(\d+)', s)
        return int(m.group(1)) if m else None

    @staticmethod
    def resolve_imdb_to_tmdb(imdb_id, media_type, tmdb_key):
        """Resolve IMDb id to TMDB id via TMDB find API. media_type 'movie' or 'tv'."""
        if not imdb_id or not re.match(r'^tt\d+$', str(imdb_id).strip(), re.I):
            return None
        if not (tmdb_key and str(tmdb_key).strip()):
            return None
        try:
            url = f"https://api.themoviedb.org/3/find/{imdb_id.strip()}?external_source=imdb_id&api_key={tmdb_key.strip()}"
            r = requests.get(url, timeout=10)
            if not r.ok:
                return None
            data = r.json()
            mt = 'movie' if media_type == 'movie' else 'tv'
            if mt == 'movie' and data.get('movie_results'):
                return int(data['movie_results'][0]['id'])
            if mt == 'tv' and data.get('tv_results'):
                return int(data['tv_results'][0]['id'])
            mr = (data.get('movie_results') or [{}])[0].get('id')
            tr = (data.get('tv_results') or [{}])[0].get('id')
            if media_type == 'movie' and mr:
                return int(mr)
            if media_type in ('tv', 'show') and tr:
                return int(tr)
            return int(mr) if mr else (int(tr) if tr else None)
        except Exception:
            log.debug("IMDB->TMDB resolution failed")
            return None

    @staticmethod
    def resolve_tvdb_to_tmdb(tvdb_id, media_type, tmdb_key):
        """Resolve TVDB id to TMDB id via TMDB find API. Uses in-memory cache."""
        global _TVDB_TMDB_CACHE
        tvdb_id = int(tvdb_id) if tvdb_id is not None else 0
        if tvdb_id <= 0 or not (tmdb_key and str(tmdb_key).strip()):
            return None
        key = (tvdb_id, media_type)
        if key in _TVDB_TMDB_CACHE:
            return _TVDB_TMDB_CACHE[key]
        try:
            url = f"https://api.themoviedb.org/3/find/{tvdb_id}?external_source=tvdb_id&api_key={tmdb_key.strip()}"
            r = requests.get(url, timeout=10)
            if not r.ok:
                _TVDB_TMDB_CACHE[key] = None
                return None
            data = r.json()
            mt = 'movie' if media_type == 'movie' else 'tv'
            if mt == 'movie' and data.get('movie_results'):
                _TVDB_TMDB_CACHE[key] = int(data['movie_results'][0]['id'])
                return _TVDB_TMDB_CACHE[key]
            if mt == 'tv' and data.get('tv_results'):
                _TVDB_TMDB_CACHE[key] = int(data['tv_results'][0]['id'])
                return _TVDB_TMDB_CACHE[key]
            mr = (data.get('movie_results') or [{}])[0].get('id')
            tr = (data.get('tv_results') or [{}])[0].get('id')
            out = int(mr) if (media_type == 'movie' and mr) else \
                  (int(tr) if (media_type in ('tv', 'show') and tr) else \
                  (int(mr) if mr else (int(tr) if tr else None)))
            _TVDB_TMDB_CACHE[key] = out
            return out
        except Exception:
            log.debug("TVDB->TMDB resolution failed")
            _TVDB_TMDB_CACHE[key] = None
            return None

    @staticmethod
    def resolve_title_year_to_tmdb(title, year, media_type, tmdb_key):
        """Resolve title + year to TMDB id via TMDB search API. Returns int or None."""
        title = (title or '').strip()
        if not title or not (tmdb_key and str(tmdb_key).strip()):
            return None
        mt = 'tv' if media_type in ('tv', 'show') else 'movie'
        year_param = ''
        if year and re.match(r'^\d{4}$', str(year).strip()):
            y = int(str(year).strip())
            year_param = f"&year={y}" if mt == 'movie' else f"&first_air_date_year={y}"
        try:
            endpoint = 'search/movie' if mt == 'movie' else 'search/tv'
            url = f"https://api.themoviedb.org/3/{endpoint}?api_key={tmdb_key.strip()}&query={requests.utils.quote(title)}{year_param}&page=1"
            r = requests.get(url, timeout=10)
            if not r.ok:
                return None
            data = r.json()
            results = data.get('results') or []
            if not results:
                return None
            return int(results[0]['id'])
        except Exception:
            log.debug("Title/year->TMDB resolution failed")
            return None

    @staticmethod
    def sync_library(app_obj):
        """
        Sync Plex library to TMDB index (TmdbAlias).
        
        First run clears old DB and plex_cache.json.
        Uses guids then IMDB/TVDB/title+year resolution like web.
        Works with both direct URLs (e.g. http://192.168.1.50:32400) and Plex relay (.plex.direct) URLs.
        
        Returns: (success: bool, message: str)
        """
        if is_system_locked():
            return False, "Another task is running. Please wait and try again."

        print("--- STARTING PLEX LIBRARY SYNC (TMDB INDEX) ---")

        with app_obj.app_context():
            settings = Settings.query.first()
            if not settings or not settings.plex_url or not settings.plex_token:
                return False, "Plex not configured."
            if not (getattr(settings, 'tmdb_key', None) and str(settings.tmdb_key).strip()):
                return False, "TMDB API key required to sync library (Settings -> APIs)."

            write_log("info", "Plex", "Started Plex library sync (TMDB index).", app_obj=app_obj)
            set_system_lock("Syncing Plex library...")
            start_time = time.time()

            # Only clear on first run (migration from old way): never completed this sync before
            last_sync = getattr(settings, 'last_alias_scan', None) or 0
            if last_sync == 0:
                try:
                    TmdbAlias.query.delete()
                    db.session.commit()
                    if os.path.exists(CACHE_FILE):
                        try:
                            os.remove(CACHE_FILE)
                        except OSError:
                            pass
                    write_log("info", "Plex", "Cleared TmdbAlias for fresh sync (first run / migration).", app_obj=app_obj)
                except Exception:
                    write_log("warning", "Plex", "Clear before sync failed", app_obj=app_obj)
                    db.session.rollback()

            max_resolve_per_run = 200  # cap IMDB/TVDB/title+year API calls per sync
            resolve_count = 0
            _TVDB_TMDB_CACHE.clear()

            try:
                plex = PlexServer(settings.plex_url, settings.plex_token)
                tmdb_key = settings.tmdb_key.strip()
                added = 0
                sections = plex.library.sections()

                for section in sections:
                    if section.type not in ('movie', 'show'):
                        continue
                    want_type = 'movie' if section.type == 'movie' else 'tv'
                    set_system_lock(f"Scanning {section.title}...")

                    for item in section.all():
                        try:
                            title = getattr(item, 'title', None) or ''
                            year = getattr(item, 'year', None) or 0
                            orig = getattr(item, 'originalTitle', None) or ''
                            guids = getattr(item, 'guids', None) or []

                            tmdb_id = None
                            # 1) TMDB from guid
                            for g in guids:
                                tmdb_id = PlexService.parse_guid_to_tmdb(g)
                                if tmdb_id:
                                    break
                            # 2) IMDB -> TMDB
                            if not tmdb_id and resolve_count < max_resolve_per_run:
                                for g in guids:
                                    imdb_id = PlexService.parse_guid_to_imdb(g)
                                    if imdb_id:
                                        resolve_count += 1
                                        tmdb_id = PlexService.resolve_imdb_to_tmdb(imdb_id, want_type, tmdb_key)
                                        if tmdb_id:
                                            break
                                        time.sleep(0.3)
                            # 3) TVDB -> TMDB
                            if not tmdb_id and resolve_count < max_resolve_per_run:
                                for g in guids:
                                    tvdb_id = PlexService.parse_guid_to_tvdb(g)
                                    if tvdb_id:
                                        resolve_count += 1
                                        tmdb_id = PlexService.resolve_tvdb_to_tmdb(tvdb_id, want_type, tmdb_key)
                                        if tmdb_id:
                                            break
                                        time.sleep(0.3)
                            # 4) Title + year search
                            if not tmdb_id and title and resolve_count < max_resolve_per_run:
                                resolve_count += 1
                                tmdb_id = PlexService.resolve_title_year_to_tmdb(title, year, want_type, tmdb_key)
                                time.sleep(0.3)

                            if tmdb_id and tmdb_id > 0:
                                norm_title = normalize_title(title) if title else ''
                                norm_orig = normalize_title(orig) if orig else norm_title
                                existing = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=want_type).first()
                                if not existing:
                                    db.session.add(TmdbAlias(
                                        tmdb_id=tmdb_id,
                                        media_type=want_type,
                                        plex_title=title or None,
                                        original_title=norm_orig or None,
                                        match_year=int(year) if year else None
                                    ))
                                    added += 1
                            else:
                                # Placeholder so we don't keep retrying
                                if title:
                                    norm_title = normalize_title(title)
                                    if not TmdbAlias.query.filter_by(tmdb_id=-1, plex_title=norm_title).first():
                                        db.session.add(TmdbAlias(tmdb_id=-1, media_type='unknown', plex_title=norm_title))

                            if added % 50 == 0 and added:
                                db.session.commit()
                        except Exception:
                            log.debug("Sync item failed")
                            continue

                db.session.commit()
                settings.last_alias_scan = int(time.time())
                db.session.commit()
                duration = round(time.time() - start_time, 2)
                total = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).count()
                msg = f"Sync completed in {duration}s. Indexed {total} items (TMDB)."
                print(f"--- {msg} ---")
                write_log("success", "Plex", msg, app_obj=app_obj)
                return True, msg

            except Exception:
                db.session.rollback()
                write_log("error", "Plex", "Plex library sync failed. Please check your Plex URL and Token in Settings.")
                return False, "Sync failed. Check application logs."
            finally:
                remove_system_lock()
