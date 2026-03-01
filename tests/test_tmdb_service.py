"""
Tests for services/tmdb_service.py

Tests the TMDB service functions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
import pytest

# Try to import, skip tests if import fails
try:
    from services.tmdb_service import TmdbService
    TMDB_SERVICE_AVAILABLE = True
except ImportError as e:
    TMDB_SERVICE_AVAILABLE = False
    IMPORT_ERROR = str(e)


@pytest.mark.skipif(not TMDB_SERVICE_AVAILABLE, reason=f"TmdbService import failed: {IMPORT_ERROR if not TMDB_SERVICE_AVAILABLE else ''}")
class TestKeywordMatching(unittest.TestCase):
    """Test keyword matching functions"""

    def test_item_matches_keywords_no_filter(self):
        """Test matching with no keyword filter"""
        item = {'id': 1, 'title': 'Test Movie'}
        result = TmdbService.item_matches_keywords(item, [])
        self.assertTrue(result)

    def test_item_matches_keywords_title_match(self):
        """Test matching keyword in title"""
        item = {'id': 1, 'title': 'Action Movie', 'overview': 'A great film'}
        result = TmdbService.item_matches_keywords(item, ['action'])
        self.assertTrue(result)

    def test_item_matches_keywords_overview_match(self):
        """Test matching keyword in overview"""
        item = {'id': 1, 'title': 'Movie', 'overview': 'An action-packed adventure'}
        result = TmdbService.item_matches_keywords(item, ['action'])
        self.assertTrue(result)

    def test_item_matches_keywords_no_match(self):
        """Test no keyword match"""
        item = {'id': 1, 'title': 'Drama Movie', 'overview': 'A sad story'}
        result = TmdbService.item_matches_keywords(item, ['comedy'])
        self.assertFalse(result)


class TestAliases(unittest.TestCase):
    """Test TMDB alias functions"""

    @patch('services.tmdb_service.TmdbAlias')
    def test_get_tmdb_aliases_cached(self, mock_alias):
        """Test getting aliases from cache"""
        mock_cached = MagicMock()
        mock_cached.plex_title = "Movie Title"
        mock_cached.original_title = "Original Title"
        mock_alias.query.filter_by.return_value.first.return_value = mock_cached

        result = TmdbService.get_tmdb_aliases(12345, 'movie', None)
        self.assertEqual(result, ["Movie Title", "Original Title"])

    @patch('services.tmdb_service.TmdbAlias')
    def test_get_tmdb_aliases_not_cached(self, mock_alias):
        """Test getting aliases when not cached"""
        mock_alias.query.filter_by.return_value.first.return_value = None

        result = TmdbService.get_tmdb_aliases(12345, 'movie', None)
        self.assertEqual(result, [])


class TestPrefetchFunctions(unittest.TestCase):
    """Test prefetch functions"""

    def test_prefetch_keywords_empty_list(self):
        """Test prefetching keywords with empty list"""
        # Should not raise exception
        TmdbService.prefetch_keywords_parallel([], "fake_api_key")
        self.assertTrue(True)

    def test_prefetch_runtime_empty_list(self):
        """Test prefetching runtime with empty list"""
        # Should not raise exception
        TmdbService.prefetch_runtime_parallel([], "fake_api_key")
        self.assertTrue(True)

    def test_prefetch_tv_states_empty_list(self):
        """Test prefetching TV states with empty list"""
        # Should not raise exception
        TmdbService.prefetch_tv_states_parallel([], "fake_api_key")
        self.assertTrue(True)

    def test_prefetch_ratings_empty_list(self):
        """Test prefetching ratings with empty list"""
        # Should not raise exception
        TmdbService.prefetch_ratings_parallel([], "fake_api_key")
        self.assertTrue(True)


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility"""

    def test_can_import_service(self):
        """Test that TmdbService can be imported"""
        try:
            from services.tmdb_service import TmdbService
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import TmdbService")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("TESTING: services/tmdb_service.py")
    print("="*70 + "\n")
    print("Testing TMDB service functions...\n")
    
    unittest.main(verbosity=2)
