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
from utils.helpers import write_log, normalize_title
from utils.system import is_system_locked, set_system_lock, remove_system_lock

log = logging.getLogger(__name__)

class CollectionService:
    @staticmethod
    def run_collection_logic(settings, preset, key, app_obj=None):
        """
        Main entry point for syncing a collection preset to Plex.
        Supports syncing to multiple libraries based on configuration.
        """
        if is_system_locked(): 
            return False, "Another task is running. Please wait and try again."

        set_system_lock(f"Syncing {preset.get('title', 'Collection')}...")
        write_log("info", "Sync", f"Starting Sync: {key}", app_obj=app_obj)

        try:
            # Load configuration for multi-library support
            schedule = CollectionSchedule.query.filter_by(preset_key=key).first()
            config_data = json.loads(schedule.configuration or '{}') if schedule else {}
            library_mode = config_data.get('target_library_mode', 'all')
            target_library_names = config_data.get('target_libraries', [])

            plex = PlexServer(settings.plex_url, settings.plex_token)
            want_type = preset.get('media_type', 'movie')
            target_type = 'movie' if want_type == 'movie' else 'show'

            # Get all libraries of matching type
            all_libs = [s for s in plex.library.sections() if s.type == target_type]

            if not all_libs:
                return False, f"No {want_type.capitalize()} library found in Plex."

            # Filter libraries based on mode
            if library_mode == 'first':
                target_libs = [all_libs[0]]
            elif library_mode == 'selected' and target_library_names:
                target_libs = [lib for lib in all_libs if lib.title in target_library_names]
                if not target_libs:
                    return False, f"None of the selected libraries found: {', '.join(target_library_names)}"
            else:  # 'all' or default
                target_libs = all_libs

            write_log("info", "Sync", f"Syncing to {len(target_libs)} library(ies): {', '.join([lib.title for lib in target_libs])}", app_obj=app_obj)

            # Fetch TMDB items once (shared across all libraries)
            tmdb_items = CollectionService._fetch_tmdb_items(settings, preset, key, app_obj)
            if tmdb_items is None:
                if not settings or not settings.tmdb_key:
                    return False, "TMDB API key not configured. Add your TMDB key in Settings to use collections."
                return False, "Failed to fetch items from TMDB"

            if not tmdb_items:
                write_log("warning", "Sync", f"TMDB returned no items for preset '{preset.get('title', key)}'. Collection unchanged.", app_obj=app_obj)
                return True, "TMDB returned no items for this preset. Collection unchanged."

            # Sync to each target library
            results = {}
            overall_success = True

            for target_lib in target_libs:
                lib_name = target_lib.title
                try:
                    success, message, stats = CollectionService._sync_to_library(
                        target_lib, tmdb_items, preset, key, settings, config_data, app_obj
                    )
                    results[lib_name] = {
                        'success': success,
                        'message': message,
                        'stats': stats
                    }
                    if not success:
                        overall_success = False
                except Exception as e:
                    log.exception(f"Failed to sync to library '{lib_name}': {e}")
                    results[lib_name] = {
                        'success': False,
                        'message': f"Error: {str(e)}",
                        'stats': {}
                    }
                    overall_success = False

            # Build summary message
            success_libs = [name for name, r in results.items() if r['success']]
            failed_libs = [name for name, r in results.items() if not r['success']]

            # Clear poster update flag if any library had poster updated
            poster_updated_any = any(r['stats'].get('poster_updated', False) for r in results.values())
            if poster_updated_any and schedule:
                try:
                    config_data['force_poster_update'] = False
                    schedule.configuration = json.dumps(config_data)
                    db.session.commit()
                    log.info(f"Cleared poster update flag for '{preset['title']}'")
                except Exception as e:
                    log.error(f"Failed to clear poster update flag: {e}")
                    db.session.rollback()

            if overall_success:
                total_items = sum(r['stats'].get('total', 0) for r in results.values())
                summary = f"Synced '{preset['title']}' to {len(success_libs)} library(ies) ({total_items} total items)"
                write_log("success", "Sync", summary, app_obj=app_obj)
                return True, summary
            elif success_libs:
                summary = f"Partial success: {len(success_libs)} succeeded, {len(failed_libs)} failed"
                write_log("warning", "Sync", summary, app_obj=app_obj)
                return True, summary
            else:
                summary = f"Failed to sync to all {len(failed_libs)} library(ies)"
                write_log("error", "Sync", summary, app_obj=app_obj)
                return False, summary

        except Exception as e:
            log.exception(f"Collection sync failed for '{preset.get('title', key)}': {e}")
            write_log("error", "Sync", f"Collection sync failed: {str(e)}", app_obj=app_obj)
            return False, f"Collection sync failed: {str(e)}"
        finally:
            remove_system_lock()

    @staticmethod
    def _fetch_tmdb_items(settings, preset, key, app_obj=None):
        """
        Fetch items from TMDB based on preset configuration.
        Returns list of TMDB items or None on error.
        """
        if not settings or not settings.tmdb_key:
            write_log("error", "Sync", "TMDB API key not configured", app_obj=app_obj)
            return None
            
        want_type = preset.get('media_type', 'movie')
        tmdb_items = []
        
        # figure out if this is a trending collection (needs strict sync)
        category = preset.get('category', '')
        is_trending = 'Trending' in category or 'Trending' in preset.get('title', '')
        max_pages = 1 if is_trending else 50

        # source: curated TMDB list
        list_id = preset.get('tmdb_list_id')
        if list_id:
            try:
                list_url = f"https://api.themoviedb.org/3/list/{list_id}?api_key={settings.tmdb_key}&language=en-US"
                resp = requests.get(list_url, timeout=15)
                if not resp.ok:
                    write_log("error", "Sync", f"TMDB list API returned {resp.status_code}: {resp.text[:200]}", app_obj=app_obj)
                    return None
                list_data = resp.json()
                raw_items = list_data.get('items', [])
                write_log("info", "Sync", f"TMDB list {list_id} returned {len(raw_items)} items", app_obj=app_obj)
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
                write_log("error", "Sync", f"TMDB list fetch failed: {str(e)}", app_obj=app_obj)
                return None
        else:
            params = (preset.get('tmdb_params') or {}).copy()
            params['api_key'] = settings.tmdb_key
            if 'language' not in params:
                params['language'] = 'en-US'

            days_old = preset.get('days_old')
            if days_old and isinstance(days_old, int):
                cutoff = (datetime.datetime.now() - timedelta(days=days_old)).strftime('%Y-%m-%d')
                if want_type == 'movie':
                    params['primary_release_date.gte'] = cutoff
                    params['primary_release_date.lte'] = datetime.datetime.now().strftime('%Y-%m-%d')
                else:
                    params['first_air_date.gte'] = cutoff
                    params['first_air_date.lte'] = datetime.datetime.now().strftime('%Y-%m-%d')

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
                        if not resp.ok:
                            write_log("warning", "Sync", f"TMDB API page {p} returned {resp.status_code}", app_obj=app_obj)
                            return []
                        data = resp.json() if resp.ok else {}
                        return data.get('results') or [] if isinstance(data, dict) else []
                    except Exception as e:
                        write_log("warning", "Sync", f"TMDB API page {p} failed: {str(e)}", app_obj=app_obj)
                        return []

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

        return tmdb_items

    @staticmethod
    def _sync_to_library(target_lib, tmdb_items, preset, key, settings, config_data, app_obj=None):
        """
        Sync collection to a single library.
        Returns (success, message, stats) tuple.
        """
        want_type = preset.get('media_type', 'movie')
        category = preset.get('category', '')
        is_trending = 'Trending' in category or 'Trending' in preset.get('title', '')
        user_mode = preset.get('sync_mode', 'append')
        mode = 'sync' if is_trending else user_mode
        limit = preset.get('limit')
        
        # Build ID map for matching
        id_map = {}
        try:
            rows = TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0, TmdbAlias.media_type == want_type).with_entities(TmdbAlias.tmdb_id, TmdbAlias.plex_title).all()
            for r in rows: id_map[r.tmdb_id] = r.plex_title
        except Exception:
            log.warning("Load alias map for preset failed")

        potential_matches = []
        for item in tmdb_items:
            if item['id'] in id_map:
                item['mapped_plex_title'] = id_map[item['id']]
                potential_matches.append(item)

        # Check if we should scan local library
        should_scan_local = category in ['Genre (Movies)', 'Genre (TV)', 'Decades', 'Studios & Networks', 'Content Ratings']
        if 'theme_' in key and ('genre' in preset.get('tmdb_params', {}).keys() or 'with_genres' in preset.get('tmdb_params', {})):
             should_scan_local = True

        local_candidates = []
        if should_scan_local:
            try:
                local_candidates = CollectionService._fetch_local_candidates(target_lib, preset)
                if local_candidates:
                    write_log("info", "Sync", f"Local scan found {len(local_candidates)} items for '{preset.get('title')}' in '{target_lib.title}'", app_obj=app_obj)
            except Exception:
                log.warning("Local scan failed")

        # Match items in this library
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
                except Exception:
                    log.debug("Plex search match failed")
        
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
                return True, f"Regular collection '{alt_title}' created because a smart one already exists.", {'total': len(found_items), 'added': len(found_items), 'removed': 0}
            return True, "Smart collection exists; no items to add.", {'total': 0, 'added': 0, 'removed': 0}

        if not existing_col:
            if found_items:
                col = target_lib.createCollection(title=preset['title'], items=found_items)
                col.sortUpdate(sort='custom')
                try:
                    col.editTitle(preset['title']).editSortTitle(preset['title']).reload()
                    # lock fields (method removed in newer PlexAPI versions, skip if not available)
                    if hasattr(col, 'lockTitle'):
                        col.lockTitle().lockSortTitle().lockSummary()
                except Exception as e:
                    log.debug(f"Failed to lock collection fields: {e}")
                
                # Handle custom poster
                poster_path = config_data.get('custom_poster')
                poster_updated = False
                if poster_path and os.path.exists(poster_path):
                    try:
                        col.unlockPoster()
                        col.uploadPoster(filepath=poster_path)
                        col.lockPoster()
                        log.info(f"Applied custom poster to new collection '{preset['title']}' in '{target_lib.title}'")
                        poster_updated = True
                    except Exception as e:
                        log.warning(f"Custom poster upload failed: {e}")

                CollectionService.apply_collection_visibility(col, 
                    visible_home=preset.get('visibility_home', True),
                    visible_library=preset.get('visibility_library', True))
                return True, f"Created '{preset['title']}' with {len(found_items)} items.", {'total': len(found_items), 'added': len(found_items), 'removed': 0, 'poster_updated': poster_updated}
            return True, "No items found to create collection.", {'total': 0, 'added': 0, 'removed': 0, 'poster_updated': False}

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
        
        # Try to reorder items
        try:
            if hasattr(existing_col, 'moveItems'):
                existing_col.moveItems(found_items)
        except Exception as e:
            log.debug(f"Failed to reorder collection items: {e}")
            
        try:
            # lock fields (method removed in newer PlexAPI versions, skip if not available)
            if hasattr(existing_col, 'lockTitle'):
                existing_col.lockTitle().lockSortTitle().lockSummary()
        except Exception as e:
            log.debug(f"Failed to lock collection fields: {e}")

        # Handle custom poster for existing collection
        poster_path = config_data.get('custom_poster')
        force_update = config_data.get('force_poster_update', False)
        poster_updated = False
        
        if poster_path and os.path.exists(poster_path) and force_update:
            try:
                existing_col.unlockPoster()
                existing_col.uploadPoster(filepath=poster_path)
                existing_col.lockPoster()
                log.info(f"Applied custom poster to '{preset['title']}' in '{target_lib.title}'")
                poster_updated = True
            except Exception as e:
                log.error(f"Custom poster update failed: {e}")

        CollectionService.apply_collection_visibility(existing_col, 
            visible_home=preset.get('visibility_home', True),
            visible_library=preset.get('visibility_library', True))
        
        action = "Synced" if mode == 'sync' else "Appended"
        msg = f"{action} '{preset['title']}': Added {len(to_add)}, Removed {len(to_remove)}."
        return True, msg, {'total': len(found_items), 'added': len(to_add), 'removed': len(to_remove), 'poster_updated': poster_updated}

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
        except Exception:
            log.debug("get_collection_visibility error")
        
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
        except Exception:
            log.debug("get_collection_visibility fallback error")
            
        return (None, None, None)

    @staticmethod
    def apply_collection_visibility(plex_collection, visible_home=False, visible_library=False, visible_friends=False):
        """Apply visibility settings to a Plex collection."""
        try:
            # Try to use the collectionPublished attribute (simpler approach)
            try:
                # set collection visibility (published = visible on home/library)
                # using edit() with kwargs - PlexAPI doesn't provide editCollectionPublished()
                import warnings
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', message='.*deprecated.*')
                    if visible_home or visible_library:
                        try:
                            plex_collection.edit(**{'collectionPublished.value': 1})
                        except:
                            plex_collection.edit(collectionPublished=True)
                        log.debug(f"Collection '{plex_collection.title}' published")
                    else:
                        try:
                            plex_collection.edit(**{'collectionPublished.value': 0})
                        except:
                            plex_collection.edit(collectionPublished=False)
                        log.debug(f"Collection '{plex_collection.title}' unpublished")
            except Exception as e:
                log.debug(f"Failed to set collectionPublished: {e}")
            
            # Try newer plexapi methods if they exist
            try:
                if visible_home and hasattr(plex_collection, 'promoteHome'):
                    plex_collection.promoteHome()
                    log.debug(f"Collection '{plex_collection.title}' promoted to home")
                elif hasattr(plex_collection, 'demoteHome'):
                    plex_collection.demoteHome()
            except Exception as e:
                log.debug(f"Home visibility method failed: {e}")
            
            try:
                if visible_library and hasattr(plex_collection, 'promoteLibrary'):
                    plex_collection.promoteLibrary()
                    log.debug(f"Collection '{plex_collection.title}' promoted to library")
                elif hasattr(plex_collection, 'demoteLibrary'):
                    plex_collection.demoteLibrary()
            except Exception as e:
                log.debug(f"Library visibility method failed: {e}")
                    
        except Exception as e:
            log.warning(f"apply_collection_visibility failed: {e}")
            # Don't fail the whole collection creation if visibility fails
            pass

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
