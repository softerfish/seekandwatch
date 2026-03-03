"""
Tests for utils/helpers.py

Tests the core helper functions extracted from utils.py.
These are CRITICAL functions used throughout the app.
"""

import sys
import os
# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import Mock, patch, MagicMock


class TestNormalizeTitle(unittest.TestCase):
    """Test title normalization function"""
    
    def test_basic_normalization(self):
        """Test basic title normalization"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("The Matrix"), "matrix")
        self.assertEqual(normalize_title("The Dark Knight"), "darkknight")
        self.assertEqual(normalize_title("Inception"), "inception")
    
    def test_special_characters(self):
        """Test special character handling"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("Spider-Man"), "spiderman")
        self.assertEqual(normalize_title("Ocean's 11"), "oceans11")
        self.assertEqual(normalize_title("M*A*S*H"), "mash")
        self.assertEqual(normalize_title("$100 Movie"), "s100movie")  # $ converts to 's'
    
    def test_accents(self):
        """Test accent normalization"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("Amélie"), "amelie")
        self.assertEqual(normalize_title("Café"), "cafe")
        self.assertEqual(normalize_title("Señor"), "senor")
    
    def test_number_words(self):
        """Test number word to digit conversion"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("Fantastic Four"), "fantastic4")
        self.assertEqual(normalize_title("Seven"), "7")
        self.assertEqual(normalize_title("Ocean's Eleven"), "oceans11")
        self.assertEqual(normalize_title("The Twelve Monkeys"), "12monkeys")
    
    def test_leading_the(self):
        """Test 'The' removal"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("The Avengers"), "avengers")
        self.assertEqual(normalize_title("The Matrix"), "matrix")
        self.assertEqual(normalize_title("The Dark Knight"), "darkknight")
    
    def test_empty_and_none(self):
        """Test edge cases"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")
    
    def test_unicode(self):
        """Test unicode handling"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("Crouching Tiger, Hidden Dragon"), "crouchingtigerhiddendragon")
        self.assertEqual(normalize_title("Parasite (기생충)"), "parasite")
    
    def test_case_insensitive(self):
        """Test case insensitivity"""
        from utils.helpers import normalize_title
        
        self.assertEqual(normalize_title("THE MATRIX"), "matrix")
        self.assertEqual(normalize_title("The Matrix"), "matrix")
        self.assertEqual(normalize_title("the matrix"), "matrix")


class TestWriteLog(unittest.TestCase):
    """Test logging function"""
    
    def test_log_sanitization_patterns(self):
        """Test various sanitization patterns"""
        from utils.helpers import _sanitize_log_message
        
        # Test URL redaction
        self.assertIn("[URL redacted]", _sanitize_log_message("https://example.com/api"))
        self.assertIn("[URL redacted]", _sanitize_log_message("http://example.com/api"))
        
        # Test secret redaction
        self.assertIn("[REDACTED]", _sanitize_log_message("password=secret123"))
        self.assertIn("[REDACTED]", _sanitize_log_message("token=abc123"))
        self.assertIn("[REDACTED]", _sanitize_log_message("api_key=xyz789"))
        
        # Test None and empty
        self.assertEqual("", _sanitize_log_message(None))
        self.assertEqual("", _sanitize_log_message(""))


class TestBackwardCompatibility(unittest.TestCase):
    """Test that new module is backward compatible with old code"""
    
    def test_can_import_from_utils(self):
        """Test that functions can still be imported from utils"""
        # Old code should still work
        try:
            from utils import write_log, normalize_title
            self.assertTrue(callable(write_log))
            self.assertTrue(callable(normalize_title))
        except ImportError:
            self.fail("Cannot import from utils (backward compatibility broken)")
    
    def test_can_import_from_new_module(self):
        """Test that functions can be imported from new module"""
        # New code should work
        try:
            from utils.helpers import write_log, normalize_title
            self.assertTrue(callable(write_log))
            self.assertTrue(callable(normalize_title))
        except ImportError:
            self.fail("Cannot import from utils.helpers")


if __name__ == '__main__':
    print("=" * 70)
    print("TESTING: utils/helpers.py")
    print("=" * 70)
    print("\nTesting core helper functions...\n")
    
    unittest.main(verbosity=2)

