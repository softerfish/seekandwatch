import os
import hashlib
import time
import requests
from flask import Flask, url_for
from web.routes_utility import web_utility_bp
from models import db, Settings
import unittest

class TestImageProxy(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test'
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['LOGIN_DISABLED'] = True
        db.init_app(self.app)
        self.app.register_blueprint(web_utility_bp)
        
        from unittest.mock import patch, Mock
        self.patcher = patch('web.routes_utility.current_user')
        self.mock_current_user = self.patcher.start()
        
        # Mock settings object to avoid DetachedInstanceError
        mock_settings = Mock()
        mock_settings.plex_url = 'http://plex.test'
        mock_settings.plex_token = 'token'
        mock_settings.tmdb_key = 'tmdb_key'
        self.mock_current_user.settings = mock_settings
            
        self.client = self.app.test_client()

    def tearDown(self):
        self.patcher.stop()

    def test_ssrf_protection_blocked(self):
        # Malicious URL
        resp = self.client.get('/api/proxy/image?url=http://malicious.com/steal-data')
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b'Domain not in allowlist', resp.data)

    def test_allowed_domain_plex(self):
        # Mock requests.get for Plex
        from unittest.mock import patch
        with patch('requests.get') as mocked_get:
            mocked_get.return_value.status_code = 200
            mocked_get.return_value.headers = {'Content-Type': 'image/jpeg'}
            mocked_get.return_value.content = b'fake-image-data'
            mocked_get.return_value.iter_content = lambda chunk_size: [b'fake-image-data']
            
            resp = self.client.get('/api/proxy/image?url=http://plex.test/photo.jpg')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers['Content-Type'], 'image/jpeg')

    def test_allowed_domain_tmdb(self):
        # TMDB is hardcoded as allowed
        # Let's mock requests.get
        from unittest.mock import patch
        with patch('requests.get') as mocked_get:
            mocked_get.return_value.status_code = 200
            mocked_get.return_value.headers = {'Content-Type': 'image/jpeg'}
            mocked_get.return_value.content = b'fake-image-data'
            mocked_get.return_value.iter_content = lambda chunk_size: [b'fake-image-data']
            
            resp = self.client.get('/api/proxy/image?url=https://image.tmdb.org/t/p/w500/path.jpg')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers['Content-Type'], 'image/jpeg')

    def test_caching(self):
        # Similar to above but check if file exists in cache
        cache_dir = os.path.join('assets', 'cache', 'images')
        target_url = 'https://image.tmdb.org/t/p/w500/cache-test.jpg'
        url_hash = hashlib.md5(target_url.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, url_hash)
        
        if os.path.exists(cache_path):
            os.remove(cache_path)
            
        from unittest.mock import patch
        with patch('requests.get') as mocked_get:
            mocked_get.return_value.status_code = 200
            mocked_get.return_value.headers = {'Content-Type': 'image/jpeg'}
            mocked_get.return_value.content = b'fake-image-data'
            mocked_get.return_value.iter_content = lambda chunk_size: [b'fake-image-data']
            
            self.client.get(f'/api/proxy/image?url={target_url}')
            self.assertTrue(os.path.exists(cache_path))

if __name__ == '__main__':
    unittest.main()
