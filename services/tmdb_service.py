"""
TMDB Service
============

Handles TMDB API integration, keyword fetching, and metadata enrichment.

Functions:
- prefetch_keywords_parallel() - Fetch TMDB keywords in parallel
- item_matches_keywords() - Check if item matches keyword filters
- prefetch_omdb_parallel() - Fetch OMDb ratings in parallel
- prefetch_runtime_parallel() - Fetch movie runtimes in parallel
- prefetch_tv_states_parallel() - Fetch TV show status in parallel
- prefetch_ratings_parallel() - Fetch content ratings in parallel
- get_tmdb_aliases() - Get alternative titles for TMDB item
"""

import json
import time
import logging
import requests
import concurrent.futures

from models import db, Settings, TmdbAlias, TmdbKeywordCache, TmdbRuntimeCache
from utils.helpers import write_log

log = logging.getLogger(__name__)


class TmdbService:
    """Service for TMDB API integration and metadata enrichment."""

    @staticmethod
    def prefetch_keywords_parallel(items, api_key):
        """
        Fetches TMDB keywords for items in parallel.
        Checks DB first, then API for missing ones, saves to DB.
        """
        if not items:
            return

        # Identify what we need
        needed = []
        cached_map = {}
        
        # Get all IDs from the list
        target_ids = [item['id'] for item in items]
        
        # Bulk fetch existing from DB
        try:
            existing = TmdbKeywordCache.query.filter(TmdbKeywordCache.tmdb_id.in_(target_ids)).all()
            for row in existing:
                try:
                    cached_map[row.tmdb_id] = json.loads(row.keywords)
                except (TypeError, ValueError):
                    cached_map[row.tmdb_id] = []
        except Exception:
            log.debug("Keyword cache read error")

        # Find what's missing from the cache
        for item in items:
            if item['id'] not in cached_map:
                needed.append(item)
        
        if not needed:
            return  # Already got everything we need

        # Fetch the missing ones from TMDB API (in parallel for speed)
        def fetch_tags(item):
            try:
                url = f"https://api.themoviedb.org/3/{item['media_type']}/{item['id']}/keywords?api_key={api_key}"
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    return None
                
                data = r.json()
                # Movies return 'keywords', TV returns 'results' - handle both
                raw_tags = data.get('keywords', data.get('results', []))
                tags = [k['name'].lower() for k in raw_tags]
                
                return {'id': item['id'], 'type': item['media_type'], 'tags': tags}
            except Exception:
                write_log("warning", "TMDB", "Keywords fetch failed")
                return None

        new_entries = []
        # Use 10 workers so we don't timeout on big batches
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_tags, needed)
            for res in results:
                if res:
                    new_entries.append(res)

        # Save to DB
        if new_entries:
            try:
                # Re-query in case another thread wrote the same IDs
                new_ids = [e['id'] for e in new_entries]
                existing_in_db = db.session.query(TmdbKeywordCache.tmdb_id).filter(
                    TmdbKeywordCache.tmdb_id.in_(new_ids)
                ).all()
                existing_ids = {r[0] for r in existing_in_db}

                count_added = 0
                for entry in new_entries:
                    # Only add if it still doesn't exist
                    if entry['id'] not in existing_ids:
                        db.session.add(TmdbKeywordCache(
                            tmdb_id=entry['id'],
                            media_type=entry['type'],
                            keywords=json.dumps(entry['tags'])
                        ))
                        count_added += 1
                
                # Only clean up old entries if we actually added new stuff
                if count_added > 0:
                    s = Settings.query.first()
                    limit = s.keyword_cache_size or 3000
                    
                    total = TmdbKeywordCache.query.count()
                    if total > limit:
                        # Delete the oldest entries to stay under the limit
                        excess = total - limit
                        subq = db.session.query(TmdbKeywordCache.id).order_by(
                            TmdbKeywordCache.timestamp.asc()
                        ).limit(excess).subquery()
                        TmdbKeywordCache.query.filter(
                            TmdbKeywordCache.id.in_(subq)
                        ).delete(synchronize_session=False)

                db.session.commit()
            except Exception:
                log.debug("Keyword cache save error")
                db.session.rollback()

    @staticmethod
    def item_matches_keywords(item, target_keywords):
        """Check if item matches keyword filters."""
        # If no keywords filter, everything matches
        if not target_keywords:
            return True
        
        # Normalize the search terms
        search_terms = {t.lower() for t in target_keywords}
        
        # Quick check: see if keywords are in the title/overview
        text_blob = (
            item.get('title', '') + ' ' + 
            item.get('name', '') + ' ' + 
            item.get('overview', '')
        ).lower()
        for term in search_terms:
            if term in text_blob:
                return True
                
        # Deeper check: look at the cached TMDB keywords
        try:
            entry = TmdbKeywordCache.query.filter_by(tmdb_id=item['id']).first()
            api_tags = json.loads(entry.keywords) if entry else []
        except Exception:
            write_log("warning", "TMDB", "Keyword cache lookup failed")
            api_tags = []
        
        if api_tags:
            if search_terms.intersection(set(api_tags)):
                return True
                    
        return False

    @staticmethod
    def prefetch_omdb_parallel(items, api_key):
        """Fetch OMDb ratings (Rotten Tomatoes) in parallel."""
        # Note: OMDb prefetch is currently disabled to prevent API limit issues
        # We now rely on Plex's internal metadata for critic ratings
        pass

    @staticmethod
    def prefetch_runtime_parallel(items, api_key):
        """Fetch runtime from TMDB in parallel with database caching."""
        if not api_key or not items:
            return
        
        # Only fetch for movies that don't already have runtime
        movies_to_fetch = [
            item for item in items 
            if item.get('media_type') == 'movie' and not item.get('runtime')
        ]
        
        if not movies_to_fetch:
            # Set default for TV shows
            for item in items:
                if item.get('media_type') == 'tv' and not item.get('runtime'):
                    item['runtime'] = 0
            return
        
        # Check database cache first
        target_ids = [item['id'] for item in movies_to_fetch]
        cached_runtimes = {}
        try:
            existing = TmdbRuntimeCache.query.filter(
                TmdbRuntimeCache.tmdb_id.in_(target_ids)
            ).all()
            for row in existing:
                cached_runtimes[row.tmdb_id] = row.runtime
        except Exception:
            log.debug("Runtime cache read error")
        
        # Apply cached values
        for item in movies_to_fetch:
            if item['id'] in cached_runtimes:
                item['runtime'] = cached_runtimes[item['id']]
        
        # Only fetch what's not cached
        needs_fetch = [
            item for item in movies_to_fetch 
            if item['id'] not in cached_runtimes
        ]
        
        if not needs_fetch:
            # All were cached, just set TV defaults
            for item in items:
                if item.get('media_type') == 'tv' and not item.get('runtime'):
                    item['runtime'] = 0
            return
        
        def fetch_runtime(item):
            """Fetch runtime for a single movie with better error handling."""
            try:
                url = f"https://api.themoviedb.org/3/movie/{item['id']}?api_key={api_key}"
                response = requests.get(url, timeout=5)
                
                # Handle rate limits (429)
                if response.status_code == 429:
                    time.sleep(1)  # Wait and retry once
                    response = requests.get(url, timeout=5)
                
                if response.status_code != 200:
                    return {'id': item.get('id'), 'runtime': 0}
                
                data = response.json()
                runtime = data.get('runtime', 0)
                return {'id': item.get('id'), 'runtime': runtime}
            except requests.exceptions.Timeout:
                return {'id': item.get('id'), 'runtime': 0}
            except requests.exceptions.RequestException:
                return {'id': item.get('id'), 'runtime': 0}
            except (KeyError, ValueError):
                return {'id': item.get('id'), 'runtime': 0}
            except Exception:
                log.debug(f"Unexpected error fetching runtime for {item.get('id')}")
                return {'id': item.get('id'), 'runtime': 0}
        
        # Fetch with rate limiting (5 workers to avoid hitting TMDB limits)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(fetch_runtime, needs_fetch))
        
        # Update items and save to cache
        new_entries = []
        for result in results:
            if result and result.get('id'):
                item_id = result['id']
                runtime = result.get('runtime', 0)
                
                # Update item
                for item in items:
                    if item.get('id') == item_id:
                        item['runtime'] = runtime
                        break
                
                # Save to cache (only if successful and runtime > 0)
                if runtime > 0:
                    new_entries.append(TmdbRuntimeCache(
                        tmdb_id=item_id,
                        media_type='movie',
                        runtime=runtime
                    ))
        
        # Bulk save to database
        if new_entries:
            try:
                db.session.bulk_save_objects(new_entries)
                db.session.commit()
                
                # Prune cache if it exceeds the limit
                try:
                    s = Settings.query.first()
                    if s:
                        limit = s.runtime_cache_size or 3000
                        total = TmdbRuntimeCache.query.count()
                        if total > limit:
                            excess = total - limit
                            subq = db.session.query(TmdbRuntimeCache.id).order_by(
                                TmdbRuntimeCache.timestamp.asc()
                            ).limit(excess).subquery()
                            db.session.query(TmdbRuntimeCache).filter(
                                TmdbRuntimeCache.id.in_(db.session.query(subq.c.id))
                            ).delete(synchronize_session=False)
                            db.session.commit()
                except Exception:
                    log.debug("Error pruning runtime cache")
                    db.session.rollback()
            except Exception:
                log.debug("Error saving runtime cache")
                db.session.rollback()
        
        # Set default for TV shows
        for item in items:
            if item.get('media_type') == 'tv' and not item.get('runtime'):
                item['runtime'] = 0

    @staticmethod
    def prefetch_tv_states_parallel(items, api_key):
        """Fetch TV show status (Returning Series, Ended, etc.) in parallel."""
        if not api_key or not items:
            return
        
        tv_items = [item for item in items if item.get('media_type') == 'tv']
        if not tv_items:
            return

        def fetch_status(item):
            try:
                url = f"https://api.themoviedb.org/3/tv/{item['id']}?api_key={api_key}"
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    return {'id': item['id'], 'status': data.get('status', 'Unknown')}
            except Exception:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_status, tv_items)

        status_map = {r['id']: r['status'] for r in results if r}
        for item in tv_items:
            if item['id'] in status_map:
                item['status'] = status_map[item['id']]

    @staticmethod
    def prefetch_ratings_parallel(items, api_key):
        """Fetch content ratings (PG, PG-13, R, etc.) in parallel."""
        if not api_key or not items:
            return

        def fetch_rating(item):
            if 'content_rating' in item:
                return None
            
            try:
                media_type = item.get('media_type', 'movie')
                if media_type == 'movie':
                    url = f"https://api.themoviedb.org/3/movie/{item['id']}/release_dates?api_key={api_key}"
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        # Look for US rating
                        for country in data.get('results', []):
                            if country.get('iso_3166_1') == 'US':
                                for release in country.get('release_dates', []):
                                    cert = release.get('certification', '').strip()
                                    if cert:
                                        return {'id': item['id'], 'rating': cert}
                else:  # TV
                    url = f"https://api.themoviedb.org/3/tv/{item['id']}/content_ratings?api_key={api_key}"
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        # Look for US rating
                        for rating in data.get('results', []):
                            if rating.get('iso_3166_1') == 'US':
                                cert = rating.get('rating', '').strip()
                                if cert:
                                    return {'id': item['id'], 'rating': cert}
            except Exception:
                pass
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_rating, items)

        rating_map = {r['id']: r['rating'] for r in results if r}
        for item in items:
            if item['id'] in rating_map:
                item['content_rating'] = rating_map[item['id']]

    @staticmethod
    def get_tmdb_aliases(tmdb_id, media_type, settings):
        """Get alternative titles for a TMDB item."""
        try:
            cached = TmdbAlias.query.filter_by(tmdb_id=tmdb_id, media_type=media_type).first()
            if cached:
                return [cached.plex_title, cached.original_title]
            
            # Fetch from TMDB API if not cached
            if not settings or not settings.tmdb_key:
                return []
            
            url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={settings.tmdb_key}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                title = data.get('title') if media_type == 'movie' else data.get('name')
                original = data.get('original_title') if media_type == 'movie' else data.get('original_name')
                return [title, original] if title != original else [title]
        except Exception:
            log.debug("Get TMDB aliases failed")
        return []

    @staticmethod
    def fetch_omdb_ratings(title, year, api_key):
        """Fetch OMDb ratings (currently disabled to prevent API limit issues)."""
        # OMDb fetch removed to prevent API limit issues.
        # We now rely on Plex's internal metadata for critic ratings.
        return []

    @staticmethod
    def sync_remote_aliases():
        """Sync remote aliases (currently a no-op, handled by sync_plex_library)."""
        return True, "Started in background"

    @staticmethod
    def fetch_omdb_ratings(title, year, api_key):
        """Fetch OMDb ratings (currently disabled to prevent API limit issues)."""
        # OMDb fetch removed to prevent API limit issues.
        # We now rely on Plex's internal metadata for critic ratings.
        return []

    @staticmethod
    def sync_remote_aliases():
        """Sync remote aliases (currently a no-op, handled by sync_plex_library)."""
        return True, "Started in background"
