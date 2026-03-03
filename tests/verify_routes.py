#!/usr/bin/env python3
"""
Route Verification Script for Phase 3
Verifies all routes are registered and accessible
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def verify_routes():
    """Verify all expected routes exist in the app"""
    
    print("=" * 80)
    print("PHASE 3: ROUTE VERIFICATION")
    print("=" * 80)
    print()
    
    try:
        from app import app
        
        # Get all registered routes
        routes = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                routes.append({
                    'endpoint': rule.endpoint,
                    'methods': ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'})),
                    'path': str(rule)
                })
        
        # Sort by path
        routes.sort(key=lambda x: x['path'])
        
        print(f"✓ App loaded successfully")
        print(f"✓ Found {len(routes)} routes")
        print()
        
        # Expected routes (all 57 routes from app.py)
        expected_routes = {
            # Web Routes - Auth (5)
            '/': ['GET'],
            '/login': ['GET', 'POST'],
            '/register': ['GET', 'POST'],
            '/logout': ['GET'],
            '/reset_password': ['GET', 'POST'],
            
            # Web Routes - Pages (13)
            '/welcome_codes': ['GET'],
            '/welcome_codes_done': ['POST'],
            '/dashboard': ['GET'],
            '/review': ['GET'],
            '/playlists': ['GET'],
            '/settings': ['GET', 'POST'],
            '/logs': ['GET'],
            '/webhook_logs': ['GET'],
            '/kometa': ['GET'],
            '/support': ['GET'],
            '/calendar': ['GET'],
            '/delete_profile': ['POST'],
            '/requests_settings': ['GET'],
            
            # Web Routes - Media (4)
            '/results': ['GET'],
            '/media': ['GET'],
            '/builder': ['GET'],
            '/blocklist': ['GET'],
            
            # Static Routes (2)
            '/img/custom_posters/<path:filename>': ['GET'],
            '/img/public_posters': ['GET'],
            
            # API Routes - Collections (3)
            '/api/run_collection': ['POST'],
            '/api/collections': ['GET'],
            '/api/delete_collection': ['POST'],
            
            # API Routes - Requests (5)
            '/api/request': ['POST'],
            '/api/get_requests': ['GET'],
            '/api/approve_request/<int:req_id>': ['POST'],
            '/api/deny_request/<int:req_id>': ['POST'],
            '/api/delete_request/<int:req_id>': ['DELETE'],
            
            # API Routes - Settings (6)
            '/api/settings': ['GET', 'POST'],
            '/api/test_plex': ['POST'],
            '/api/test_tmdb': ['POST'],
            '/api/test_radarr': ['POST'],
            '/api/test_sonarr': ['POST'],
            '/api/autodiscover': ['POST'],
            
            # API Routes - Media (3)
            '/tmdb_search_proxy': ['GET'],
            '/get_metadata/<media_type>/<int:tmdb_id>': ['GET'],
            '/load_more_recs': ['GET'],
            
            # API Routes - Admin (4)
            '/api/logs': ['GET'],
            '/api/reset_alias_db': ['POST'],
            '/api/test_cloud': ['POST'],
            '/api/save_cloud_settings': ['POST'],
            
            # System Routes (3)
            '/health': ['GET'],
            '/api/csrf-token': ['GET'],
            '/requests': ['GET'],
            
            # Already Separated Routes (from Phase 1 & 2)
            '/api/webhook': ['POST'],
            '/api/pair/receive_key': ['POST'],
            # Tunnel routes (multiple)
            # Monitoring routes (multiple)
        }
        
        # Check each expected route
        print("Checking Expected Routes:")
        print("-" * 80)
        
        missing_routes = []
        found_routes = []
        
        for expected_path, expected_methods in expected_routes.items():
            # Find matching route (handle path parameters)
            found = False
            for route in routes:
                # Simple path matching (exact or with parameters)
                if route['path'] == expected_path or \
                   (expected_path.replace('<', '').replace('>', '') in route['path']):
                    found = True
                    found_routes.append(expected_path)
                    
                    # Check methods
                    route_methods = route['methods'].split(',')
                    missing_methods = set(expected_methods) - set(route_methods)
                    
                    if missing_methods:
                        print(f"⚠ {expected_path}: Missing methods {missing_methods}")
                    else:
                        print(f"✓ {expected_path}: {route['methods']}")
                    break
            
            if not found:
                missing_routes.append(expected_path)
                print(f"✗ {expected_path}: NOT FOUND")
        
        print()
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total Expected Routes: {len(expected_routes)}")
        print(f"Found Routes: {len(found_routes)}")
        print(f"Missing Routes: {len(missing_routes)}")
        print()
        
        if missing_routes:
            print("Missing Routes:")
            for route in missing_routes:
                print(f"  - {route}")
            print()
        
        # Show all registered routes
        print("All Registered Routes:")
        print("-" * 80)
        for route in routes:
            print(f"{route['path']:50} {route['methods']:20} {route['endpoint']}")
        
        print()
        print("=" * 80)
        
        if missing_routes:
            print("❌ VERIFICATION FAILED: Some routes are missing")
            return False
        else:
            print("✅ VERIFICATION PASSED: All expected routes found")
            return True
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = verify_routes()
    sys.exit(0 if success else 1)
