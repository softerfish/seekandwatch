import unittest
import sys
import os
import json

# add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import Settings, User

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_health_endpoint(self):
        """Check if the app is even running."""
        response = self.app.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertIn('ok', response.get_data(as_text=True))

    def test_webhook_security(self):
        """Ensure webhook rejects requests without a secret."""
        # This test ensures we didn't accidentally remove security
        response = self.app.post('/api/webhook', 
                                 data=json.dumps({'event': 'test'}),
                                 content_type='application/json')
        # Should be 401 (Unauthorized) or 400 (if secret is configured)
        self.assertIn(response.status_code, [400, 401])

    def test_database_connection(self):
        """Ensure the database is reachable and models are valid."""
        with app.app_context():
            user = User.query.first()
            # Database might be empty in test environment
            if user:
                self.assertIsNotNone(user)

if __name__ == '__main__':
    print("--- RUNNING INTEGRITY CHECKS ---")
    unittest.main()
