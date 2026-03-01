"""Test pairing routes are registered and working"""
import pytest
from flask import Flask


def test_pairing_routes_exist(app):
    """Verify pairing routes are registered in the app"""
    with app.app_context():
        # Get all registered routes
        routes = {rule.rule: rule.endpoint for rule in app.url_map.iter_rules()}
        
        # Check that pairing routes exist
        assert '/api/pair/start' in routes, "Pairing start route not registered"
        assert '/api/pair/receive_key' in routes, "Pairing receive_key route not registered"
        
        # Verify they're on the api blueprint
        assert routes['/api/pair/start'].startswith('api.'), f"pair/start route has wrong endpoint: {routes['/api/pair/start']}"
        assert routes['/api/pair/receive_key'].startswith('api.'), f"pair/receive_key route has wrong endpoint: {routes['/api/pair/receive_key']}"


def test_routes_pair_module_imported():
    """Verify routes_pair module is imported in api package"""
    from api import api_bp
    
    # Check that routes_pair functions are accessible
    try:
        from api import routes_pair
        assert hasattr(routes_pair, 'pair_start'), "pair_start function not found in routes_pair"
        assert hasattr(routes_pair, 'pair_receive_key'), "pair_receive_key function not found in routes_pair"
        assert hasattr(routes_pair, 'cloud_test'), "cloud_test function not found in routes_pair"
    except ImportError as e:
        pytest.fail(f"routes_pair module not imported: {e}")


def test_api_init_imports_routes_pair():
    """Verify api/__init__.py imports routes_pair"""
    import api
    
    # Read the api/__init__.py file to verify import
    import os
    init_file = os.path.join(os.path.dirname(api.__file__), '__init__.py')
    
    with open(init_file, 'r') as f:
        content = f.read()
    
    # Check that routes_pair is in the import statement
    assert 'routes_pair' in content, "routes_pair not found in api/__init__.py imports"
    
    # More specific check - look for the actual import line
    import_lines = [line for line in content.split('\n') if 'from api import' in line and 'routes_' in line]
    
    found = False
    for line in import_lines:
        if 'routes_pair' in line and not line.strip().startswith('#'):
            found = True
            break
    
    assert found, f"routes_pair not in active import statement. Found: {import_lines}"


def test_pairing_routes_have_correct_methods(app):
    """Verify pairing routes accept correct HTTP methods"""
    with app.app_context():
        rules = {rule.rule: rule for rule in app.url_map.iter_rules()}
        
        # pair/start should accept POST
        pair_start = rules.get('/api/pair/start')
        assert pair_start is not None, "pair/start route not found"
        assert 'POST' in pair_start.methods, "pair/start should accept POST"
        
        # pair/receive_key should accept POST
        pair_receive = rules.get('/api/pair/receive_key')
        assert pair_receive is not None, "pair/receive_key route not found"
        assert 'POST' in pair_receive.methods, "pair/receive_key should accept POST"


def test_no_duplicate_pairing_routes_in_routes_main():
    """Verify pairing routes are NOT duplicated in routes_main.py"""
    from api import routes_main
    import inspect
    
    # Get source code of routes_main
    source = inspect.getsource(routes_main)
    
    # Check that pairing routes are NOT defined in routes_main
    # (they should only be in routes_pair)
    assert 'def pair_start(' not in source, "pair_start should not be in routes_main.py (should be in routes_pair.py)"
    assert 'def pair_receive_key(' not in source, "pair_receive_key should not be in routes_main.py (should be in routes_pair.py)"


@pytest.fixture
def app():
    """Create app instance for testing"""
    from app import app
    return app
