"""test security fixes - command injection, webhook auth, sql injection"""

import os
import sys
import time
import hmac
import hashlib
from datetime import datetime, timedelta

# add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_secure_test_runner():
    """test secure test runner validation"""
    print("\ntesting secure test runner...")
    
    try:
        from utils.secure_test_runner import SecureTestRunner
        
        # create test runner
        tests_dir = os.path.join(os.path.dirname(__file__))
        runner = SecureTestRunner(tests_dir)
        
        # test path traversal detection
        valid, msg = runner.validate_test_file("../app.py")
        assert not valid, "should reject path traversal"
        assert "path traversal" in msg.lower()
        
        # test absolute path detection
        valid, msg = runner.validate_test_file("/etc/passwd")
        assert not valid, "should reject absolute paths"
        
        # test whitelist validation
        valid, msg = runner.validate_test_file("fake_test.py")
        assert not valid, "should reject non-whitelisted files"
        assert "whitelist" in msg.lower()
        
        # test symlink detection (if we can create one)
        try:
            test_file = os.path.join(tests_dir, "test_symlink.py")
            if os.path.exists(test_file):
                os.remove(test_file)
            os.symlink(__file__, test_file)
            
            valid, msg = runner.validate_test_file("test_symlink.py")
            os.remove(test_file)
            
            # note: symlink might be in whitelist but should fail integrity check
            if valid:
                print("  warning: symlink passed validation (might be in whitelist)")
        except (OSError, NotImplementedError):
            print("  skipped symlink test (not supported on this platform)")
        
        print("✓ secure test runner validation works")
        return True
        
    except Exception as e:
        print(f"✗ secure test runner test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_webhook_signing():
    """test webhook request signing and verification"""
    print("\ntesting webhook signing...")
    
    try:
        from utils.webhook_security import WebhookSigner
        
        secret = "test_secret_key_12345"
        timestamp = int(time.time())
        body = b'{"event": "test", "data": "hello"}'
        
        # create signature
        signature = WebhookSigner.sign_request(secret, timestamp, body)
        assert signature.startswith("sha256="), "signature should have sha256 prefix"
        
        # verify valid signature
        valid, msg = WebhookSigner.verify_request(secret, str(timestamp), body, signature)
        assert valid, f"should verify valid signature: {msg}"
        
        # test invalid signature
        valid, msg = WebhookSigner.verify_request(secret, str(timestamp), body, "sha256=invalid")
        assert not valid, "should reject invalid signature"
        assert "invalid signature" in msg.lower()
        
        # test expired timestamp
        old_timestamp = timestamp - 400  # 6+ minutes ago
        old_sig = WebhookSigner.sign_request(secret, old_timestamp, body)
        valid, msg = WebhookSigner.verify_request(secret, str(old_timestamp), body, old_sig)
        assert not valid, "should reject expired timestamp"
        assert "timestamp" in msg.lower()
        
        # test wrong secret
        wrong_secret = "wrong_secret"
        valid, msg = WebhookSigner.verify_request(wrong_secret, str(timestamp), body, signature)
        assert not valid, "should reject wrong secret"
        
        print("✓ webhook signing works")
        return True
        
    except Exception as e:
        print(f"✗ webhook signing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_webhook_rate_limiting():
    """test webhook rate limiting and lockout"""
    print("\ntesting webhook rate limiting...")
    
    try:
        from utils.webhook_security import WebhookRateLimiter
        from models import db
        from app import app
        
        with app.app_context():
            test_ip = "192.168.1.100"
            
            # clear any existing attempts
            WebhookRateLimiter.clear_attempts(test_ip)
            
            # should not be locked initially
            locked, msg = WebhookRateLimiter.is_ip_locked_out(test_ip)
            assert not locked, "should not be locked initially"
            
            # log multiple failures
            for i in range(5):
                WebhookRateLimiter.log_attempt(test_ip, False, "test-agent", f"test_failure_{i}")
            
            # should be locked after 5 failures
            locked, msg = WebhookRateLimiter.is_ip_locked_out(test_ip)
            assert locked, "should be locked after 5 failures"
            assert "locked" in msg.lower()
            
            # clear attempts
            WebhookRateLimiter.clear_attempts(test_ip)
            
            # should not be locked after clearing
            locked, msg = WebhookRateLimiter.is_ip_locked_out(test_ip)
            assert not locked, "should not be locked after clearing"
            
            print("✓ webhook rate limiting works")
            return True
        
    except Exception as e:
        print(f"✗ webhook rate limiting test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_migration_helpers():
    """test secure migration helpers"""
    print("\ntesting migration helpers...")
    
    try:
        from utils.migration_helpers import MigrationLock, column_exists, table_exists
        from models import db
        from app import app
        
        with app.app_context():
            # test table existence check
            assert table_exists(db.engine, "user"), "user table should exist"
            assert not table_exists(db.engine, "fake_table_xyz"), "fake table should not exist"
            
            # test column existence check
            assert column_exists(db.engine, "user", "username"), "username column should exist"
            assert not column_exists(db.engine, "user", "fake_column_xyz"), "fake column should not exist"
            
            # test migration lock
            with MigrationLock() as lock:
                assert lock is not None, "lock should be acquired"
            
            print("✓ migration helpers work")
            return True
        
    except Exception as e:
        print(f"✗ migration helpers test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_security_tables_exist():
    """verify security tables were created"""
    print("\ntesting security tables...")
    
    try:
        from utils.migration_helpers import table_exists
        from models import db
        from app import app
        
        with app.app_context():
            # check security tables exist
            assert table_exists(db.engine, "webhook_attempt"), "webhook_attempt table should exist"
            assert table_exists(db.engine, "login_attempt"), "login_attempt table should exist"
            assert table_exists(db.engine, "account_lockout"), "account_lockout table should exist"
            
            print("✓ security tables exist")
            return True
        
    except Exception as e:
        print(f"✗ security tables test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """run all security fix tests"""
    print("=" * 70)
    print("security fixes test suite")
    print("=" * 70)
    
    results = []
    
    # run tests
    results.append(("secure test runner", test_secure_test_runner()))
    results.append(("webhook signing", test_webhook_signing()))
    results.append(("webhook rate limiting", test_webhook_rate_limiting()))
    results.append(("migration helpers", test_migration_helpers()))
    results.append(("security tables", test_security_tables_exist()))
    
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
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
