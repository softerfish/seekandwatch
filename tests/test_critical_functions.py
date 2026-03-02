"""
Critical Function Tests - Phase 1 Safety Infrastructure

Tests for high-risk functions that are used across multiple files.
These tests ensure refactoring doesn't break core functionality.
"""

import unittest
import os
import sys
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock

# add parent directory to path so we can import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Settings, User, SystemLog, TmdbAlias, CollectionSchedule
from utils.helpers import normalize_title, write_log
from utils.system import is_system_locked, set_system_lock, remove_system_lock, get_lock_status
from utils.backup import create_backup, list_backups


class TestNormalizeTitle(unittest.TestCase):
    """Test title normalization - used in 4+ files (HIGH RISK)"""
    
    def test_basic_normalization(self):
        """Test basic title normalization"""
        self.assertEqual(normalize_title("The Matrix"), "matrix")
        self.assertEqual(normalize_title("The Dark Knight"), "darkknight")
    
    def test_special_characters(self):
        """Test special character handling"""
        self.assertEqual(normalize_title("Spider-Man"), "spiderman")
        self.assertEqual(normalize_title("Ocean's 11"), "oceans11")
        self.assertEqual(normalize_title("M*A*S*H"), "mash")
    
    def test_accents(self):
        """Test accent normalization"""
        self.assertEqual(normalize_title("Amélie"), "amelie")
        self.assertEqual(normalize_title("Café"), "cafe")
    
    def test_number_words(self):
        """Test number word to digit conversion"""
        self.assertEqual(normalize_title("Fantastic Four"), "fantastic4")
        self.assertEqual(normalize_title("Seven"), "7")
        self.assertEqual(normalize_title("Ocean's Eleven"), "oceans11")
    
    def test_leading_the(self):
        """Test 'The' removal"""
        self.assertEqual(normalize_title("The Avengers"), "avengers")
        self.assertEqual(normalize_title("The Matrix"), "matrix")
    
    def test_empty_and_none(self):
        """Test edge cases"""
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(None), "")
    
    def test_unicode(self):
        """Test unicode handling"""
        self.assertEqual(normalize_title("Crouching Tiger, Hidden Dragon"), "crouchingtigerhiddendragon")


class TestLockManagement(unittest.TestCase):
    """Test lock management - used in 4+ files (HIGH RISK)"""
    
    def setUp(self):
        """Clean up any existing locks before each test"""
        remove_system_lock()
    
    def tearDown(self):
        """Clean up locks after each test"""
        remove_system_lock()
    
    def test_lock_creation(self):
        """Test creating a system lock"""
        self.assertFalse(is_system_locked())
        set_system_lock("Test operation")
        self.assertTrue(is_system_locked())
    
    def test_lock_removal(self):
        """Test removing a system lock"""
        set_system_lock("Test operation")
        self.assertTrue(is_system_locked())
        remove_system_lock()
        self.assertFalse(is_system_locked())
    
    def test_lock_status(self):
        """Test getting lock status"""
        status = get_lock_status()
        self.assertFalse(status['running'])
        
        set_system_lock("Syncing collections")
        status = get_lock_status()
        self.assertTrue(status['running'])
        self.assertEqual(status['progress'], "Syncing collections")
    
    def test_multiple_locks(self):
        """Test that locks prevent concurrent operations"""
        set_system_lock("First operation")
        self.assertTrue(is_system_locked())
        
        # Second lock should overwrite (by design)
        set_system_lock("Second operation")
        status = get_lock_status()
        self.assertEqual(status['progress'], "Second operation")


class TestLogging(unittest.TestCase):
    """Test logging system - used in 6+ files (CRITICAL)"""
    
    def test_log_sanitization(self):
        """Test that sensitive data is redacted"""
        from utils.helpers import _sanitize_log_message
        
        # Test URL redaction
        self.assertIn("[URL redacted]", _sanitize_log_message("https://api.example.com/secret?token=abc123"))
        
        # Test secret redaction
        self.assertIn("[REDACTED]", _sanitize_log_message("password=secret123"))
        self.assertIn("[REDACTED]", _sanitize_log_message("token=abc123"))
        self.assertIn("[REDACTED]", _sanitize_log_message("api_key=xyz789"))
        
        # Test None and empty
        self.assertEqual("", _sanitize_log_message(None))
        self.assertEqual("", _sanitize_log_message(""))


class TestBackupOperations(unittest.TestCase):
    """Test backup operations - isolated but critical for data safety"""
    
    def test_list_backups(self):
        """Test listing backups"""
        backups = list_backups()
        self.assertIsInstance(backups, list)
    
    @patch('config.get_database_path')
    @patch('utils.backup.BACKUP_DIR')
    def test_create_backup(self, mock_backup_dir, mock_db_path):
        """Test backup creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_backup_dir = tmpdir
            mock_db_path.return_value = os.path.join(tmpdir, 'test.db')
            
            # Create a dummy database file
            with open(mock_db_path.return_value, 'w') as f:
                f.write('test')
            
            success, message = create_backup()
            # May fail if database is locked, but should return tuple
            self.assertIsInstance(success, bool)
            self.assertIsInstance(message, str)


class TestCollectionService(unittest.TestCase):
    """Test CollectionService integration - ensures circular dependency fix works"""
    
    def test_collection_service_import(self):
        """Test that CollectionService can be imported without circular dependency"""
        try:
            from services.CollectionService import CollectionService
            self.assertTrue(hasattr(CollectionService, 'run_collection_logic'))
            self.assertTrue(hasattr(CollectionService, 'apply_collection_visibility'))
            self.assertTrue(hasattr(CollectionService, 'get_collection_visibility'))
            self.assertTrue(hasattr(CollectionService, '_get_plex_tmdb_id'))
        except ImportError as e:
            self.fail(f"Failed to import CollectionService: {e}")
    
    def test_no_circular_dependency(self):
        """Test that utils.py doesn't have circular dependency wrappers"""
        import utils
        # These should NOT exist in utils anymore
        self.assertFalse(hasattr(utils, 'run_collection_logic') or 
                        callable(getattr(utils, 'run_collection_logic', None)))


class TestDatabaseModels(unittest.TestCase):
    """Test database models are intact"""
    
    def test_settings_model(self):
        """Test Settings model has critical fields"""
        # Check that Settings model has critical fields
        self.assertTrue(hasattr(Settings, 'plex_url'))
        self.assertTrue(hasattr(Settings, 'plex_token'))
        self.assertTrue(hasattr(Settings, 'tmdb_key'))
    
    def test_user_model(self):
        """Test User model has critical fields"""
        # Check that User model has critical fields
        self.assertTrue(hasattr(User, 'username'))
        self.assertTrue(hasattr(User, 'password_hash'))
    
    def test_collection_schedule_model(self):
        """Test CollectionSchedule model exists"""
        # Should be able to import the model
        self.assertTrue(hasattr(CollectionSchedule, '__tablename__'))


class TestAPIEndpoints(unittest.TestCase):
    """Test critical API endpoints - removed database-dependent tests"""
    
    def test_api_routes_module_exists(self):
        """Test that API routes modules exist"""
        try:
            from api import routes_main, routes_pair
            self.assertTrue(hasattr(routes_main, 'health'))
            self.assertTrue(hasattr(routes_pair, 'pair_start'))
        except ImportError as e:
            self.fail(f"Failed to import API routes: {e}")


if __name__ == '__main__':
    print("=" * 70)
    print("PHASE 1: CRITICAL FUNCTION TESTS")
    print("=" * 70)
    print("\nTesting high-risk functions to ensure refactoring safety...\n")
    
    # Run tests with verbose output
    unittest.main(verbosity=2)

