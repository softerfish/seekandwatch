"""migration to add security tracking tables"""

from models import db
from models_security import WebhookAttempt, LoginAttempt, AccountLockout

def upgrade():
    """create security tables"""
    try:
        # create tables using ORM (safe from SQL injection)
        WebhookAttempt.__table__.create(db.engine, checkfirst=True)
        LoginAttempt.__table__.create(db.engine, checkfirst=True)
        AccountLockout.__table__.create(db.engine, checkfirst=True)
        
        print("✓ Created security tables: webhook_attempt, login_attempt, account_lockout")
        return True
    except Exception as e:
        print(f"Failed to create security tables: {e}")
        return False

def downgrade():
    """drop security tables"""
    try:
        WebhookAttempt.__table__.drop(db.engine, checkfirst=True)
        LoginAttempt.__table__.drop(db.engine, checkfirst=True)
        AccountLockout.__table__.drop(db.engine, checkfirst=True)
        
        print("✓ Dropped security tables")
        return True
    except Exception as e:
        print(f"Failed to drop security tables: {e}")
        return False
