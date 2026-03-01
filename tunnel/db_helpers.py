"""
database operation helpers with automatic context management,
ensures database operations work correctly in all contexts
"""

import time
from models import db
from typing import Any, Optional, List, Type, TypeVar
from flask import current_app
from sqlalchemy.exc import OperationalError

T = TypeVar('T')

def safe_commit() -> bool:
    """
    safely commit database changes with error handling,
    returns true if successful, false otherwise
    """
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database commit failed: {e}")
        return False

def safe_add(obj: Any) -> bool:
    """
    safely add object to database with error handling,
    returns true if successful, false otherwise
    """
    try:
        db.session.add(obj)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database add failed: {e}")
        return False

def safe_delete(obj: Any) -> bool:
    """
    safely delete object from database with error handling,
    returns true if successful, false otherwise
    """
    try:
        db.session.delete(obj)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Database delete failed: {e}")
        return False

def commit_with_retry(max_retries=3):
    """
    commit database changes with retry logic for sqlite lock issues,
    helps when sqlite is briefly locked by another operation
    """
    for attempt in range(max_retries):
        try:
            db.session.commit()
            return
        except OperationalError as e:
            if "locked" in str(e).lower() or "busy" in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(0.15 * (attempt + 1))
                else:
                    raise
            else:
                raise
        return False

def safe_query(model: Type[T], **filters) -> List[T]:
    """
    safely query database with error handling,
    returns empty list on error
    """
    try:
        return model.query.filter_by(**filters).all()
    except Exception as e:
        current_app.logger.error(f"Database query failed: {e}")
        return []

def safe_get_or_create(model: Type[T], defaults: Optional[dict] = None, **kwargs) -> tuple:
    """
    grab existing object or create new one,
    returns (object, created) where created is true if new object was created
    """
    try:
        instance = model.query.filter_by(**kwargs).first()
        if instance:
            return instance, False
        else:
            params = dict(kwargs)
            if defaults:
                params.update(defaults)
            instance = model(**params)
            db.session.add(instance)
            db.session.commit()
            return instance, True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Get or create failed: {e}")
        raise
