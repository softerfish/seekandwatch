"""
Tests for utils/system.py

Tests the system utilities extracted from utils.py.
These are HIGH-RISK functions used for lock management.
"""

import sys
import os
# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import tempfile
from unittest.mock import patch


class TestLockManagement(unittest.TestCase):
    """Test lock management functions"""
    
    def setUp(self):
        """Set up test environment with temporary lock file"""
        self.temp_dir = tempfile.mkdtemp()
        self.lock_file = os.path.join(self.temp_dir, 'test.lock')
        
        # Patch LOCK_FILE to use temp file
        self.patcher = patch('utils.system.LOCK_FILE', self.lock_file)
        self.patcher.start()
    
    def tearDown(self):
        """Clean up"""
        self.patcher.stop()
        
        # Remove lock file if exists
        if os.path.exists(self.lock_file):
            os.remove(self.lock_file)
        
        # Remove temp directory
        os.rmdir(self.temp_dir)
    
    def test_is_system_locked_false(self):
        """Test that system is not locked initially"""
        from utils.system import is_system_locked
        
        self.assertFalse(is_system_locked())
    
    def test_set_system_lock(self):
        """Test setting a system lock"""
        from utils.system import set_system_lock, is_system_locked
        
        result = set_system_lock("Test operation")
        self.assertTrue(result)
        self.assertTrue(is_system_locked())
    
    def test_remove_system_lock(self):
        """Test removing a system lock"""
        from utils.system import set_system_lock, remove_system_lock, is_system_locked
        
        set_system_lock("Test operation")
        self.assertTrue(is_system_locked())
        
        remove_system_lock()
        self.assertFalse(is_system_locked())
    
    def test_get_lock_status_not_locked(self):
        """Test getting lock status when not locked"""
        from utils.system import get_lock_status
        
        status = get_lock_status()
        self.assertFalse(status['running'])
    
    def test_get_lock_status_locked(self):
        """Test getting lock status when locked"""
        from utils.system import set_system_lock, get_lock_status
        
        set_system_lock("Syncing collections")
        status = get_lock_status()
        
        self.assertTrue(status['running'])
        self.assertEqual(status['progress'], "Syncing collections")
    
    def test_multiple_locks(self):
        """Test that locks can be overwritten"""
        from utils.system import set_system_lock, get_lock_status
        
        set_system_lock("First operation")
        status = get_lock_status()
        self.assertEqual(status['progress'], "First operation")
        
        # Second lock should overwrite
        set_system_lock("Second operation")
        status = get_lock_status()
        self.assertEqual(status['progress'], "Second operation")
    
    def test_reset_stuck_locks(self):
        """Test resetting stuck locks"""
        from utils.system import set_system_lock, reset_stuck_locks, is_system_locked
        
        set_system_lock("Stuck operation")
        self.assertTrue(is_system_locked())
        
        success, message = reset_stuck_locks()
        self.assertTrue(success)
        self.assertIn("removed", message.lower())
        self.assertFalse(is_system_locked())
    
    def test_reset_stuck_locks_no_lock(self):
        """Test resetting when no lock exists"""
        from utils.system import reset_stuck_locks, is_system_locked
        
        self.assertFalse(is_system_locked())
        
        success, message = reset_stuck_locks()
        self.assertTrue(success)
        self.assertIn("no lock", message.lower())


class TestLockEdgeCases(unittest.TestCase):
    """Test edge cases for lock management"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.lock_file = os.path.join(self.temp_dir, 'test.lock')
        
        self.patcher = patch('utils.system.LOCK_FILE', self.lock_file)
        self.patcher.start()
    
    def tearDown(self):
        """Clean up"""
        self.patcher.stop()
        
        if os.path.exists(self.lock_file):
            os.remove(self.lock_file)
        
        os.rmdir(self.temp_dir)
    
    def test_remove_lock_when_not_locked(self):
        """Test removing lock when it doesn't exist"""
        from utils.system import remove_system_lock, is_system_locked
        
        self.assertFalse(is_system_locked())
        
        # Should not raise error
        remove_system_lock()
        self.assertFalse(is_system_locked())
    
    def test_corrupted_lock_file(self):
        """Test handling corrupted lock file"""
        from utils.system import get_lock_status
        
        # Create corrupted lock file
        with open(self.lock_file, 'w') as f:
            f.write("not valid json")
        
        status = get_lock_status()
        self.assertTrue(status['running'])
        self.assertEqual(status['progress'], 'Unknown')


class TestBackwardCompatibility(unittest.TestCase):
    """Test that new module is backward compatible with old code"""
    
    def test_can_import_from_utils(self):
        """Test that functions can still be imported from utils"""
        try:
            from utils import is_system_locked, set_system_lock, remove_system_lock, get_lock_status
            self.assertTrue(callable(is_system_locked))
            self.assertTrue(callable(set_system_lock))
            self.assertTrue(callable(remove_system_lock))
            self.assertTrue(callable(get_lock_status))
        except ImportError:
            self.fail("Cannot import from utils (backward compatibility broken)")
    
    def test_can_import_from_new_module(self):
        """Test that functions can be imported from new module"""
        try:
            from utils.system import is_system_locked, set_system_lock, remove_system_lock, get_lock_status
            self.assertTrue(callable(is_system_locked))
            self.assertTrue(callable(set_system_lock))
            self.assertTrue(callable(remove_system_lock))
            self.assertTrue(callable(get_lock_status))
        except ImportError:
            self.fail("Cannot import from utils.system")


if __name__ == '__main__':
    print("=" * 70)
    print("TESTING: utils/system.py")
    print("=" * 70)
    print("\nTesting system utilities...\n")
    
    unittest.main(verbosity=2)

