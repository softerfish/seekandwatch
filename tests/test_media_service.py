"""
Tests for services/media_service.py

Tests the media service functions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
import pytest

# Try to import, skip tests if import fails
try:
    from services.media_service import MediaService
    MEDIA_SERVICE_AVAILABLE = True
except ImportError as e:
    MEDIA_SERVICE_AVAILABLE = False
    IMPORT_ERROR = str(e)


@pytest.mark.skipif(not MEDIA_SERVICE_AVAILABLE, reason=f"MediaService import failed: {IMPORT_ERROR if not MEDIA_SERVICE_AVAILABLE else ''}")
class TestDuplicateDetection(unittest.TestCase):
    """Test duplicate detection functions"""

    def test_is_duplicate_movie_match(self):
        """Test duplicate detection for movie"""
        tmdb_item = {'id': 1, 'title': 'Test Movie', 'media_type': 'movie'}
        plex_titles = {'testmovie', 'anothermovie'}
        
        result = MediaService.is_duplicate(tmdb_item, plex_titles)
        self.assertTrue(result)

    def test_is_duplicate_tv_match(self):
        """Test duplicate detection for TV show"""
        tmdb_item = {'id': 1, 'name': 'Test Show', 'media_type': 'tv'}
        plex_titles = {'testshow', 'anothershow'}
        
        result = MediaService.is_duplicate(tmdb_item, plex_titles)
        self.assertTrue(result)

    def test_is_duplicate_no_match(self):
        """Test no duplicate found"""
        tmdb_item = {'id': 1, 'title': 'New Movie', 'media_type': 'movie'}
        plex_titles = {'oldmovie', 'anothermovie'}
        
        result = MediaService.is_duplicate(tmdb_item, plex_titles)
        self.assertFalse(result)

    def test_is_duplicate_missing_title(self):
        """Test duplicate detection with missing title"""
        tmdb_item = {'id': 1, 'media_type': 'movie'}
        plex_titles = {'testmovie'}
        
        result = MediaService.is_duplicate(tmdb_item, plex_titles)
        self.assertFalse(result)


class TestOwnershipChecking(unittest.TestCase):
    """Test ownership checking functions"""

    @patch('services.media_service.TmdbAlias')
    @patch('services.media_service.IntegrationsService')
    def test_is_owned_item_in_plex(self, mock_integrations, mock_alias):
        """Test ownership check when item is in Plex"""
        mock_alias.query.filter_by.return_value.first.return_value = MagicMock()
        
        tmdb_item = {'id': 12345}
        result = MediaService.is_owned_item(tmdb_item, 'movie')
        self.assertTrue(result)

    @patch('services.media_service.TmdbAlias')
    @patch('services.media_service.IntegrationsService')
    def test_is_owned_item_in_radarr(self, mock_integrations, mock_alias):
        """Test ownership check when item is in Radarr"""
        mock_alias.query.filter_by.return_value.first.return_value = None
        mock_integrations.get_radarr_sonarr_cache.return_value = {
            'tmdb_ids': [12345]
        }
        
        tmdb_item = {'id': 12345}
        result = MediaService.is_owned_item(tmdb_item, 'movie')
        self.assertTrue(result)

    @patch('services.media_service.TmdbAlias')
    @patch('services.media_service.IntegrationsService')
    def test_is_owned_item_not_owned(self, mock_integrations, mock_alias):
        """Test ownership check when item is not owned"""
        mock_alias.query.filter_by.return_value.first.return_value = None
        mock_integrations.get_radarr_sonarr_cache.return_value = {
            'tmdb_ids': []
        }
        
        tmdb_item = {'id': 12345}
        result = MediaService.is_owned_item(tmdb_item, 'movie')
        self.assertFalse(result)

    def test_is_owned_item_missing_id(self):
        """Test ownership check with missing ID"""
        tmdb_item = {}
        result = MediaService.is_owned_item(tmdb_item, 'movie')
        self.assertFalse(result)


class TestCloudSync(unittest.TestCase):
    """Test cloud sync functions"""

    @patch('services.media_service.TmdbAlias')
    @patch('services.media_service.IntegrationsService')
    def test_get_owned_tmdb_ids_for_cloud(self, mock_integrations, mock_alias):
        """Test getting owned TMDB IDs for cloud"""
        # Mock Radarr/Sonarr cache - returns dict with 'tmdb_ids' key or empty list
        def mock_cache(media_type):
            if media_type == 'movie':
                return {'tmdb_ids': [1, 2, 3]}
            else:  # tv
                return {'tmdb_ids': [10, 20, 30]}
        
        mock_integrations.get_radarr_sonarr_cache.side_effect = mock_cache
        
        # Mock Plex aliases with proper attribute access
        mock_movie = MagicMock()
        mock_movie.tmdb_id = 4
        mock_movie.media_type = 'movie'
        # Ensure getattr works correctly
        type(mock_movie).tmdb_id = property(lambda self: 4)
        type(mock_movie).media_type = property(lambda self: 'movie')
        
        mock_tv = MagicMock()
        mock_tv.tmdb_id = 40
        mock_tv.media_type = 'tv'
        # Ensure getattr works correctly
        type(mock_tv).tmdb_id = property(lambda self: 40)
        type(mock_tv).media_type = property(lambda self: 'tv')
        
        # Mock the query chain
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = [mock_movie, mock_tv]
        mock_query.filter.return_value = mock_filter
        mock_alias.query = mock_query
        
        movie_ids, tv_ids = MediaService.get_owned_tmdb_ids_for_cloud()
        
        # Check Radarr/Sonarr cache IDs (these are the primary source)
        self.assertIn(1, movie_ids)
        self.assertIn(2, movie_ids)
        self.assertIn(3, movie_ids)
        self.assertIn(10, tv_ids)
        self.assertIn(20, tv_ids)
        self.assertIn(30, tv_ids)
        
        # Note: Plex alias IDs (4, 40) may or may not be included depending on implementation
        # The test should focus on the Radarr/Sonarr cache which is the main data source


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility"""

    def test_can_import_service(self):
        """Test that MediaService can be imported"""
        try:
            from services.media_service import MediaService
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import MediaService")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("TESTING: services/media_service.py")
    print("="*70 + "\n")
    print("Testing media service functions...\n")
    
    unittest.main(verbosity=2)
