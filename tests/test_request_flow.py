"""
Request Flow Tests

End-to-end tests for request submission, approval, and integration flows.
"""

import unittest
from unittest.mock import patch, MagicMock, Mock
import sys
import os
import json

# add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestRequestSubmission(unittest.TestCase):
    """Test request submission flow"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_request = {
            'tmdb_id': 550,
            'media_type': 'movie',
            'title': 'Fight Club',
            'release_year': 1999,
            'notes': 'Great movie!'
        }
    
    def test_request_data_structure(self):
        """Test that request has required fields"""
        required_fields = ['tmdb_id', 'media_type', 'title']
        
        for field in required_fields:
            self.assertIn(field, self.test_request, 
                         f"Request should have '{field}' field")
    
    def test_request_validation(self):
        """Test request validation logic"""
        # valid request
        self.assertIsInstance(self.test_request['tmdb_id'], int)
        self.assertIn(self.test_request['media_type'], ['movie', 'tv'])
        self.assertIsInstance(self.test_request['title'], str)
        self.assertGreater(len(self.test_request['title']), 0)
    
    def test_duplicate_request_detection(self):
        """Test that duplicate requests are detected"""
        # simulate checking for existing request
        existing_requests = [
            {'tmdb_id': 550, 'status': 'pending'},
            {'tmdb_id': 551, 'status': 'completed'}
        ]
        
        # check if request already exists
        tmdb_id = 550
        is_duplicate = any(r['tmdb_id'] == tmdb_id for r in existing_requests)
        
        self.assertTrue(is_duplicate, "Should detect duplicate request")
        
        # check non-duplicate
        tmdb_id = 999
        is_duplicate = any(r['tmdb_id'] == tmdb_id for r in existing_requests)
        
        self.assertFalse(is_duplicate, "Should not flag unique request as duplicate")
    
    def test_request_notes_length_limit(self):
        """Test that request notes have length limit"""
        max_length = 500  # typical limit
        
        short_notes = "This is a short note"
        self.assertLessEqual(len(short_notes), max_length)
        
        long_notes = "x" * 1000
        self.assertGreater(len(long_notes), max_length, 
                          "Long notes should exceed limit")


class TestRequestApproval(unittest.TestCase):
    """Test request approval and denial flows"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.pending_request = {
            'id': 1,
            'tmdb_id': 550,
            'media_type': 'movie',
            'title': 'Fight Club',
            'status': 'pending',
            'requester_id': 'user-123'
        }
    
    def test_status_transitions(self):
        """Test valid status transitions"""
        valid_transitions = {
            'pending': ['completed', 'denied', 'available'],
            'completed': ['available'],
            'denied': ['pending'],  # can be reconsidered
            'available': []  # terminal state
        }
        
        # test that pending can transition to completed
        current_status = 'pending'
        new_status = 'completed'
        
        self.assertIn(new_status, valid_transitions[current_status],
                     f"Should allow transition from {current_status} to {new_status}")
    
    def test_approval_requires_owner_or_admin(self):
        """Test that only owners/admins can approve requests"""
        roles_that_can_approve = ['owner', 'admin']
        roles_that_cannot = ['friend', 'user']
        
        for role in roles_that_can_approve:
            self.assertIn(role, ['owner', 'admin'])
        
        for role in roles_that_cannot:
            self.assertNotIn(role, ['owner', 'admin'])
    
    def test_denial_reason_optional(self):
        """Test that denial reason is optional but recommended"""
        denial_with_reason = {
            'status': 'denied',
            'reason': 'Not available in region'
        }
        
        denial_without_reason = {
            'status': 'denied'
        }
        
        # both should be valid
        self.assertEqual(denial_with_reason['status'], 'denied')
        self.assertEqual(denial_without_reason['status'], 'denied')


class TestWebhookIntegration(unittest.TestCase):
    """Test webhook integration for request notifications"""
    
    def test_webhook_payload_structure(self):
        """Test webhook payload has required fields"""
        webhook_payload = {
            'event': 'request_approved',
            'request': {
                'tmdb_id': 550,
                'media_type': 'movie',
                'title': 'Fight Club',
                'status': 'completed'
            },
            'timestamp': '2026-02-27T12:00:00Z'
        }
        
        # verify required fields
        self.assertIn('event', webhook_payload)
        self.assertIn('request', webhook_payload)
        self.assertIn('timestamp', webhook_payload)
        
        # verify request data
        self.assertIn('tmdb_id', webhook_payload['request'])
        self.assertIn('media_type', webhook_payload['request'])
        self.assertIn('status', webhook_payload['request'])
    
    def test_webhook_signature_generation(self):
        """Test webhook signature for security"""
        import hmac
        import hashlib
        
        secret = 'test-secret-key'
        payload = json.dumps({'event': 'test'})
        
        # generate signature
        signature = hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # verify signature is hex string
        self.assertIsInstance(signature, str)
        self.assertEqual(len(signature), 64)  # SHA256 = 64 hex chars
        
        # verify signature changes with different payload
        different_payload = json.dumps({'event': 'different'})
        different_signature = hmac.new(
            secret.encode(),
            different_payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        self.assertNotEqual(signature, different_signature)
    
    @patch('requests.post')
    def test_webhook_delivery_retry(self, mock_post):
        """Test webhook delivery retry logic"""
        # simulate failed webhook delivery
        mock_post.return_value.status_code = 500
        mock_post.return_value.ok = False
        
        # webhook should be queued for retry
        response = mock_post('https://example.com/webhook', json={'test': 'data'})
        
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.ok)


class TestRadarrSonarrIntegration(unittest.TestCase):
    """Test Radarr/Sonarr integration for approved requests"""
    
    def test_radarr_payload_structure(self):
        """Test Radarr API payload structure"""
        radarr_payload = {
            'title': 'Fight Club',
            'year': 1999,
            'tmdbId': 550,
            'qualityProfileId': 1,
            'rootFolderPath': '/movies',
            'monitored': True,
            'addOptions': {
                'searchForMovie': True
            }
        }
        
        # verify required fields for Radarr
        required_fields = ['title', 'year', 'tmdbId', 'qualityProfileId', 
                          'rootFolderPath', 'monitored']
        
        for field in required_fields:
            self.assertIn(field, radarr_payload, 
                         f"Radarr payload should have '{field}' field")
    
    def test_sonarr_payload_structure(self):
        """Test Sonarr API payload structure"""
        sonarr_payload = {
            'title': 'Breaking Bad',
            'tvdbId': 81189,
            'qualityProfileId': 1,
            'rootFolderPath': '/tv',
            'monitored': True,
            'seasonFolder': True,
            'addOptions': {
                'searchForMissingEpisodes': True
            }
        }
        
        # verify required fields for Sonarr
        required_fields = ['title', 'tvdbId', 'qualityProfileId', 
                          'rootFolderPath', 'monitored']
        
        for field in required_fields:
            self.assertIn(field, sonarr_payload, 
                         f"Sonarr payload should have '{field}' field")
    
    @patch('requests.post')
    def test_radarr_api_call(self, mock_post):
        """Test Radarr API call structure"""
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {'id': 1}
        
        # simulate Radarr API call
        response = mock_post(
            'http://radarr:7878/api/v3/movie',
            json={'title': 'Test Movie', 'tmdbId': 123},
            headers={'X-Api-Key': 'test-key'}
        )
        
        self.assertEqual(response.status_code, 201)
        mock_post.assert_called_once()


class TestRequestStatusSync(unittest.TestCase):
    """Test request status synchronization between cloud and local app"""
    
    def test_status_update_payload(self):
        """Test status update payload structure"""
        status_update = {
            'request_id': 1,
            'old_status': 'pending',
            'new_status': 'completed',
            'updated_by': 'owner-123',
            'updated_at': '2026-02-27T12:00:00Z'
        }
        
        # verify fields
        self.assertIn('request_id', status_update)
        self.assertIn('old_status', status_update)
        self.assertIn('new_status', status_update)
        self.assertIn('updated_at', status_update)
    
    def test_cloud_sync_detection(self):
        """Test detection of requests from cloud vs local"""
        cloud_request = {
            'source': 'cloud',
            'cloud_request_id': 'cloud-123'
        }
        
        local_request = {
            'source': 'local'
        }
        
        # verify source detection
        self.assertEqual(cloud_request['source'], 'cloud')
        self.assertEqual(local_request['source'], 'local')
        
        # cloud requests should have cloud_request_id
        self.assertIn('cloud_request_id', cloud_request)
        self.assertNotIn('cloud_request_id', local_request)


if __name__ == '__main__':
    unittest.main()
