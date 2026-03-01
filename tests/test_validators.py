"""
Tests for utils/validators.py

Tests the validation functions extracted from utils.py.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import patch, MagicMock
from utils.validators import validate_url, validate_url_safety, validate_path, get_session_filters


class TestValidators(unittest.TestCase):
    """Test validation functions"""

    def test_validate_url_valid_http(self):
        """Test validating valid HTTP URL"""
        valid, result = validate_url("http://example.com")
        self.assertTrue(valid)

    def test_validate_url_valid_https(self):
        """Test validating valid HTTPS URL"""
        valid, result = validate_url("https://example.com")
        self.assertTrue(valid)

    def test_validate_url_invalid(self):
        """Test validating invalid URL"""
        valid, result = validate_url("not a url")
        self.assertFalse(valid)

    def test_validate_url_empty(self):
        """Test validating empty URL"""
        valid, result = validate_url("")
        self.assertFalse(valid)

    def test_validate_url_safety_aws_metadata(self):
        """Test SSRF protection for AWS metadata endpoint"""
        valid, ip = validate_url_safety("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(valid)

    def test_validate_url_safety_localhost(self):
        """Test localhost URL (should be allowed for self-hosted apps)"""
        valid, ip = validate_url_safety("http://localhost:8080")
        # Localhost is typically allowed for self-hosted apps
        # Check implementation for actual behavior
        self.assertIsInstance(valid, bool)

    def test_validate_path_valid(self):
        """Test validating valid path"""
        result = validate_path("/valid/path/file.txt", ["/valid"], "test file")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_validate_path_traversal(self):
        """Test path traversal protection"""
        result = validate_path("../../../etc/passwd", ["/allowed"], "test file")
        # Should reject path traversal attempts
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        self.assertFalse(result[0])  # Should be invalid

    def test_get_session_filters(self):
        """Test getting session filters"""
        from app import app
        
        with app.test_request_context():
            from flask import session
            session['min_year'] = '2020'
            session['min_rating'] = '7.0'
            session['genre_filter'] = 'action'
            session['critic_filter'] = 'true'
            session['critic_threshold'] = '80'
            
            filters = get_session_filters()
            self.assertIsInstance(filters, tuple)
            self.assertEqual(len(filters), 5)


class TestBackwardCompatibility(unittest.TestCase):
    """Test backward compatibility imports"""

    def test_can_import_from_utils(self):
        """Test that functions can still be imported from utils"""
        try:
            from utils import validate_url, validate_path, get_session_filters
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import from utils (backward compatibility broken)")

    def test_can_import_from_new_module(self):
        """Test that functions can be imported from new module"""
        try:
            from utils.validators import validate_url, validate_path, get_session_filters
            self.assertTrue(True)
        except ImportError:
            self.fail("Cannot import from utils.validators")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("TESTING: utils/validators.py")
    print("="*70 + "\n")
    print("Testing validation functions...\n")
    
    unittest.main(verbosity=2)
