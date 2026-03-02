#!/usr/bin/env python3
"""
Quick script to unlock a locked account
Run this from the seekandwatch directory
"""

import sys
import os

# Add the parent directory to the path so we can import from the app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User

def unlock_account(username):
    """Remove account lockout for a user"""
    with app.app_context():
        try:
            # Try to import the security models
            from models_security import AccountLockout
            
            # Find lockouts for this user
            user = User.query.filter_by(username=username).first()
            if not user:
                print(f"User '{username}' not found")
                return False
            
            # Delete any lockouts
            lockouts = AccountLockout.query.filter_by(user_id=user.id).all()
            if lockouts:
                for lockout in lockouts:
                    db.session.delete(lockout)
                db.session.commit()
                print(f"Removed {len(lockouts)} lockout(s) for user '{username}'")
                return True
            else:
                print(f"No lockouts found for user '{username}'")
                return True
                
        except ImportError:
            print("Security models not found - no lockout system in place")
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python unlock_account.py <username>")
        sys.exit(1)
    
    username = sys.argv[1]
    success = unlock_account(username)
    sys.exit(0 if success else 1)
