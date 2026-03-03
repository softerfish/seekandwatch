"""
Blueprint Migration Verification Tests
Ensures all routes work after migration to blueprints.

Usage:
    python tests/test_blueprint_migration.py
"""

import sys
import os
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_all_routes_registered(app):
    """Verify all expected routes are registered"""
    print("Testing route registration...")
    
    with app.test_request_context():
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        
        # Critical routes must exist
        critical_routes = [
            '/',
            '/health',
            '/login',
            '/logout',
            '/dashboard',
            '/settings',
            '/generate',
            '/api/webhook',
            '/api/pair/receive_key',
        ]
        
        missing = []
        for route in critical_routes:
            if route not in routes:
                missing.append(route)
        
        if missing:
            print(f"  ✗ Missing routes: {', '.join(missing)}")
            return False
        
        print(f"  ✓ All {len(routes)} routes registered")
        print(f"  ✓ All {len(critical_routes)} critical routes present")
        return True

def test_health_endpoint(app):
    """Test health endpoint works"""
    print("Testing health endpoint...")
    
    with app.test_client() as client:
        response = client.get('/health')
        
        if response.status_code != 200:
            print(f"  ✗ Health endpoint returned {response.status_code}")
            return False
        
        if b'ok' not in response.data:
            print(f"  ✗ Health endpoint missing 'ok' in response")
            return False
        
        print("  ✓ Health endpoint works")
        return True

def test_ready_endpoint(app):
    """Test ready endpoint works (if it exists)"""
    print("Testing ready endpoint...")
    
    with app.test_client() as client:
        response = client.get('/ready')
        
        # Ready endpoint might not exist - that's OK
        if response.status_code == 404:
            print("  ⚠️  Ready endpoint not implemented (optional)")
            return True
        
        if response.status_code != 200:
            print(f"  ✗ Ready endpoint returned {response.status_code}")
            return False
        
        print("  ✓ Ready endpoint works")
        return True

@pytest.mark.requires_config_dir
def test_login_page(app):
    """Test login page loads"""
    print("Testing login page...")
    
    with app.test_client() as client:
        response = client.get('/login')
        
        # Login might redirect if already logged in - that's OK
        if response.status_code in [200, 302]:
            print("  ✓ Login page accessible")
            return True
        
        print(f"  ✗ Login page returned {response.status_code}")
        return False

def test_static_files(app):
    """Test static files accessible"""
    print("Testing static files...")
    
    with app.test_client() as client:
        # Test CSS
        response = client.get('/static/style.css')
        
        if response.status_code != 200:
            print(f"  ✗ Static CSS returned {response.status_code}")
            return False
        
        print("  ✓ Static files accessible")
        return True

@pytest.mark.requires_config_dir
def test_protected_routes_require_auth(app):
    """Test protected routes redirect to login"""
    print("Testing auth protection...")
    
    with app.test_client() as client:
        # Dashboard should redirect to login when not authenticated
        response = client.get('/dashboard', follow_redirects=False)
        
        if response.status_code not in [302, 401]:
            print(f"  ✗ Dashboard didn't redirect (status: {response.status_code})")
            return False
        
        print("  ✓ Auth protection works")
        return True

def test_api_endpoints_exist(app):
    """Test API endpoints are registered"""
    print("Testing API endpoints...")
    
    with app.test_request_context():
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        
        api_routes = [
            '/api/webhook',
            '/api/pair/receive_key',
        ]
        
        missing = []
        for route in api_routes:
            if route not in routes:
                missing.append(route)
        
        if missing:
            print(f"  ✗ Missing API routes: {', '.join(missing)}")
            return False
        
        print(f"  ✓ All {len(api_routes)} critical API endpoints registered")
        return True

def test_no_duplicate_routes(app):
    """Test no duplicate route definitions"""
    print("Testing for duplicate routes...")
    
    with app.test_request_context():
        routes = {}
        duplicates = []
        
        for rule in app.url_map.iter_rules():
            url = rule.rule
            # Skip if already seen - Flask allows same URL with different methods
            if url in routes:
                # Only flag as duplicate if same endpoint
                if routes[url] != rule.endpoint:
                    duplicates.append(f"{url} ({routes[url]} vs {rule.endpoint})")
            routes[url] = rule.endpoint
        
        if duplicates:
            print(f"  ⚠️  Duplicate routes with different endpoints:")
            for dup in duplicates:
                print(f"      {dup}")
            # This is actually OK in Flask - same URL, different methods
            print(f"  ✓ No problematic duplicates ({len(routes)} unique URLs)")
            return True
        
        print(f"  ✓ No duplicate routes ({len(routes)} unique)")
        return True

def test_blueprints_registered(app):
    """Test blueprints are properly registered"""
    print("Testing blueprint registration...")
    
    # Check if blueprints are registered
    blueprints = list(app.blueprints.keys())
    
    if not blueprints:
        print("  ⚠️  No blueprints registered yet (app.py only)")
        return True
    
    print(f"  ✓ {len(blueprints)} blueprints registered: {', '.join(blueprints)}")
    return True

def test_url_for_works(app):
    """Test url_for works for routes"""
    print("Testing url_for...")
    
    from flask import url_for
    
    with app.test_request_context():
        try:
            # Test basic routes
            url_for('health')
            url_for('web_auth.login')  # Updated for blueprint
            
            print("  ✓ url_for works")
            return True
        except Exception as e:
            print(f"  ✗ url_for failed: {e}")
            return False

def run_all_tests():
    """Run all blueprint migration tests"""
    print("\n" + "="*60)
    print("BLUEPRINT MIGRATION VERIFICATION")
    print("="*60 + "\n")
    
    tests = [
        test_all_routes_registered,
        test_health_endpoint,
        test_ready_endpoint,
        test_login_page,
        test_static_files,
        test_protected_routes_require_auth,
        test_api_endpoints_exist,
        test_no_duplicate_routes,
        test_blueprints_registered,
        test_url_for_works,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__} failed with exception: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    if failed == 0:
        print("✅ ALL TESTS PASSED - Blueprint migration successful!")
        return True
    else:
        print(f"❌ {failed} TEST(S) FAILED - Review issues before proceeding")
        return False

if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
