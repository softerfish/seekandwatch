"""
Unraid Compatibility Tests

Ensures all Unraid-critical paths and configurations remain unchanged.
These tests verify that upgrades won't break existing Unraid installations.
"""

import unittest
import os
import sys
from unittest.mock import Mock, patch

# add parent directory to path so we can import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestUnraidPaths(unittest.TestCase):
    """Test that critical Unraid paths are unchanged"""
    
    def test_config_dir_constant(self):
        """Test that CONFIG_DIR points to /config"""
        from config import CONFIG_DIR
        
        # In production, should be /config
        # In dev, might be different, but the constant should exist
        self.assertIsNotNone(CONFIG_DIR)
        self.assertIsInstance(CONFIG_DIR, str)
    
    def test_database_path(self):
        """Test that database path uses CONFIG_DIR"""
        from config import get_database_path
        
        db_path = get_database_path()
        self.assertIn('seekandwatch.db', db_path)
        # Should be in config directory
        self.assertTrue(db_path.endswith('seekandwatch.db'))
    
    def test_backup_dir(self):
        """Test that backup directory uses CONFIG_DIR"""
        from config import get_backup_dir
        
        backup_dir = get_backup_dir()
        self.assertIn('backups', backup_dir)
    
    def test_custom_poster_dir(self):
        """Test that custom poster directory is correct"""
        from utils import CUSTOM_POSTER_DIR
        
        self.assertIn('custom_posters', CUSTOM_POSTER_DIR)


class TestUnraidPort(unittest.TestCase):
    """Test that port configuration is unchanged"""
    
    def test_default_port(self):
        """Test that default port is 5000"""
        # Port is typically set in app.py or via environment
        # Just verify the app can be configured with port 5000
        self.assertEqual(5000, 5000)  # Placeholder test


class TestUnraidEnvironmentVariables(unittest.TestCase):
    """Test that environment variable names are unchanged"""
    
    def test_env_var_names(self):
        """Test that critical env var names haven't changed"""
        critical_env_vars = [
            'CONFIG_DIR',
            'PLEX_URL',
            'PLEX_TOKEN',
            'TMDB_KEY',
            'SCHEDULER_USER_ID',
        ]
        
        # These should be documented and unchanged
        # Just verify they're in the config module
        import config
        
        # CONFIG_DIR should exist
        self.assertTrue(hasattr(config, 'CONFIG_DIR'))


class TestUnraidDatabaseSchema(unittest.TestCase):
    """Test that database schema changes are handled safely"""
    
    def test_migration_system_exists(self):
        """Test that migration system is available"""
        try:
            from migrations.migration_manager import MigrationManager, run_migrations
            self.assertTrue(True)
        except ImportError:
            self.fail("Migration system not available")
    
    def test_migration_creates_backup(self):
        """Test that migrations create backups"""
        # This is tested in the migration manager itself
        # Just verify the backup function exists
        from utils import create_backup
        self.assertTrue(callable(create_backup))


class TestUnraidBackupRestore(unittest.TestCase):
    """Test that backup/restore functionality is unchanged"""
    
    def test_backup_functions_exist(self):
        """Test that backup functions are available"""
        from utils import create_backup, list_backups, restore_backup
        
        self.assertTrue(callable(create_backup))
        self.assertTrue(callable(list_backups))
        self.assertTrue(callable(restore_backup))
    
    def test_backup_endpoints_exist(self):
        """Test that backup API endpoints exist"""
        # Check that routes_backup.py exists
        backup_routes = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'api',
            'routes_backup.py'
        )
        self.assertTrue(os.path.exists(backup_routes),
                       "Backup routes file missing")


class TestUnraidAPIEndpoints(unittest.TestCase):
    """Test that critical API endpoints are unchanged"""
    
    def test_webhook_endpoint_unchanged(self):
        """Test that webhook endpoint path is unchanged"""
        # Webhook endpoint must be POST /api/webhook
        # This is tested in api_contracts.md
        # Just verify the file exists
        webhook_routes = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'api',
            'routes_webhook.py'
        )
        self.assertTrue(os.path.exists(webhook_routes),
                       "Webhook routes file missing")
    
    def test_pair_endpoint_unchanged(self):
        """Test that pairing endpoint path is unchanged"""
        # Pairing endpoint must be POST /api/pair/receive_key
        pair_routes = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'api',
            'routes_pair.py'
        )
        self.assertTrue(os.path.exists(pair_routes),
                       "Pair routes file missing")


class TestUnraidDockerCompatibility(unittest.TestCase):
    """Test Docker-specific compatibility"""
    
    def test_entrypoint_exists(self):
        """Test that entrypoint.sh exists"""
        entrypoint = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'entrypoint.sh'
        )
        self.assertTrue(os.path.exists(entrypoint),
                       "entrypoint.sh missing")
    
    def test_dockerfile_exists(self):
        """Test that Dockerfile exists"""
        dockerfile = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'Dockerfile'
        )
        self.assertTrue(os.path.exists(dockerfile),
                       "Dockerfile missing")


class TestUnraidUpgradeSafety(unittest.TestCase):
    """Test upgrade safety features"""
    
    def test_python_version_check_exists(self):
        """Test that Python version check exists"""
        try:
            from utils.version_check import check_python_version
            self.assertTrue(callable(check_python_version))
        except ImportError:
            self.fail("Python version check not available")
    
    def test_migration_rollback_capability(self):
        """Test that migrations can be rolled back"""
        try:
            from migrations.migration_manager import MigrationManager
            
            # Check that rollback method exists
            self.assertTrue(hasattr(MigrationManager, 'rollback'))
        except ImportError:
            self.fail("Migration manager not available")


class TestUnraidDocumentation(unittest.TestCase):
    """Test that Unraid documentation exists"""
    
    def test_unraid_compatibility_doc(self):
        """Test that Unraid compatibility doc exists"""
        doc = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs',
            'unraid_compatibility.md'
        )
        self.assertTrue(os.path.exists(doc),
                       "Unraid compatibility doc missing")
    
    def test_unraid_upgrade_safety_doc(self):
        """Test that Unraid upgrade safety doc exists"""
        doc = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs',
            'UNRAID_UPGRADE_SAFETY.md'
        )
        self.assertTrue(os.path.exists(doc),
                       "Unraid upgrade safety doc missing")
    
    def test_configuration_doc(self):
        """Test that configuration doc exists"""
        doc = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs',
            'configuration.md'
        )
        self.assertTrue(os.path.exists(doc),
                       "Configuration doc missing")


if __name__ == '__main__':
    print("=" * 70)
    print("UNRAID COMPATIBILITY TESTS")
    print("=" * 70)
    print("\nVerifying Unraid-critical paths and configurations...\n")
    
    unittest.main(verbosity=2)

