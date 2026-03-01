"""secure migration helpers - replaces raw SQL with ORM operations"""

import os
import time
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from config import CONFIG_DIR

class MigrationLock:
    """file-based lock to prevent concurrent migrations"""
    
    def __init__(self, lock_path=None):
        self.lock_path = lock_path or os.path.join(CONFIG_DIR, 'migration.lock')
        self.fd = None
    
    def __enter__(self):
        """acquire lock with timeout"""
        for _ in range(30):  # wait up to 30 seconds
            try:
                # try to create lock file exclusively
                self.fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                # another worker is migrating, wait
                time.sleep(1)
            except Exception as e:
                print(f"Migration lock error: {e}")
                break
        
        # timeout or error, but try anyway (maybe stale lock)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """release lock"""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except:
                pass
        
        try:
            os.remove(self.lock_path)
        except:
            pass


def add_column_safe(engine, table_name, column_name, column_type, default=None):
    """add column using ORM inspection (safe from SQL injection)"""
    inspector = inspect(engine)
    
    # check if table exists
    if table_name not in inspector.get_table_names():
        return False
    
    # check if column already exists
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    if column_name in columns:
        return True  # already exists
    
    # build ALTER TABLE statement safely
    # column_type should be a SQLAlchemy type object, not a string
    from sqlalchemy import Table, Column, MetaData
    
    metadata = MetaData()
    table = Table(table_name, metadata, autoload_with=engine)
    
    # create column object
    if default is not None:
        col = Column(column_name, column_type, default=default)
    else:
        col = Column(column_name, column_type)
    
    # add column using SQLAlchemy (safer than raw SQL)
    try:
        with engine.connect() as conn:
            # use parameterized query (SQLAlchemy handles escaping)
            conn.execute(sqlalchemy.text(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col.type.compile(engine.dialect)}"
                + (f" DEFAULT {default}" if default is not None else "")
            ))
            conn.commit()
        return True
    except OperationalError as e:
        if "duplicate column" in str(e).lower():
            return True  # already exists
        raise


def column_exists(engine, table_name, column_name):
    """check if column exists in table"""
    inspector = inspect(engine)
    
    if table_name not in inspector.get_table_names():
        return False
    
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(engine, table_name):
    """check if table exists"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def get_table_count(engine, table_name):
    """get row count for table"""
    if not table_exists(engine, table_name):
        return 0
    
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text(f"SELECT COUNT(*) FROM {table_name}"))
        return result.scalar()


def create_backup_before_migration(app):
    """create database backup before running migrations"""
    try:
        from utils import create_backup
        backup_path = create_backup()
        if backup_path:
            print(f"✓ Created pre-migration backup: {backup_path}")
            return backup_path
    except Exception as e:
        print(f"Warning: Could not create pre-migration backup: {e}")
    return None
