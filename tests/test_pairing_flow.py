"""
tests for pairing flow - ensures routes exist, return correct responses, and flow works end-to-end
"""

import pytest
import sys
import os

# add parent directory to path for Docker environment
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import url_for
from models import Settings
from datetime import datetime, timedelta


class TestPairingRoutes:
    """test pairing route existence and basic responses"""
    
    def test_pair_start_route_exists(self, client, auth_user):
        """pair start endpoint should exist and require auth"""
        # without auth should redirect
        resp = client.post('/api/pair/start')
        assert resp.status_code in [302, 401]
        
        # with auth should work (may fail for other reasons but not 404)
        auth_user.login()
        resp = client.post('/api/pair/start', json={})
        assert resp.status_code != 404
    
    def test_pair_status_route_exists(self, client, auth_user):
        """pair status endpoint should exist and require auth"""
        # without auth should redirect
        resp = client.get('/api/pair/status')
        assert resp.status_code in [302, 401]
        
        # with auth should work
        auth_user.login()
        resp = client.get('/api/pair/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'paired' in data
        assert isinstance(data['paired'], bool)
    
    def test_pair_receive_key_route_exists(self, client):
        """pair receive key endpoint should exist (public, no auth)"""
        resp = client.post('/api/pair/receive_key', json={})
        # should return 400 (missing data) not 404
        assert resp.status_code in [400, 401]
    
    def test_pair_status_returns_false_without_key(self, client, auth_user, db_session):
        """pair status should return paired=false when no api key"""
        auth_user.login()
        
        # clear api key
        settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
        if settings:
            settings.cloud_api_key = None
            db_session.commit()
        
        resp = client.get('/api/pair/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['paired'] is False
    
    def test_pair_status_returns_true_with_key(self, client, auth_user, db_session):
        """pair status should return paired=true when api key exists"""
        auth_user.login()
        
        # set api key
        settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
        if not settings:
            settings = Settings(user_id=auth_user.user.id)
            db_session.add(settings)
        
        settings.cloud_api_key = 'test_key_123'
        db_session.commit()
        
        resp = client.get('/api/pair/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['paired'] is True


class TestCloudTestRoute:
    """test cloud connection test route"""
    
    def test_cloud_test_route_exists(self, client, auth_user):
        """cloud test endpoint should exist"""
        auth_user.login()
        resp = client.post('/api/cloud/test', json={})
        # should return 400 (no key) not 404
        assert resp.status_code in [200, 400]
        assert resp.status_code != 404
    
    def test_cloud_test_returns_400_without_key(self, client, auth_user, db_session):
        """cloud test should return 400 when no api key provided"""
        auth_user.login()
        
        # clear api key
        settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
        if settings:
            settings.cloud_api_key = None
            db_session.commit()
        
        resp = client.post('/api/cloud/test', json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'message' in data or 'error' in data


class TestTunnelRoutes:
    """test tunnel management routes"""
    
    def test_tunnel_status_route_exists(self, client, auth_user):
        """tunnel status endpoint should exist"""
        auth_user.login()
        resp = client.get('/api/tunnel/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'success' in data
    
    def test_tunnel_enable_route_exists(self, client, auth_user):
        """tunnel enable endpoint should exist"""
        auth_user.login()
        resp = client.post('/api/tunnel/enable', json={})
        # may fail but should not 404
        assert resp.status_code != 404
    
    def test_tunnel_disable_route_exists(self, client, auth_user):
        """tunnel disable endpoint should exist"""
        auth_user.login()
        resp = client.post('/api/tunnel/disable', json={})
        # may fail but should not 404
        assert resp.status_code != 404


class TestBlueprintRegistration:
    """test that all api routes are properly registered"""
    
    def test_no_duplicate_endpoints(self, app):
        """check for duplicate endpoint registrations"""
        endpoints = {}
        for rule in app.url_map.iter_rules():
            if rule.endpoint in endpoints:
                # same endpoint registered twice can cause issues
                if endpoints[rule.endpoint] != str(rule):
                    pytest.fail(f"Duplicate endpoint: {rule.endpoint} registered at {endpoints[rule.endpoint]} and {rule}")
            endpoints[rule.endpoint] = str(rule)
    
    def test_api_routes_use_api_blueprint(self, app):
        """all /api/* routes should use api blueprint"""
        for rule in app.url_map.iter_rules():
            if str(rule).startswith('/api/'):
                # endpoint should start with 'api.'
                assert rule.endpoint.startswith('api.'), f"Route {rule} should use api blueprint but has endpoint {rule.endpoint}"


class TestPairingFlowIntegration:
    """test the complete pairing flow"""
    
    def test_pairing_flow_sequence(self, client, auth_user, db_session):
        """test complete pairing sequence"""
        auth_user.login()
        
        # clear existing pairing data
        settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
        if settings:
            settings.cloud_api_key = None
            settings.pairing_token = None
            settings.pairing_token_expires = None
            db_session.commit()
        
        # check initial status (should be unpaired)
        resp = client.get('/api/pair/status')
        assert resp.get_json()['paired'] is False
        
        # start pairing (may fail due to tunnel but should not 404)
        resp = client.post('/api/pair/start', json={})
        assert resp.status_code != 404
        
        # if pairing started successfully, token should be set
        if resp.status_code == 200:
            settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
            assert settings.pairing_token is not None
            assert settings.pairing_token_expires is not None
            
            # simulate receiving key from cloud
            token = settings.pairing_token
            resp = client.post('/api/pair/receive_key', json={
                'token': token,
                'api_key': 'test_api_key_from_cloud'
            })
            
            # should succeed
            assert resp.status_code == 200
            
            # check status now shows paired
            resp = client.get('/api/pair/status')
            assert resp.get_json()['paired'] is True
            
            # verify key was saved
            settings = Settings.query.filter_by(user_id=auth_user.user.id).first()
            assert settings.cloud_api_key == 'test_api_key_from_cloud'
            assert settings.pairing_token is None  # token cleared after use


@pytest.fixture
def auth_user(client, db_session):
    """fixture providing authenticated user helper"""
    from models import User
    from werkzeug.security import generate_password_hash
    
    class AuthUser:
        def __init__(self):
            self.user = User(
                username='testuser',
                email='test@example.com',
                password_hash=generate_password_hash('testpass123')
            )
            db_session.add(self.user)
            db_session.commit()
            
            # create settings
            settings = Settings(user_id=self.user.id)
            db_session.add(settings)
            db_session.commit()
        
        def login(self):
            with client:
                client.post('/login', data={
                    'username': 'testuser',
                    'password': 'testpass123'
                }, follow_redirects=True)
    
    return AuthUser()
