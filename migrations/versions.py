"""
database migration versions

add new migrations here as you refactor,
each migration should have a unique version number

version numbering:
- 1-99: phase 0-1 (infrastructure)
- 100-199: phase 2 (utils.py split)
- 200-299: phase 3 (API refactoring)
- 300-399: phase 4 (web refactoring)
"""

import logging
import sqlite3
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

log = logging.getLogger(__name__)


def load_migrations(manager):
    """
    load all migrations into the manager
    
    call this on app startup before running migrations
    """
    
    # migration 1: initial migration (baseline)
    manager.register(
        version=1,
        description="Initial migration - baseline schema",
        upgrade=upgrade_1_baseline,
        downgrade=None  # can't rollback baseline
    )
    
    # migration 2: tunnel auto-recovery columns
    manager.register(
        version=2,
        description="Add tunnel auto-recovery columns to settings",
        upgrade=upgrade_2_tunnel_recovery,
        downgrade=downgrade_2_tunnel_recovery
    )


# migration 1: baseline
def upgrade_1_baseline(app: Flask, db: SQLAlchemy):
    """
    baseline migration - marks existing database as version 1
    
    this doesn't change anything, just establishes a starting point,
    all existing databases are considered version 1
    """
    log.info("Baseline migration - no changes needed")
    # no actual changes, just marking the version


# migration 2: tunnel auto-recovery
def upgrade_2_tunnel_recovery(app: Flask, db: SQLAlchemy):
    """add tunnel auto-recovery columns to settings table"""
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # check existing columns
        cursor.execute("PRAGMA table_info(settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # add new columns if they don't exist
        new_columns = [
            ("tunnel_provider", "TEXT"),  # NULL, 'cloudflare', 'ngrok'
            ("tunnel_auto_recovery_enabled", "BOOLEAN DEFAULT 1"),  # true by default
            ("tunnel_consecutive_failures", "INTEGER DEFAULT 0"),
            ("tunnel_recovery_count", "INTEGER DEFAULT 0"),
            ("tunnel_last_recovery", "TIMESTAMP"),
            ("tunnel_recovery_disabled", "BOOLEAN DEFAULT 0"),  # circuit breaker flag
            ("tunnel_user_stopped", "BOOLEAN DEFAULT 0"),  # manual stop flag
            ("tunnel_recovery_history", "TEXT"),  # JSON array of last 10 recovery attempts
        ]
        
        for column_name, column_type in new_columns:
            if column_name not in columns:
                cursor.execute(f"ALTER TABLE settings ADD COLUMN {column_name} {column_type}")
                log.info(f"Added {column_name} column to settings")
            else:
                log.info(f"{column_name} column already exists")
        
        conn.commit()
        conn.close()
        log.info("Tunnel auto-recovery migration complete")


def downgrade_2_tunnel_recovery(app: Flask, db: SQLAlchemy):
    """remove tunnel auto-recovery columns from settings table"""
    # SQLite doesn't support DROP COLUMN easily
    # would need to recreate table without the columns
    # for now, just leave them (harmless, will be ignored by old code)
    log.warning("Downgrade not fully implemented for tunnel_recovery (columns will remain but be unused)")
    
    # we can at least clear the data
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # reset all the new columns to NULL/0
        cursor.execute("""
            UPDATE settings SET 
                tunnel_provider = NULL,
                tunnel_auto_recovery_enabled = 1,
                tunnel_consecutive_failures = 0,
                tunnel_recovery_count = 0,
                tunnel_last_recovery = NULL,
                tunnel_recovery_disabled = 0,
                tunnel_user_stopped = 0,
                tunnel_recovery_history = NULL
        """)
        
        conn.commit()
        conn.close()
        log.info("Cleared tunnel auto-recovery data (columns remain)")


# example migration 2 (for reference, not active):
"""
def upgrade_2_cache_version(app: Flask, db: SQLAlchemy):
    '''add cache_version column to settings table'''
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # check if column exists
        cursor.execute("PRAGMA table_info(settings)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'cache_version' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN cache_version INTEGER DEFAULT 1")
            conn.commit()
            log.info("Added cache_version column to settings")
        else:
            log.info("cache_version column already exists")
        
        conn.close()

def downgrade_2_cache_version(app: Flask, db: SQLAlchemy):
    '''remove cache_version column from settings table'''
    # SQLite doesn't support DROP COLUMN easily
    # would need to recreate table without the column
    # for now, just leave it (harmless)
    log.warning("Downgrade not implemented for cache_version (column will remain)")
"""


# example migration 3 (for reference, not active):
"""
def upgrade_3_new_table(app: Flask, db: SQLAlchemy):
    '''create new monitoring_metrics table'''
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitoring_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                duration REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        log.info("Created monitoring_metrics table")

def downgrade_3_new_table(app: Flask, db: SQLAlchemy):
    '''drop monitoring_metrics table'''
    with app.app_context():
        db_path = app.config.get('SQLALCHEMY_DATABASE_URI', '').replace('sqlite:///', '')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("DROP TABLE IF EXISTS monitoring_metrics")
        
        conn.commit()
        conn.close()
        log.info("Dropped monitoring_metrics table")
"""

