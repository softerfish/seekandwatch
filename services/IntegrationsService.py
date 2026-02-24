"""
IntegrationsService - Handles all communication with Radarr, Sonarr, and Overseerr.
Ensures that adding items to your media managers is independent of other app features.
"""

import logging
import requests
import json
import time
from flask import current_app
from models import db, RadarrSonarrCache, Settings, TmdbAlias
from utils import write_log, normalize_title, is_system_locked, set_system_lock, remove_system_lock

log = logging.getLogger(__name__)

class IntegrationsService:
    @staticmethod
    def get_radarr_sonarr_cache(media_type=None):
        """Get cached items from Radarr/Sonarr that have a file on disk."""
        try:
            query = RadarrSonarrCache.query
            if media_type:
                query = query.filter_by(media_type=media_type)
            items = query.all()
            titles = set()
            tmdb_ids = set()
            for item in items:
                if getattr(item, 'has_file', True) is not True:
                    continue
                if item.title:
                    titles.add(item.title)
                if item.tmdb_id and item.tmdb_id > 0:
                    tmdb_ids.add(item.tmdb_id)
            return {'titles': titles, 'tmdb_ids': tmdb_ids}
        except Exception:
            write_log("warning", "Integrations", "get_radarr_sonarr_cache failed")
            return {'titles': set(), 'tmdb_ids': set()}

    @staticmethod
    def send_to_overseerr(settings, media_type, tmdb_id, uid=None):
        """Sends a request to Overseerr/Jellyseerr."""
        if not settings.overseerr_url or not settings.overseerr_api_key:
            return False, "Overseerr settings missing."
            
        headers = {'X-Api-Key': settings.overseerr_api_key, "Content-Type": "application/json"}
        base_url = settings.overseerr_url.rstrip('/')
        
        try:
            payload = {
                'mediaType': media_type,
                'mediaId': int(tmdb_id),
                'is4k': False
            }
            
            if media_type == 'tv':
                seasons = []
                try:
                    resp = requests.get(f"{base_url}/api/v1/tv/{tmdb_id}", headers=headers, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        for s in data.get('seasons', []):
                            if s.get('seasonNumber', 0) > 0 and s.get('status', 0) != 3:
                                seasons.append(s.get('seasonNumber'))
                except:
                    if settings.tmdb_key:
                        try:
                            url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={settings.tmdb_key}"
                            data = requests.get(url, timeout=4).json()
                            for s in data.get('seasons', []):
                                if s.get('season_number', 0) > 0:
                                    seasons.append(s.get('season_number'))
                        except: pass

                if not seasons:
                    return False, "No seasons available to request."
                payload['seasons'] = seasons

            r = requests.post(f"{base_url}/api/v1/request", json=payload, headers=headers, timeout=10)
            if r.status_code in [200, 201]:
                return True, "Success"
            elif r.status_code == 409:
                return True, "Already requested in Overseerr"
                
            try:
                error_data = r.json()
                error_msg = error_data.get('message', error_data.get('error', r.text))
            except:
                error_msg = f"HTTP Error {r.status_code}"

            error_lower = str(error_msg).lower()
            if "already available" in error_lower: return True, "Already available in your library."
            if "already requested" in error_lower: return True, "Already requested."
            
            return False, f"Overseerr: {error_msg}"
            
        except Exception:
            write_log("error", "Overseerr", "Connection error")
            return False, "Connection error. Please check your Overseerr URL and API key."

    @staticmethod
    def _arr_root_and_quality(base_url, headers):
        """Fetch first root folder path and first quality profile id from *arr."""
        try:
            rf_resp = requests.get(f"{base_url}/api/v3/rootfolder", headers=headers, timeout=5)
            rf_data = rf_resp.json()
            rf_list = rf_data if isinstance(rf_data, list) else (rf_data.get('records', rf_data.get('data', [])) if isinstance(rf_data, dict) else [])
            if not rf_list or not isinstance(rf_list[0], dict):
                return None, None, "No root folders configured."
            root_path = rf_list[0].get('path')
            if not root_path:
                return None, None, "Could not get root folder path."
            qp_resp = requests.get(f"{base_url}/api/v3/qualityprofile", headers=headers, timeout=5)
            qp_data = qp_resp.json()
            qp_list = qp_data if isinstance(qp_data, list) else (qp_data.get('records', qp_data.get('data', [])) if isinstance(qp_data, dict) else [])
            if not qp_list or not isinstance(qp_list[0], dict):
                return None, None, "No quality profiles configured."
            quality_id = qp_list[0].get('id')
            if quality_id is None:
                return None, None, "Could not get quality profile id."
            return root_path, quality_id, None
        except Exception:
            return None, None, "Request failed"

    @staticmethod
    def _arr_language_profile(base_url, headers):
        """Fetch first language profile id from Sonarr."""
        try:
            lp_resp = requests.get(f"{base_url}/api/v3/languageprofile", headers=headers, timeout=5)
            lp_data = lp_resp.json()
            lp_list = lp_data if isinstance(lp_data, list) else (lp_data.get('records', lp_data.get('data', [])) if isinstance(lp_data, dict) else [])
            if not lp_list or not isinstance(lp_list[0], dict):
                return None, "No language profiles configured."
            lang_id = lp_list[0].get('id')
            if lang_id is None:
                return None, "Could not get language profile id."
            return lang_id, None
        except Exception:
            return None, "Request failed"

    @staticmethod
    def _get_clean_base_url(url):
        """Strip trailing slashes and /api or /api/v3 suffixes."""
        if not url: return ""
        u = url.rstrip('/')
        if u.endswith('/api/v3'): u = u.rsplit('/api/v3', 1)[0]
        if u.endswith('/api'): u = u.rsplit('/api', 1)[0]
        return u

    @staticmethod
    def send_to_radarr_sonarr(settings, media_type, tmdb_id):
        """Sends a request directly to Radarr or Sonarr."""
        if not settings: return False, "Settings not configured."

        try:
            if media_type == 'movie':
                if not settings.radarr_url or not settings.radarr_api_key:
                    return False, "Radarr not configured."

                base_url = IntegrationsService._get_clean_base_url(settings.radarr_url)
                headers = {"X-Api-Key": settings.radarr_api_key, "Content-Type": "application/json"}

                root_path, quality_profile_id, err = IntegrationsService._arr_root_and_quality(base_url, headers)
                if err: return False, f"Radarr: {err}"

                # Lookup movie in Radarr first to get full metadata
                lookup_url = f"{base_url}/api/v3/movie/lookup?term=tmdb:{tmdb_id}"
                lookup = requests.get(lookup_url, headers=headers, timeout=10)
                
                if lookup.status_code == 200:
                    results = lookup.json()
                    if results and len(results) > 0:
                        movie_data = results[0]
                        if movie_data.get('id'):
                            return True, "Already in Radarr"
                        
                        payload = {
                            "tmdbId": int(tmdb_id),
                            "title": movie_data.get('title'),
                            "qualityProfileId": quality_profile_id,
                            "rootFolderPath": root_path,
                            "monitored": True,
                            "year": movie_data.get('year'),
                            "titleSlug": movie_data.get('titleSlug'),
                            "images": movie_data.get('images', []),
                            "addOptions": {"searchForMovie": True}
                        }
                        
                        resp = requests.post(f"{base_url}/api/v3/movie", json=payload, headers=headers, timeout=15)
                        if resp.status_code in [200, 201]:
                            return True, "Added to Radarr"
                        else:
                            try:
                                err_data = resp.json()
                                msg = err_data[0].get('errorMessage') if isinstance(err_data, list) else err_data.get('message')
                            except: msg = resp.text[:100]
                            return False, f"Radarr Error: {msg or resp.status_code}"
                
                return False, "Could not find movie metadata in Radarr lookup."

            elif media_type == 'tv':
                if not settings.sonarr_url or not settings.sonarr_api_key:
                    return False, "Sonarr not configured."

                base_url = IntegrationsService._get_clean_base_url(settings.sonarr_url)
                headers = {"X-Api-Key": settings.sonarr_api_key, "Content-Type": "application/json"}

                root_path, quality_profile_id, err = IntegrationsService._arr_root_and_quality(base_url, headers)
                if err: return False, f"Sonarr: {err}"
                
                language_profile_id, lang_err = IntegrationsService._arr_language_profile(base_url, headers)
                if lang_err: return False, f"Sonarr: {lang_err}"

                lookup_url = f"{base_url}/api/v3/series/lookup?term=tmdb:{tmdb_id}"
                lookup = requests.get(lookup_url, headers=headers, timeout=10)
                
                if lookup.status_code == 200:
                    results = lookup.json()
                    if results and len(results) > 0:
                        series_data = results[0]
                        if series_data.get('id'):
                            return True, "Already in Sonarr"
                            
                        payload = {
                            "tvdbId": series_data.get('tvdbId'),
                            "tmdbId": int(tmdb_id),
                            "title": series_data.get('title'),
                            "qualityProfileId": quality_profile_id,
                            "languageProfileId": language_profile_id,
                            "rootFolderPath": root_path,
                            "monitored": True,
                            "titleSlug": series_data.get('titleSlug'),
                            "images": series_data.get('images', []),
                            "addOptions": {"searchForMissingEpisodes": True}
                        }
                        
                        resp = requests.post(f"{base_url}/api/v3/series", json=payload, headers=headers, timeout=15)
                        if resp.status_code in [200, 201]:
                            return True, "Added to Sonarr"
                        else:
                            try:
                                err_data = resp.json()
                                msg = err_data[0].get('errorMessage') if isinstance(err_data, list) else err_data.get('message')
                            except: msg = resp.text[:100]
                            return False, f"Sonarr Error: {msg or resp.status_code}"

                return False, "Could not find show in Sonarr lookup."
                    
        except Exception:
            return False, "Integrations Error: Request failed"
        
        return False, "Unknown Media Type"

    @staticmethod
    def refresh_radarr_sonarr_cache(app_obj):
        """Scan Radarr and Sonarr libraries and store items in database."""
        if is_system_locked():
            return False, "Another task is running. Please wait and try again."

        print("--- STARTING RADARR/SONARR CACHE REFRESH ---")
        
        with app_obj.app_context():
            from datetime import datetime
            settings = Settings.query.first()
            if not settings:
                return False, "Settings not found."
            
            has_radarr = settings.radarr_url and settings.radarr_api_key
            has_sonarr = settings.sonarr_url and settings.sonarr_api_key
            
            if not has_radarr and not has_sonarr:
                return False, "Radarr or Sonarr not configured."

            write_log("info", "Radarr/Sonarr", "Started background scan.", app_obj=app_obj)
            set_system_lock("Refreshing Radarr/Sonarr Cache...") 
            start_time = time.time()
            
            try:
                total_items = 0
                
                # Scan Radarr
                if has_radarr:
                    try:
                        headers = {'X-Api-Key': settings.radarr_api_key}
                        base_url = IntegrationsService._get_clean_base_url(settings.radarr_url)
                        
                        resp = requests.get(f"{base_url}/api/v3/movie", headers=headers, timeout=30)
                        if resp.status_code == 200:
                            movies = resp.json()
                            radarr_count = 0
                            for movie in movies:
                                tmdb_id = movie.get('tmdbId')
                                if not tmdb_id: continue
                                
                                title = movie.get('title', '')
                                year = movie.get('year')
                                norm_title = normalize_title(title) if title else ''
                                has_file = bool(movie.get('hasFile', False))
                                
                                existing = RadarrSonarrCache.query.filter_by(
                                    tmdb_id=tmdb_id, media_type='movie', source='radarr'
                                ).first()
                                if existing:
                                    existing.title = norm_title
                                    existing.original_title = title
                                    existing.year = year
                                    existing.has_file = has_file
                                    existing.timestamp = datetime.now()
                                else:
                                    entry = RadarrSonarrCache(
                                        tmdb_id=tmdb_id, media_type='movie', source='radarr',
                                        title=norm_title, original_title=title, year=year, has_file=has_file
                                    )
                                    db.session.add(entry)
                                radarr_count += 1
                            db.session.commit()
                            total_items += radarr_count
                            write_log("info", "Radarr/Sonarr", f"Scanned {radarr_count} movies from Radarr.", app_obj=app_obj)
                    except Exception:
                        log.error("Radarr scan error")

                # Scan Sonarr
                if has_sonarr:
                    try:
                        headers = {'X-Api-Key': settings.sonarr_api_key}
                        base_url = IntegrationsService._get_clean_base_url(settings.sonarr_url)
                        
                        resp = requests.get(f"{base_url}/api/v3/series", headers=headers, timeout=30)
                        if resp.status_code == 200:
                            shows = resp.json()
                            sonarr_count = 0
                            for show in shows:
                                tmdb_id = show.get('tmdbId')
                                if not tmdb_id:
                                    tvdb_id = show.get('tvdbId')
                                    if tvdb_id and settings.tmdb_key:
                                        try:
                                            find_url = f"https://api.themoviedb.org/3/find/{tvdb_id}?api_key={settings.tmdb_key}&external_source=tvdb_id"
                                            find_resp = requests.get(find_url, timeout=5)
                                            if find_resp.ok:
                                                tv_results = find_resp.json().get('tv_results', [])
                                                if tv_results: tmdb_id = tv_results[0].get('id')
                                        except: pass
                                
                                if not tmdb_id: continue
                                
                                title = show.get('title', '')
                                year = show.get('year')
                                norm_title = normalize_title(title) if title else ''
                                stats = show.get('statistics') or {}
                                has_file = int(stats.get('episodeFileCount') or 0) > 0
                                
                                existing = RadarrSonarrCache.query.filter_by(
                                    tmdb_id=tmdb_id, media_type='tv', source='sonarr'
                                ).first()
                                if existing:
                                    existing.title = norm_title
                                    existing.original_title = title
                                    existing.year = year
                                    existing.has_file = has_file
                                    existing.timestamp = datetime.now()
                                else:
                                    entry = RadarrSonarrCache(
                                        tmdb_id=tmdb_id, media_type='tv', source='sonarr',
                                        title=norm_title, original_title=title, year=year, has_file=has_file
                                    )
                                    db.session.add(entry)
                                sonarr_count += 1
                            db.session.commit()
                            total_items += sonarr_count
                            write_log("info", "Radarr/Sonarr", f"Scanned {sonarr_count} TV shows from Sonarr.", app_obj=app_obj)
                    except Exception:
                        log.error("Sonarr scan error")

                settings.last_radarr_sonarr_scan = int(time.time())
                db.session.commit()
                
                duration = round(time.time() - start_time, 2)
                msg = f"Radarr/Sonarr scan completed in {duration}s. Indexed {total_items} items."
                write_log("success", "Radarr/Sonarr", msg, app_obj=app_obj)
                return True, msg
                
            except Exception:
                log.error("Arr Cache Refresh Failed")
                return False, "Scan failed"
            finally:
                from utils import remove_system_lock
                remove_system_lock()
