"""
CollectionService - Handles all playlist and collection synchronization logic.
Decoupled from main app logic to ensure stability and independent updates.
"""

import json
import logging
import os
import time
import concurrent.futures
import requests
from datetime import datetime, timedelta
from plexapi.server import PlexServer

from models import db, CollectionSchedule, TmdbAlias
from presets import TMDB_GENRE_MAP, TMDB_STUDIO_MAP, PLAYLIST_PRESETS
from utils import (
    write_log, 
    is_system_locked, 
    set_system_lock, 
    remove_system_lock, 
    normalize_title
)

log = logging.getLogger(__name__)

class CollectionService:
    @staticmethod
    def run_collection_logic(settings, preset, key, app_obj=None):
        """
        Main entry point for syncing a collection preset to Plex.
        """
        if is_system_locked(): 
            return False, "Another task is running. Please wait and try again."
        
        set_system_lock(f"Syncing {preset.get('title', 'Collection')}...")
        write_log("info", "Sync", f"Starting Sync: {key}", app_obj=app_obj)

        try:
            plex = PlexServer(settings.plex_url, settings.plex_token)
            want_type = preset.get('media_type', 'movie')
            tmdb_items = []

            # figure out if this is a trending collection (needs strict sync)
            category = preset.get('category', '')
            is_trending = 'Trending' in category or 'Trending' in preset.get('title', '')
            max_pages = 1 if is_trending else 50
            user_mode = preset.get('sync_mode', 'append')
            mode = 'sync' if is_trending else user_mode

            # source: curated TMDB list
            list_id = preset.get('tmdb_list_id')
            if list_id:
                try:
                    list_url = f"https://api.themoviedb.org/3/list/{list_id}?api_key={settings.tmdb_key}&language=en-US"
                    list_data = requests.get(list_url, timeout=15).json()
                    raw_items = list_data.get('items', [])
                    for it in raw_items:
                        mt = it.get('media_type') or want_type
                        if mt != want_type:
                            continue
                        tmdb_items.append({
                            'id': it.get('id'),
                            'title': it.get('title') if mt == 'movie' else None,
                            'name': it.get('name') if mt == 'tv' else None,
                            'release_date': it.get('release_date'),
                            'first_air_date': it.get('first_air_date'),
                            'poster_path': it.get('poster_path'),
                            'vote_average': it.get('vote_average'),
                            'genre_ids': it.get('genre_ids')
                        })
                except Exception as e:
                    write_log("error", "Sync", f"TMDB list fetch failed: {e}", app_obj=app_obj)
                    return False, "Could not load list from TMDB. Check list ID or try again later."
            else:
                params = (preset.get('tmdb_params') or {}).copy()
                params['api_key'] = settings.tmdb_key
                if 'language' not in params:
                    params['language'] = 'en-US'

                days_old = preset.get('days_old')
                if days_old and isinstance(days_old, int):
                    cutoff = (datetime.now() - timedelta(days=days_old)).strftime('%Y-%m-%d')
                    if want_type == 'movie':
                        params['primary_release_date.gte'] = cutoff
                        params['primary_release_date.lte'] = datetime.now().strftime('%Y-%m-%d')
                    else:
                        params['first_air_date.gte'] = cutoff
                        params['first_air_date.lte'] = datetime.now().strftime('%Y-%m-%d')

                if 'with_collection_id' in params:
                    col_id = params.pop('with_collection_id')
                    url = f"https://api.themoviedb.org/3/collection/{col_id}?api_key={settings.tmdb_key}&language=en-US"
                    data = requests.get(url, timeout=10).json()
                    tmdb_items = data.get('parts', [])
                else:
                    endpoint = preset.get('tmdb_endpoint')
                    url = f"https://api.themoviedb.org/3/{endpoint}" if endpoint else f"https://api.themoviedb.org/3/discover/{want_type}"

                    def fetch_page(p):
                        try:
                            p_params = params.copy()
                            p_params['page'] = p
                            resp = requests.get(url, params=p_params, timeout=10)
                            data = resp.json() if resp.ok else {}
                            return data.get('results') or [] if isinstance(data, dict) else []
                        except: return []

                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        results = executor.map(fetch_page, range(1, max_pages + 1))
                        for page_items in results:
                            if page_items: tmdb_items.extend(page_items)
                            
            if want_type == 'tv':
                tmdb_items = [i for i in tmdb_items if i.get('name')]
            else:
                tmdb_items = [i for i in tmdb_items if i.get('title')]
            
            limit = preset.get('limit')
            if limit and isinstance(limit, int) and limit > 0:
                if is_trending:
                    tmdb_items = tmdb_items[:limit]
            
            if key == 'genre_horror_tv' and want_type == 'tv':
                exclude_genres = {16, 10762, 10751}
                tmdb_items = [i for i in tmdb_items if not (exclude_genres & set(i.get('genre_ids', [])))]

            if not tmdb_items:
                write_log("warning", "Sync", f"TMDB returned no items for preset '{preset.get('title', key)}'. Collection unchanged.", app_obj=app_obj)
                return True, "TMDB returned no items for this preset. Collection unchanged."

            id_map = {}
            try:
                rows = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0, TmdbAlias.media_type == want_type).with_entities(TmdbAlias.tmdb_id, TmdbAlias.plex_title).all()
                for r in rows: id_map[r.tmdb_id] = r.plex_title
            except Exception as e: log.warning("Load alias map for preset: %s", e)

            potential_matches = []
            for item in tmdb_items:
                if item['id'] in id_map:
                    item['mapped_plex_title'] = id_map[item['id']]
                    potential_matches.append(item)

            target_type = 'movie' if want_type == 'movie' else 'show'
            target_lib = next((s for s in plex.library.sections() if s.type == target_type), None)
            if not target_lib:
                return False, f"No {want_type.capitalize()} library found in Plex."
            
            should_scan_local = category in ['Genre (Movies)', 'Genre (TV)', 'Decades', 'Studios & Networks', 'Content Ratings']
            if 'theme_' in key and ('genre' in preset.get('tmdb_params', {}).keys() or 'with_genres' in preset.get('tmdb_params', {})):
                 should_scan_local = True

            local_candidates = []
            if should_scan_local:
                try:
                    local_candidates = CollectionService._fetch_local_candidates(target_lib, preset)
                    if local_candidates:
                        write_log("info", "Sync", f"Local scan found {len(local_candidates)} items for '{preset.get('title')}'", app_obj=app_obj)
                except Exception as e: log.warning("Local scan failed: %s", e)

            found_items = []
            if potential_matches:
                for item in potential_matches:
                    search_title = item.get('mapped_plex_title', item.get('title', item.get('name')))
                    if not search_title: continue
                    year = int((item.get('release_date') or item.get('first_air_date') or '0000')[:4])
                    tmdb_id = item.get('id')
                    try:
                        results = target_lib.search(search_title)
                        matched = None
                        for r in results:
                            plex_tmdb = CollectionService._get_plex_tmdb_id(r)
                            if plex_tmdb == tmdb_id:
                                matched = r
                                break
                        if matched is None:
                            for r in results:
                                r_year = r.year if r.year else 0
                                if r_year in (year, year - 1, year + 1) and normalize_title(r.title) == normalize_title(search_title):
                                    matched = r
                                    break
                        if matched and matched not in found_items:
                            matched._tmdb_rating = item.get('vote_average')
                            found_items.append(matched)
                    except Exception as e: log.debug("Plex search match: %s", e)
            
            if local_candidates:
                existing_keys = {x.ratingKey for x in found_items}
                for item in local_candidates:
                    if item.ratingKey not in existing_keys:
                        found_items.append(item)
                        existing_keys.add(item.ratingKey)

            if limit and isinstance(limit, int) and limit > 0:
                found_items = found_items[:limit]

            want_title = (preset['title'] or '').strip()
            want_lower = want_title.lower()
            existing_col = None
            try:
                results = target_lib.search(title=preset['title'], libtype='collection')
                for col in results:
                    if (getattr(col, 'title', None) or '').strip().lower() == want_lower:
                        existing_col = col
                        break
            except: pass

            if existing_col and getattr(existing_col, 'smart', False):
                alt_title = want_title + " (SeekAndWatch)"
                if found_items:
                    col = target_lib.createCollection(title=alt_title, items=found_items)
                    CollectionService.apply_collection_visibility(col, 
                        visible_home=preset.get('visibility_home', True),
                        visible_library=preset.get('visibility_library', True))
                    return True, f"Regular collection '{alt_title}' created because a smart one already exists."
                return True, "Smart collection exists; no items to add."

            if not existing_col:
                if found_items:
                    col = target_lib.createCollection(title=preset['title'], items=found_items)
                    col.sortUpdate(sort='custom')
                    try:
                        col.edit(**{"title.locked": 1, "summary.locked": 1, "titleSort.locked": 1})
                    except: pass
                    
                    # Handle custom poster
                    try:
                        schedule = CollectionSchedule.query.filter_by(preset_key=key).first()
                        if schedule:
                            config_data = json.loads(schedule.configuration or '{}')
                            poster_path = config_data.get('custom_poster')
                            if poster_path and os.path.exists(poster_path):
                                col.edit(**{'thumb.locked': 0})
                                col.uploadPoster(filepath=poster_path)
                                col.edit(**{'thumb.locked': 1})
                    except Exception as e: log.warning(f"Custom poster failed: {e}")

                    CollectionService.apply_collection_visibility(col, 
                        visible_home=preset.get('visibility_home', True),
                        visible_library=preset.get('visibility_library', True))
                    return True, f"Created '{preset['title']}' with {len(found_items)} items."
                return True, "No items found to create collection."

            # Update existing regular collection
            current_items = existing_col.items()
            current_keys = {item.ratingKey for item in current_items}
            found_keys = {item.ratingKey for item in found_items}
            
            to_add = [item for item in found_items if item.ratingKey not in current_keys]
            to_remove = []
            if mode == 'sync':
                to_remove = [item for item in current_items if item.ratingKey not in found_keys]

            if to_add: existing_col.addItems(to_add)
            if to_remove: existing_col.removeItems(to_remove)
            existing_col.moveItems(found_items)
                
            try:
                existing_col.edit(**{"title.locked": 1, "summary.locked": 1, "titleSort.locked": 1})
            except: pass

            CollectionService.apply_collection_visibility(existing_col, 
                visible_home=preset.get('visibility_home', True),
                visible_library=preset.get('visibility_library', True))
            
            action = "Synced" if mode == 'sync' else "Appended"
            msg = f"{action} '{preset['title']}': Added {len(to_add)}, Removed {len(to_remove)}."
            write_log("success", "Sync", msg, app_obj=app_obj)
            return True, msg

        except Exception:
            write_log("error", "Sync", "Collection sync failed. Please check the logs.", app_obj=app_obj)
            return False, "Collection sync failed"
        finally:
            remove_system_lock()

    @staticmethod
    def _fetch_local_candidates(target_lib, preset):
        local_items = []
        tmdb_params = preset.get('tmdb_params', {})
        
        g_ids = tmdb_params.get('with_genres', '')
        if g_ids:
            parts = g_ids.replace(',', '|').split('|')
            for pid in parts:
                g_name = TMDB_GENRE_MAP.get(str(pid))
                if g_name:
                    try:
                        hits = target_lib.search(genre=g_name)
                        local_items.extend(hits)
                    except: pass

        d_gte = tmdb_params.get('primary_release_date.gte') or tmdb_params.get('first_air_date.gte')
        if d_gte and (d_gte.endswith('-01-01') or d_gte == '2020-01-01'):
            try:
                year = int(d_gte[:4])
                if year % 10 == 0:
                    hits = target_lib.search(decade=year)
                    local_items.extend(hits)
            except: pass

        cert = tmdb_params.get('certification')
        if cert:
            try:
                hits = target_lib.search(contentRating=cert)
                local_items.extend(hits)
            except: pass

        company_ids = tmdb_params.get('with_companies') or tmdb_params.get('with_networks')
        if company_ids:
            parts = str(company_ids).replace(',', '|').split('|')
            for cid in parts:
                s_name = TMDB_STUDIO_MAP.get(str(cid))
                if s_name:
                    try:
                        hits = target_lib.search(studio=s_name)
                        local_items.extend(hits)
                        if preset.get('media_type') == 'tv':
                            local_items.extend(target_lib.search(network=s_name))
                    except: pass
        return local_items

    @staticmethod
    def get_collection_visibility(server, section_id, rating_key):
        """Read Home / Library / Friends visibility from Plex."""
        def _bool_attr(v):
            if v is None: return False
            if isinstance(v, bool): return v
            return str(v).strip().lower() in ('1', 'true', 'yes')

        def _from_elem(elem):
            if elem is None or not hasattr(elem, 'attrib'): return None
            a = elem.attrib
            if 'promotedToOwnHome' not in a and 'promotedToRecommended' not in a and 'promotedToLibrary' not in a:
                return None
            home = _bool_attr(a.get('promotedToOwnHome'))
            lib = _bool_attr(a.get('promotedToRecommended')) or _bool_attr(a.get('promotedToLibrary'))
            friends = _bool_attr(a.get('promotedToSharedHome'))
            return (home, lib, friends)

        try:
            hub_id = 'custom.collection.%s.%s' % (section_id, rating_key)
            path = '/hubs/sections/%s/manage/%s' % (section_id, hub_id)
            data = server.query(path)
            if data is None: return (None, None, None)
            
            def walk(e):
                if e is None: return None
                r = _from_elem(e)
                if r is not None: return r
                try:
                    for child in list(e) if hasattr(e, '__iter__') and not isinstance(e, (str, bytes)) else []:
                        r = walk(child)
                        if r is not None: return r
                except: pass
                return None
            
            result = walk(data)
            if result is not None: return result
            
            if hasattr(data, 'find') and callable(data.find):
                for tag in ('Directory', 'directory', 'Hub', 'hub'):
                    elem = data.find(tag) or data.find('.//' + tag)
                    if elem is not None:
                        result = _from_elem(elem)
                        if result is not None: return result
            if hasattr(data, 'attrib'):
                result = _from_elem(data)
                if result is not None: return result
        except Exception as e:
            log.debug("get_collection_visibility error: %s", e)
        
        try:
            path2 = '/hubs/sections/%s/manage?metadataItemId=%s' % (section_id, rating_key)
            data = server.query(path2)
            if data is not None:
                result = walk(data)
                if result is None and hasattr(data, 'find') and callable(data.find):
                    for tag in ('Directory', 'directory', 'Hub', 'hub'):
                        elem = data.find(tag) or data.find('.//' + tag)
                        if elem is not None:
                            result = _from_elem(elem)
                            if result is not None: return result
                return result or (None, None, None)
        except Exception as e:
            log.debug("get_collection_visibility fallback error: %s", e)
            
        return (None, None, None)

    @staticmethod
    def apply_collection_visibility(plex_collection, visible_home=False, visible_library=False, visible_friends=False):
        try:
            # plexapi methods for visibility
            if visible_home: plex_collection.promoteToRecommended()
            else: plex_collection.demoteFromRecommended()
            
            if visible_library: plex_collection.promoteToOwnRecommended()
            else: plex_collection.demoteFromOwnRecommended()
            
            if visible_friends: plex_collection.promoteToSharedRecommended()
            else: plex_collection.demoteFromSharedRecommended()
        except: pass

    @staticmethod
    def _get_plex_tmdb_id(plex_item):
        """Extracts TMDB ID from Plex item GUID."""
        try:
            guid = getattr(plex_item, 'guid', '')
            if 'tmdb://' in guid:
                return int(guid.split('tmdb://')[1].split('?')[0])
            for remote in getattr(plex_item, 'guids', []):
                if 'tmdb://' in remote.id:
                    return int(remote.id.split('tmdb://')[1].split('?')[0])
        except: pass
        return None
