"""
Unit tests for Phase 3.2E & 3.2F migrated routes
Tests utility routes and cloud request routes
"""

import unittest
import sys
import os
import json
from unittest.mock import Mock, patch, MagicMock
from flask import url_for

# add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import User, Settings, CloudRequest, DeletedCloudId
from werkzeug.security import generate_password_hash


class TestBase(unittest.TestCase):
    """Base test class with setup/teardown"""
    
    def setUp(self):
        """Set up test client and database"""
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Create test user
        user = User(
            username='testuser',
            password_hash=generate_password_hash('testpass'),
            is_admin=True
        )
        db.session.add(user)
        db.session.commit()
        
        # Create settings for user
        settings = Settings(
            user_id=user.id,
            plex_url='http://localhost:32400',
            plex_token='test_token',
            tmdb_key='test_tmdb_key',
            cloud_api_key='test_cloud_key',
            cloud_enabled=True
        )
        db.session.add(settings)
        db.session.commit()
    
    def tearDown(self):
        """Clean up after tests"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
    
    def login(self):
        """Helper to log in test user"""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = '1'


# ============================================================================
# PHASE 3.2E: UTILITY ROUTES TESTS
# ============================================================================

class TestTriggerUpdateRoute(TestBase):
    """Tests for /trigger_update route"""
    
    @patch('web.routes_utility.check_for_updates')
    @patch('web.routes_utility.is_unraid')
    @patch('web.routes_utility.is_git_repo')
    def test_trigger_update_no_update_available(self, mock_git, mock_unraid, mock_check):
        """Test trigger_update when no update available"""
        self.login()
        mock_check.return_value = None
        mock_unraid.return_value = False
        mock_git.return_value = False
        
        response = self.client.post('/trigger_update')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['action'], 'none')
    
    @patch('web.routes_utility.check_for_updates')
    @patch('web.routes_utility.is_unraid')
    def test_trigger_update_unraid_instruction(self, mock_unraid, mock_check):
        """Test trigger_update on Unraid (should show instruction)"""
        self.login()
        mock_check.return_value = '1.7.0'
        mock_unraid.return_value = True
        
        response = self.client.post('/trigger_update')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['action'], 'unraid_instruction')
        self.assertEqual(data['version'], '1.7.0')
    
    def test_trigger_update_requires_auth(self):
        """Test trigger_update requires authentication"""
        response = self.client.post('/trigger_update')
        self.assertEqual(response.status_code, 302)  # Redirect to login


class TestCloudConnectionTest(TestBase):
    """Tests for /api/cloud/test route"""
    
    @patch('web.routes_utility.requests.get')
    @patch('web.routes_utility.CloudService.get_cloud_base_url')
    def test_cloud_test_success(self, mock_base_url, mock_get):
        """Test successful cloud connection"""
        self.login()
        mock_base_url.return_value = 'https://cloud.example.com'
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        response = self.client.post('/api/cloud/test',
                                    json={'api_key': 'test_key'},
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertIn('valid', data['message'].lower())
    
    @patch('web.routes_utility.requests.get')
    @patch('web.routes_utility.CloudService.get_cloud_base_url')
    def test_cloud_test_invalid_key(self, mock_base_url, mock_get):
        """Test cloud connection with invalid API key"""
        self.login()
        mock_base_url.return_value = 'https://cloud.example.com'
        mock_response = Mock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response
        
        response = self.client.post('/api/cloud/test',
                                    json={'api_key': 'bad_key'},
                                    content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('invalid', data['message'].lower())
    
    def test_cloud_test_no_api_key(self):
        """Test cloud connection without API key"""
        self.login()
        response = self.client.post('/api/cloud/test',
                                    json={},
                                    content_type='application/json')
        
        # The endpoint may return 200 with error status or 400
        # Both are acceptable as long as it indicates an error
        self.assertIn(response.status_code, [200, 400])
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')


class TestAutodiscoverRoute(TestBase):
    """Tests for /api/settings/autodiscover route"""
    
    @patch('web.routes_utility.socket.socket')
    @patch('web.routes_utility.requests.get')
    def test_autodiscover_finds_services(self, mock_get, mock_socket):
        """Test autodiscover finds local services"""
        self.login()
        # Mock socket connection success
        mock_sock = Mock()
        mock_sock.connect_ex.return_value = 0
        mock_socket.return_value.__enter__.return_value = mock_sock
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        response = self.client.post('/api/settings/autodiscover')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertIn('found', data)
    
    def test_autodiscover_requires_auth(self):
        """Test autodiscover requires authentication"""
        response = self.client.post('/api/settings/autodiscover')
        self.assertEqual(response.status_code, 302)


class TestPlexMetadataRoute(TestBase):
    """Tests for /api/plex/metadata route"""
    
    @patch('web.routes_utility.PlexServer')
    def test_plex_metadata_success(self, mock_plex):
        """Test successful Plex metadata fetch"""
        self.login()
        # Mock Plex server
        mock_server = Mock()
        mock_account = Mock()
        mock_account.username = 'testuser'
        mock_account.users.return_value = []
        mock_server.myPlexAccount.return_value = mock_account
        
        mock_section = Mock()
        mock_section.title = 'Movies'
        mock_section.type = 'movie'
        mock_server.library.sections.return_value = [mock_section]
        
        mock_plex.return_value = mock_server
        
        response = self.client.get('/api/plex/metadata')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('users', data)
        self.assertIn('libraries', data)
    
    def test_plex_metadata_no_settings(self):
        """Test Plex metadata with no Plex configured"""
        self.login()
        # Clear Plex settings
        settings = Settings.query.first()
        settings.plex_url = None
        settings.plex_token = None
        db.session.commit()
        
        response = self.client.get('/api/plex/metadata')
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['users'], [])
        self.assertEqual(data['libraries'], [])


# ============================================================================
# PHASE 3.2F: CLOUD REQUEST ROUTES TESTS
# ============================================================================

class TestRequestsPageRoute(TestBase):
    """Tests for /requests route"""
    
    def test_requests_page_redirects(self):
        """Test /requests redirects to settings"""
        self.login()
        response = self.client.get('/requests')
        
        self.assertEqual(response.status_code, 302)
        self.assertIn('/settings', response.location)


class TestRequestsSettingsRoute(TestBase):
    """Tests for /requests/settings route"""
    
    @patch('web.routes_requests.CloudService.get_cloud_import_log')
    def test_requests_settings_loads(self, mock_log):
        """Test requests settings page loads"""
        self.login()
        mock_log.return_value = []
        
        response = self.client.get('/requests/settings')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b'requests_settings' in response.data or b'cloud' in response.data.lower())
    
    def test_requests_settings_requires_auth(self):
        """Test requests settings requires authentication"""
        response = self.client.get('/requests/settings')
        self.assertEqual(response.status_code, 302)


class TestSaveCloudSettingsRoute(TestBase):
    """Tests for /save_cloud_settings route"""
    
    @patch('web.routes_requests.CloudService.register_webhook')
    def test_save_cloud_settings_success(self, mock_register):
        """Test saving cloud settings"""
        self.login()
        mock_register.return_value = True
        
        response = self.client.post('/save_cloud_settings', data={
            'cloud_api_key': 'new_key',
            'cloud_movie_handler': 'radarr',
            'cloud_tv_handler': 'sonarr',
            'cloud_webhook_url': 'https://example.com/webhook',
            'cloud_webhook_secret': 'secret123'
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect after save
        
        # Verify settings saved
        settings = Settings.query.first()
        self.assertEqual(settings.cloud_api_key, 'new_key')
        self.assertEqual(settings.cloud_movie_handler, 'radarr')
    
    def test_save_cloud_settings_empty_key(self):
        """Test saving with empty API key disables cloud"""
        self.login()
        response = self.client.post('/save_cloud_settings', data={
            'cloud_api_key': '',
            'cloud_movie_handler': 'radarr'
        })
        
        self.assertEqual(response.status_code, 302)
        
        settings = Settings.query.first()
        self.assertIsNone(settings.cloud_api_key)
        self.assertFalse(settings.cloud_enabled)


class TestApproveRequestRoute(TestBase):
    """Tests for /approve_request/<id> route"""
    
    @patch('web.routes_requests.CloudService.process_item')
    def test_approve_request_success(self, mock_process):
        """Test approving a cloud request"""
        self.login()
        mock_process.return_value = True
        
        # Create test request
        req = CloudRequest(
            cloud_id='test123',
            title='Test Movie',
            media_type='movie',
            tmdb_id=12345,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id
        
        response = self.client.post(f'/approve_request/{req_id}')
        
        self.assertEqual(response.status_code, 302)
        
        # Verify request was processed
        mock_process.assert_called_once()
    
    def test_approve_request_not_found(self):
        """Test approving non-existent request"""
        self.login()
        response = self.client.post('/approve_request/99999')
        self.assertEqual(response.status_code, 404)


class TestDenyRequestRoute(TestBase):
    """Tests for /deny_request/<id> route"""
    
    @patch('web.routes_requests.requests.post')
    @patch('services.CloudService.CloudService.get_cloud_base_url')
    def test_deny_request_success(self, mock_base_url, mock_post):
        """Test denying a cloud request"""
        self.login()
        mock_base_url.return_value = 'https://cloud.example.com'
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # Create test request
        req = CloudRequest(
            cloud_id='test123',
            title='Test Movie',
            media_type='movie',
            tmdb_id=12345,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id
        
        response = self.client.post(f'/deny_request/{req_id}')
        
        self.assertEqual(response.status_code, 302)
        
        # Verify request status changed
        req = CloudRequest.query.get(req_id)
        self.assertEqual(req.status, 'denied')


class TestDeleteRequestRoute(TestBase):
    """Tests for /delete_request/<id> route"""
    
    @patch('web.routes_requests.requests.post')
    @patch('services.CloudService.CloudService.get_cloud_base_url')
    def test_delete_request_success(self, mock_base_url, mock_post):
        """Test deleting a cloud request"""
        self.login()
        mock_base_url.return_value = 'https://cloud.example.com'
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response
        
        # Create test request
        req = CloudRequest(
            cloud_id='test123',
            title='Test Movie',
            media_type='movie',
            tmdb_id=12345,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id
        
        response = self.client.post(f'/delete_request/{req_id}')
        
        self.assertEqual(response.status_code, 302)
        
        # Verify request was deleted
        req = CloudRequest.query.get(req_id)
        self.assertIsNone(req)
        
        # Verify cloud_id was recorded
        deleted = DeletedCloudId.query.filter_by(cloud_id='test123').first()
        self.assertIsNotNone(deleted)
    
    def test_delete_request_records_cloud_id(self):
        """Test delete records cloud_id to prevent re-import"""
        self.login()
        # Create test request
        req = CloudRequest(
            cloud_id='test456',
            title='Test Movie',
            media_type='movie',
            tmdb_id=12345,
            status='pending'
        )
        db.session.add(req)
        db.session.commit()
        req_id = req.id
        
        with patch('web.routes_requests.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response
            
            response = self.client.post(f'/delete_request/{req_id}')
        
        # Verify cloud_id recorded
        deleted = DeletedCloudId.query.filter_by(cloud_id='test456').first()
        self.assertIsNotNone(deleted)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestBlueprintIntegration(unittest.TestCase):
    """Integration tests for blueprint functionality"""
    
    def test_all_routes_registered(self):
        """Test all migrated routes are registered"""
        with app.app_context():
            routes = [rule.rule for rule in app.url_map.iter_rules()]
            
            # Utility routes
            self.assertIn('/trigger_update', routes)
            self.assertIn('/api/cloud/test', routes)
            self.assertIn('/api/settings/autodiscover', routes)
            self.assertIn('/api/plex/metadata', routes)
            
            # Request routes
            self.assertIn('/requests', routes)
            self.assertIn('/requests/settings', routes)
            self.assertIn('/save_cloud_settings', routes)
            # Dynamic routes won't show exact path
            self.assertTrue(any('/approve_request/' in r for r in routes))
            self.assertTrue(any('/deny_request/' in r for r in routes))
            self.assertTrue(any('/delete_request/' in r for r in routes))
    
    def test_blueprints_have_correct_names(self):
        """Test blueprints have correct endpoint names"""
        with app.app_context():
            endpoints = [rule.endpoint for rule in app.url_map.iter_rules()]
            
            # Utility blueprint endpoints
            self.assertIn('web_utility.trigger_update_route', endpoints)
            self.assertIn('web_utility.settings_autodiscover', endpoints)
            self.assertIn('web_utility.plex_metadata_api', endpoints)
            
            # API blueprint endpoints (cloud test moved here from web_utility)
            self.assertIn('api.test_cloud_connection', endpoints)
            
            # Request blueprint endpoints
            self.assertIn('web_requests.requests_page', endpoints)
            self.assertIn('web_requests.requests_settings_page', endpoints)
            self.assertIn('web_requests.save_cloud_settings', endpoints)
            self.assertIn('web_requests.approve_request', endpoints)
            self.assertIn('web_requests.deny_request', endpoints)
            self.assertIn('web_requests.delete_request', endpoints)


if __name__ == '__main__':
    unittest.main()
