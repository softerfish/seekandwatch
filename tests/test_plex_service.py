"""
Tests for services/plex_service.py

Tests the Plex service functions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
import pytest

# Try to import, skip tests if import fails
try:
    from services.plex_service import PlexService
    PLEX_SERVICE_AVAILABLE = True
except ImportError as e:
    PLEX_SERVICE_AVAILABLE = False
    IMPORT_ERROR = str(e)


@pytest.mark.skipif(not PLEX_SERVICE_AVAILABLE, reason=f"PlexService import failed: {IMPORT_ERROR if not PLEX_SERVICE_AVAILABLE else ''}")
class TestPlexGuidParsing(unittest.TestCase):
    """Test Plex GUID parsing functions"""

    def test_parse_guid_to_tmdb_valid(self):
        """Test parsing valid TMDB GUID"""
        guid = "tmdb://12345"
        result = PlexService.parse_guid_to_tmdb(guid)
        self.assertEqual(result, 12345)

    def test_parse_guid_to_tmdb_url_format(self):
        """Test parsing TMDB URL format"""
        guid = "https://www.themoviedb.org/movie/12345"
        result = PlexService.parse_guid_to_tmdb(guid)
        self.assertEqual(result, 12345)

    def test_parse_guid_to_tmdb_invalid(self):
        """Test parsing invalid GUID"""
        guid = "imdb://tt1234567"
        result = PlexService.parse_guid_to_tmdb(guid)
        self.assertIsNone(result)

    def test_parse_guid_to_tmdb_empty(self):
        """Test parsing empty GUID"""
        result = PlexService.parse_guid_to_tmdb("")
        self.assertIsNone(result)

    def test_parse_guid_to_imdb_valid(self):
        """Test parsing valid IMDb GUID"""
        guid = "imdb://tt1234567"
        result = PlexService.parse_guid_to_imdb(guid)
        self.assertEqual(result, "tt1234567")

    def test_parse_guid_to_imdb_invalid(self):
        """Test parsing invalid IMDb GUID"""
        guid = "tmdb://12345"
        result = PlexService.parse_guid_to_imdb(guid)
        self.assertIsNone(result)

    def test_parse_guid_to_tvdb_valid(self):
        """Test parsing valid TVDB GUID"""
        guid = "tvdb://12345"
        result = PlexService.parse_guid_to_tvdb(guid)
        self.assertEqual(result, 12345)

    def test_parse_guid_to_tvdb_invalid(self):
        """Test parsing invalid TVDB GUID"""
        guid = "imdb://tt1234567"
        result = PlexService.parse_guid_to_tvdb(guid)
        self.assertIsNone(result)


class TestPlexResolution(unittest.TestCase):
    """Test ID resolution functions"""

    @patch('services.plex_service.requests.get')
    def test_resolve_imdb_to_tmdb_success(self, mock_get):
        """Test successful IMDb to TMDB resolution"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'movie_results': [{'id': 12345}]
        }
        mock_get.return_value = mock_response

        result = PlexService.resolve_imdb_to_tmdb("tt1234567", "movie", "fake_api_key")
        self.assertEqual(result, 12345)

    @patch('services.plex_service.requests.get')
    def test_resolve_imdb_to_tmdb_not_found(self, mock_get):
        """Test IMDb to TMDB resolution when not found"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'movie_results': []
        }
        mock_get.return_value = mock_response

        result = PlexService.resolve_imdb_to_tmdb("tt9999999", "movie", "fake_api_key")
        self.assertIsNone(result)

    def test_resolve_imdb_to_tmdb_invalid_imdb(self):
        """Test resolution with invalid IMDb ID"""
        result = PlexService.resolve_imdb_to_tmdb("invalid", "movie", "fake_api_key")
        self.assertIsNone(result)

    @patch('services.plex_service.requests.get')
    def test_resolve_title_year_to_tmdb_success(self, mock_get):
        """Test successful title+year to TMDB resolution"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'results': [{'id': 12345, 'title': 'Test Movie'}]
        }
        mock_get.return_value = mock_response

        result = PlexService.resolve_title_year_to_tmdb("Test Movie", 2020, "movie", "fake_api_key")
        self.assertEqual(result, 12345)

    @patch('services.plex_service.requests.get')
    def test_resolve_title_year_to_tmdb_not_found(self, mock_get):
        """Test title+year resolution when not found"""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            'results': []
        }
        mock_get.return_value = mock_response

        result = PlexService.resolve_title_year_to_tmdb("Nonexistent Movie", 2020, "movie", "fake_api_key")
        self.assertIsNone(result)


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility"""

    def test_can_import_service(self):
        """Test that PlexService can be imported"""
        try:
            from services.plex_service import PlexService
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import PlexService")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("TESTING: services/plex_service.py")
    print("="*70 + "\n")
    print("Testing Plex service functions...\n")
    
    unittest.main(verbosity=2)
