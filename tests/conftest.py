"""
pytest configuration file - automatically loaded before running tests

this file sets up the python path so tests can import app modules
when running in Docker (where tests are in /config/tests/ but app is in /app/)
"""

import sys
import os
import pytest

# add parent directory to path so tests can import app modules
# this works for both local dev (seekandwatch/tests/) and Docker (/config/tests/)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# also add /app to path for Docker environment
if os.path.exists('/app') and '/app' not in sys.path:
    sys.path.insert(0, '/app')


# pytest fixtures for tests that need them
@pytest.fixture
def app():
    """Flask app fixture"""
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    return flask_app


@pytest.fixture
def client(app):
    """Test client fixture"""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Database session fixture"""
    from models import db
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()


@pytest.fixture
def auth_user(client, db_session):
    """Authenticated user fixture"""
    from models import User, Settings
    from werkzeug.security import generate_password_hash
    
    # create test user
    user = User(
        username='testuser',
        password_hash=generate_password_hash('testpass'),
        is_admin=True
    )
    db_session.session.add(user)
    db_session.session.commit()
    
    # create settings for user
    settings = Settings(user_id=user.id)
    db_session.session.add(settings)
    db_session.session.commit()
    
    # helper to log in
    class AuthHelper:
        def login(self):
            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)
    
    return AuthHelper()

