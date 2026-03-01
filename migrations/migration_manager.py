"""
database migration manager - critical safety feature

handles database schema changes during refactoring to ensure
existing Unraid users can upgrade without data loss

usage:
    from migrations.migration_manager import run_migrations
    
    # on app startup
    run_migrations(app, db)
"""

import os
import logging
import sqlite3
from typing import List, Tuple, Callable
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

log = logging.getLogger(__name__)


class Migration:
    """represents a single database migration"""
    
    def __init__(self, version: int, description: str, 
                 upgrade: Callable, downgrade: Callable = None):
        self.version = version
        self.description = description
        self.upgrade = upgrade
        self.downgrade = downgrade
    
    def __repr__(self):
        return f"Migration(v{self.version}: {self.description})"


class MigrationManager:
    """
    manages database migrations with version tracking,
    ensures migrations run in order and only once
    """
    
    def __init__(self, app: Flask, db: SQLAlchemy):
        self.app = app
        self.db = db
        self.migrations: List[Migration] = []
        self._ensure_migration_table()
    
    def _ensure_migration_table(self):
        """create migration tracking table if it doesn't exist"""
        try:
            with self.app.app_context():
                # Use raw SQL to avoid model dependencies
                db_path = self.app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
                if not db_path or not os.path.exists(db_path):
                    log.warning("Database not found, skipping migration table creation")
                    return
                
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        description TEXT NOT NULL,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                conn.close()
                log.info("Migration tracking table ready")
        except Exception as e:
            log.error(f"Failed to create migration table: {e}")
    
    def register(self, version: int, description: str, 
                 upgrade: Callable, downgrade: Callable = None):
        """
        register a migration
        
        args:
            version: migration version number (must be unique and sequential)
            description: human-readable description
            upgrade: function to apply migration
            downgrade: optional function to rollback migration
        """
        migration = Migration(version, description, upgrade, downgrade)
        self.migrations.append(migration)
        log.debug(f"Registered {migration}")
    
    def get_current_version(self) -> int:
        """grab the current database schema version"""
        try:
            with self.app.app_context():
                db_path = self.app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
                if not db_path or not os.path.exists(db_path):
                    return 0
                
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute("SELECT MAX(version) FROM schema_migrations")
                result = cursor.fetchone()
                conn.close()
                
                return result[0] if result and result[0] else 0
        except Exception as e:
            log.warning(f"Could not get current version: {e}")
            return 0
    
    def get_pending_migrations(self) -> List[Migration]:
        """grab migrations that haven't been applied yet"""
        current_version = self.get_current_version()
        pending = [m for m in self.migrations if m.version > current_version]
        return sorted(pending, key=lambda m: m.version)
    
    def apply_migration(self, migration: Migration) -> bool:
        """
        apply a single migration
        
        returns:
            bool: true if successful, false otherwise
        """
        try:
            with self.app.app_context():
                log.info(f"Applying {migration}")
                
                # Run the upgrade function
                migration.upgrade(self.app, self.db)
                
                # Record the migration
                db_path = self.app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                    (migration.version, migration.description)
                )
                
                conn.commit()
                conn.close()
                
                log.info(f"Successfully applied {migration}")
                return True
        except Exception as e:
            log.error(f"Failed to apply {migration}: {e}")
            return False
    
    def run_migrations(self) -> Tuple[int, int]:
        """
        run all pending migrations
        
        returns:
            tuple[int, int]: (applied_count, failed_count)
        """
        pending = self.get_pending_migrations()
        
        if not pending:
            log.info("No pending migrations")
            return (0, 0)
        
        log.info(f"Found {len(pending)} pending migrations")
        
        applied = 0
        failed = 0
        
        for migration in pending:
            if self.apply_migration(migration):
                applied += 1
            else:
                failed += 1
                log.error(f"Migration failed, stopping at version {migration.version}")
                break
        
        return (applied, failed)
    
    def rollback(self, target_version: int) -> bool:
        """
        rollback to a specific version
        
        args:
            target_version: version to rollback to
            
        returns:
            bool: true if successful, false otherwise
        """
        current_version = self.get_current_version()
        
        if target_version >= current_version:
            log.warning(f"Target version {target_version} >= current version {current_version}")
            return False
        
        # Get migrations to rollback (in reverse order)
        to_rollback = [m for m in self.migrations 
                      if target_version < m.version <= current_version]
        to_rollback.sort(key=lambda m: m.version, reverse=True)
        
        for migration in to_rollback:
            if not migration.downgrade:
                log.error(f"Migration {migration.version} has no downgrade function")
                return False
            
            try:
                log.info(f"Rolling back {migration}")
                migration.downgrade(self.app, self.db)
                
                # Remove from tracking table
                db_path = self.app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM schema_migrations WHERE version = ?", (migration.version,))
                conn.commit()
                conn.close()
                
                log.info(f"Successfully rolled back {migration}")
            except Exception as e:
                log.error(f"Failed to rollback {migration}: {e}")
                return False
        
        return True


# global migration manager instance
_manager = None


def get_manager(app: Flask, db: SQLAlchemy) -> MigrationManager:
    """grab or create the global migration manager"""
    global _manager
    if _manager is None:
        _manager = MigrationManager(app, db)
    return _manager


def run_migrations(app: Flask, db: SQLAlchemy) -> Tuple[int, int]:
    """
    run all pending migrations
    
    call this on app startup
    
    returns:
        tuple[int, int]: (applied_count, failed_count)
    """
    manager = get_manager(app, db)
    return manager.run_migrations()


def register_migration(version: int, description: str, 
                      upgrade: Callable, downgrade: Callable = None):
    """
    decorator to register a migration
    
    usage:
        @register_migration(1, "Add new_column to settings")
        def upgrade_1(app, db):
            # migration code
            pass
    """
    def decorator(upgrade_func):
        # this will be called when migrations are loaded
        # the actual registration happens in migrations/versions.py
        upgrade_func._migration_version = version
        upgrade_func._migration_description = description
        return upgrade_func
    return decorator


# example migration (for reference):
"""
def upgrade_add_column(app, db):
    '''add new_column to settings table'''
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'new_column' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN new_column TEXT")
            conn.commit()
        
        conn.close()

def downgrade_add_column(app, db):
    '''remove new_column from settings table'''
    # SQLite doesn't support DROP COLUMN easily
    # would need to recreate table without the column
    pass

# register the migration
manager = get_manager(app, db)
manager.register(1, "Add new_column to settings", upgrade_add_column, downgrade_add_column)
"""

