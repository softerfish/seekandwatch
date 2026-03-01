"""
Media Service
=============

Handles media matching, duplicate detection, and ownership checking.

Functions:
- is_duplicate() - Check if TMDB item is duplicate based on title
- is_owned_item() - Check if item is owned in Plex/Radarr/Sonarr
- get_owned_tmdb_ids_for_cloud() - Get all owned TMDB IDs for cloud sync
"""

import logging
from models import TmdbAlias, RadarrSonarrCache
from utils.helpers import normalize_title
from services.IntegrationsService import IntegrationsService

log = logging.getLogger(__name__)


class MediaService:
    """Service for media matching and ownership checking."""

    @staticmethod
    def is_duplicate(tmdb_item, plex_raw_titles, settings=None):
        """
        Check if a TMDB item is a duplicate based on title matching.
        
        Args:
            tmdb_item: TMDB item dict with 'title'/'name' and 'media_type'
            plex_raw_titles: Set of normalized Plex titles
            settings: Settings object (optional)
        
        Returns:
            bool: True if duplicate, False otherwise
        """
        # Simple title match check
        tmdb_title = tmdb_item.get('title') if tmdb_item.get('media_type') == 'movie' else tmdb_item.get('name')
        if not tmdb_title:
            return False
        
        norm = normalize_title(tmdb_title)
        return norm in plex_raw_titles

    @staticmethod
    def is_owned_item(tmdb_item, media_type):
        """
        Check if a TMDB item is already owned in Plex (TmdbAlias from sync) or Radarr/Sonarr.
        
        Args:
            tmdb_item: TMDB item dict with 'id'
            media_type: 'movie' or 'tv'
        
        Returns:
            bool: True if owned, False otherwise
        """
        tmdb_id = tmdb_item.get('id')
        if not tmdb_id:
            return False
        
        try:
            # Check Plex (TmdbAlias table)
            plex_match = TmdbAlias.query.filter_by(
                tmdb_id=tmdb_id,
                media_type=media_type
            ).first()
            if plex_match:
                return True
            
            # Check Radarr/Sonarr cache
            cache = IntegrationsService.get_radarr_sonarr_cache(media_type)
            owned_ids = cache.get('tmdb_ids', [])
            if tmdb_id in owned_ids:
                return True
            
            return False
        except Exception:
            log.debug("Ownership check failed")
            return False

    @staticmethod
    def get_owned_tmdb_ids_for_cloud():
        """
        Build lists of owned movie and TV TMDB IDs for Cloud sync.
        
        Combines:
        - Radarr/Sonarr cache (items with files)
        - Plex alias table (items found in Plex library)
        
        Used so SeekAndWatch Cloud can show 'Already in library' and hide those from friends.
        
        Returns:
            tuple: (movie_ids: list, tv_ids: list)
        """
        movie_ids = set()
        tv_ids = set()
        
        try:
            # Get from Radarr/Sonarr cache
            for media_type, id_set in [('movie', movie_ids), ('tv', tv_ids)]:
                cache = IntegrationsService.get_radarr_sonarr_cache(media_type)
                id_set.update(cache.get('tmdb_ids') or [])
            
            # Get from Plex (TmdbAlias has tmdb_id for items found in Plex)
            for row in TmdbAlias.query.filter(TmdbAlias.tmdb_id > 0).all():
                mid = getattr(row, 'tmdb_id', None)
                mtype = getattr(row, 'media_type', None)
                if mid and mtype == 'movie':
                    movie_ids.add(mid)
                elif mid and mtype == 'tv':
                    tv_ids.add(mid)
        except Exception:
            log.debug("Get owned IDs failed")
        
        return (list(movie_ids), list(tv_ids))
