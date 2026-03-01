"""
Tests for utils/cache.py

Tests the caching functions extracted from utils.py.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import tempfile
import json
from unittest.mock import patch, MagicMock
from utils.cache import (
    load_results_cache, save_results_cache,
    get_history_cache, set_history_cache,
    get_tmdb_rec_cache, set_tmdb_rec_cache,
    score_recommendation, diverse_sample,
    RESULTS_CACHE
)


class TestCacheFunctions(unittest.TestCase):
    """Test caching operations"""

    def test_score_recommendation(self):
        """Test recommendation scoring algorithm"""
        item = {
            'vote_average': 8.0,
            'vote_count': 1000,
            'popularity': 50.0
        }
        score = score_recommendation(item)
        self.assertIsInstance(score, float)
        self.assertGreater(score, 0)

    def test_score_recommendation_missing_data(self):
        """Test scoring with missing data"""
        item = {}
        score = score_recommendation(item)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0)

    def test_diverse_sample_empty(self):
        """Test diverse sampling with empty list"""
        result = diverse_sample([], 10)
        self.assertEqual(result, [])

    def test_diverse_sample_basic(self):
        """Test diverse sampling with basic list"""
        items = [{'id': i, 'title': f'Item {i}'} for i in range(20)]
        result = diverse_sample(items, 10)
        self.assertEqual(len(result), 10)
        self.assertTrue(all(item in items for item in result))

    def test_diverse_sample_with_bucket_fn(self):
        """Test diverse sampling with bucket function"""
        items = [
            {'id': 1, 'genre': 'action'},
            {'id': 2, 'genre': 'action'},
            {'id': 3, 'genre': 'comedy'},
            {'id': 4, 'genre': 'comedy'},
        ]
        result = diverse_sample(items, 2, bucket_fn=lambda x: x.get('genre'))
        self.assertEqual(len(result), 2)

    def test_history_cache_operations(self):
        """Test history cache get/set"""
        key = 'test_key'
        candidates = [{'id': 1}, {'id': 2}]
        
        # Set cache
        set_history_cache(key, candidates)
        
        # Get cache
        result = get_history_cache(key)
        self.assertEqual(result, candidates)

    def test_history_cache_missing_key(self):
        """Test getting non-existent cache key"""
        result = get_history_cache('nonexistent_key_12345')
        self.assertIsNone(result)

    def test_tmdb_rec_cache_operations(self):
        """Test TMDB recommendation cache get/set"""
        key = 'test_tmdb_key'
        results = [{'id': 1, 'title': 'Movie 1'}]
        
        # Set cache
        set_tmdb_rec_cache(key, results)
        
        # Get cache
        cached = get_tmdb_rec_cache(key)
        self.assertEqual(cached, results)

    def test_tmdb_rec_cache_missing_key(self):
        """Test getting non-existent TMDB cache key"""
        result = get_tmdb_rec_cache('nonexistent_tmdb_key_12345')
        self.assertIsNone(result)

    def test_results_cache_constant(self):
        """Test that RESULTS_CACHE is accessible"""
        self.assertIsInstance(RESULTS_CACHE, dict)


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility imports"""

    def test_can_import_from_utils(self):
        """Test that functions can still be imported from utils"""
        try:
            from utils import (
                load_results_cache, save_results_cache,
                get_history_cache, set_history_cache,
                get_tmdb_rec_cache, set_tmdb_rec_cache,
                score_recommendation, diverse_sample
            )
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import from utils (backward compatibility broken)")

    def test_can_import_from_new_module(self):
        """Test that functions can be imported from new module"""
        try:
            from utils.cache import (
                load_results_cache, save_results_cache,
                get_history_cache, set_history_cache,
                get_tmdb_rec_cache, set_tmdb_rec_cache,
                score_recommendation, diverse_sample
            )
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import from utils.cache")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("TESTING: utils/cache.py")
    print("="*70 + "\n")
    print("Testing caching operations...\n")
    
    unittest.main(verbosity=2)
