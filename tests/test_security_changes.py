"""quick test to verify security changes didn't break anything"""

import os
import sys

# add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """verify all new imports work"""
    print("\n1. testing imports...")
    
    try:
        # new security modules
        from utils.secure_test_runner import SecureTestRunner
        from utils.webhook_security import WebhookSigner, WebhookRateLimiter
        from utils.migration_helpers import MigrationLock, column_exists, table_exists
        from models_security import WebhookAttempt, LoginAttempt, AccountLockout
        
        # existing modules that import new stuff
        from app import app, db
        from api.routes_webhook import receive_webhook
        
        print("   ✓ all imports successful")
        return True
    except ImportError as e:
        print(f"   ✗ import failed: {e}")
        return False


def test_app_starts():
    """verify app starts without errors"""
    print("\n2. testing app startup...")
    
    try:
        from app import app
        
        with app.app_context():
            # check app is configured
            assert app.config.get('SECRET_KEY'), "secret key not set"
            assert app.config.get('SQLALCHEMY_DATABASE_URI'), "database uri not set"
            
            print("   ✓ app starts successfully")
            return True
    except Exception as e:
        print(f"   ✗ app startup failed: {e}")
        return False


def test_database_tables():
    """verify all tables exist including new security tables"""
    print("\n3. testing database tables...")
    
    try:
        from app import app, db
        from utils.migration_helpers import table_exists
        
        with app.app_context():
            # existing tables
            existing_tables = [
                'user', 'settings', 'blocklist', 'collection_schedule',
                'tmdb_alias', 'system_log', 'cloud_request', 'webhook_log'
            ]
            
            for table in existing_tables:
                if not table_exists(db.engine, table):
                    print(f"   ✗ missing table: {table}")
                    return False
            
            # new security tables
            security_tables = ['webhook_attempt', 'login_attempt', 'account_lockout']
            
            for table in security_tables:
                if not table_exists(db.engine, table):
                    print(f"   ✗ missing security table: {table}")
                    return False
            
            print(f"   ✓ all tables exist ({len(existing_tables)} existing + {len(security_tables)} security)")
            return True
    except Exception as e:
        print(f"   ✗ database check failed: {e}")
        return False


def test_routes_registered():
    """verify all routes still registered"""
    print("\n4. testing route registration...")
    
    try:
        from app import app
        
        with app.app_context():
            # get all registered endpoints
            endpoints = set(app.url_map._rules_by_endpoint.keys())
            
            # critical routes that must exist
            critical_routes = [
                'web_auth.login',
                'web_auth.logout',
                'web_pages.dashboard',
                'web_settings.settings',
                'api.receive_webhook',
                'health'
            ]
            
            missing = []
            for route in critical_routes:
                if route not in endpoints:
                    missing.append(route)
            
            if missing:
                print(f"   ✗ missing routes: {', '.join(missing)}")
                return False
            
            print(f"   ✓ all critical routes registered ({len(endpoints)} total endpoints)")
            return True
    except Exception as e:
        print(f"   ✗ route check failed: {e}")
        return False


def test_blueprints_registered():
    """verify all blueprints still registered"""
    print("\n5. testing blueprint registration...")
    
    try:
        from app import app
        
        # check blueprints
        blueprint_names = [bp.name for bp in app.blueprints.values()]
        
        required_blueprints = ['api', 'web_auth', 'web_settings', 'web_pages', 'web_utility', 'web_requests', 'generate']
        
        missing = []
        for bp in required_blueprints:
            if bp not in blueprint_names:
                missing.append(bp)
        
        if missing:
            print(f"   ✗ missing blueprints: {', '.join(missing)}")
            return False
        
        print(f"   ✓ all blueprints registered ({len(blueprint_names)} total)")
        return True
    except Exception as e:
        print(f"   ✗ blueprint check failed: {e}")
        return False


def test_models_loadable():
    """verify all models can be loaded"""
    print("\n6. testing model loading...")
    
    try:
        from models import (
            User, Settings, Blocklist, CollectionSchedule, TmdbAlias,
            SystemLog, CloudRequest, WebhookLog, RecoveryCode
        )
        from models_security import WebhookAttempt, LoginAttempt, AccountLockout
        
        print("   ✓ all models loadable")
        return True
    except Exception as e:
        print(f"   ✗ model loading failed: {e}")
        return False


def test_secure_test_runner():
    """verify secure test runner works"""
    print("\n7. testing secure test runner...")
    
    try:
        from utils.secure_test_runner import SecureTestRunner
        
        tests_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tests')
        runner = SecureTestRunner(tests_dir)
        
        # should have found some tests
        allowed = runner.get_allowed_tests()
        if not allowed:
            print("   ⚠ warning: no tests found in whitelist")
        
        # test validation
        valid, msg = runner.validate_test_file("../app.py")
        if valid:
            print("   ✗ path traversal not blocked")
            return False
        
        print(f"   ✓ secure test runner works ({len(allowed)} tests whitelisted)")
        return True
    except Exception as e:
        print(f"   ✗ secure test runner failed: {e}")
        return False


def test_webhook_security():
    """verify webhook security works"""
    print("\n8. testing webhook security...")
    
    try:
        from utils.webhook_security import WebhookSigner, WebhookRateLimiter
        import time
        
        # test signing
        secret = "test_secret"
        timestamp = int(time.time())
        body = b'{"test": "data"}'
        
        signature = WebhookSigner.sign_request(secret, timestamp, body)
        valid, msg = WebhookSigner.verify_request(secret, str(timestamp), body, signature)
        
        if not valid:
            print(f"   ✗ signature verification failed: {msg}")
            return False
        
        # test rate limiter (just check it doesn't crash)
        locked, msg = WebhookRateLimiter.is_ip_locked_out("127.0.0.1")
        
        print("   ✓ webhook security works")
        return True
    except Exception as e:
        print(f"   ✗ webhook security failed: {e}")
        return False


def test_migration_helpers():
    """verify migration helpers work"""
    print("\n9. testing migration helpers...")
    
    try:
        from utils.migration_helpers import MigrationLock, column_exists, table_exists
        from app import app, db
        
        with app.app_context():
            # test table check
            exists = table_exists(db.engine, 'user')
            if not exists:
                print("   ✗ table_exists() not working")
                return False
            
            # test column check
            exists = column_exists(db.engine, 'user', 'username')
            if not exists:
                print("   ✗ column_exists() not working")
                return False
            
            print("   ✓ migration helpers work")
            return True
    except Exception as e:
        print(f"   ✗ migration helpers failed: {e}")
        return False


def test_existing_functionality():
    """verify existing functionality still works"""
    print("\n10. testing existing functionality...")
    
    try:
        from app import app
        from flask import url_for
        
        with app.app_context():
            # test url generation (common operation)
            try:
                url = url_for('web_pages.dashboard')
                assert url, "url_for returned empty"
            except Exception as e:
                print(f"   ✗ url_for failed: {e}")
                return False
            
            # test database query (common operation)
            from models import User
            try:
                count = User.query.count()
                # count can be 0, that's fine
            except Exception as e:
                print(f"   ✗ database query failed: {e}")
                return False
            
            print("   ✓ existing functionality works")
            return True
    except Exception as e:
        print(f"   ✗ functionality check failed: {e}")
        return False


def run_all_tests():
    """run all verification tests"""
    print("=" * 70)
    print("security changes verification")
    print("=" * 70)
    
    tests = [
        ("imports", test_imports),
        ("app startup", test_app_starts),
        ("database tables", test_database_tables),
        ("route registration", test_routes_registered),
        ("blueprint registration", test_blueprints_registered),
        ("model loading", test_models_loadable),
        ("secure test runner", test_secure_test_runner),
        ("webhook security", test_webhook_security),
        ("migration helpers", test_migration_helpers),
        ("existing functionality", test_existing_functionality),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n   ✗ test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # summary
    print("\n" + "=" * 70)
    print("test summary")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ pass" if result else "✗ fail"
        print(f"{status}: {name}")
    
    print(f"\ntotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ all checks passed - security changes look good!")
        return True
    else:
        print(f"\n❌ {total - passed} checks failed - review errors above")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
