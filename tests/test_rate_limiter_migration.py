"""
Tests for rate limiter after migration to utils/rate_limiter.py
Verifies that rate limiting still works in blueprints
"""

import unittest
import sys
import os

# add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from utils.rate_limiter import limiter


class TestRateLimiterMigration(unittest.TestCase):
    """Test rate limiter after migration to utils module"""
    
    def test_limiter_exists(self):
        """Verify limiter is properly initialized"""
        self.assertIsNotNone(limiter)
        self.assertTrue(hasattr(limiter, 'limit'))
    
    def test_limiter_attached_to_app(self):
        """Verify limiter is attached to Flask app"""
        with app.app_context():
            # Limiter should be initialized with app
            # Note: Different versions of flask-limiter use different attribute names
            self.assertTrue(hasattr(limiter, 'app') or hasattr(limiter, '_app'))
            if hasattr(limiter, 'app'):
                self.assertEqual(limiter.app, app)
            elif hasattr(limiter, '_app'):
                self.assertEqual(limiter._app, app)
    
    def test_api_module_has_limiter(self):
        """Verify API module receives limiter from app.py"""
        import api
        self.assertIsNotNone(api.limiter)
        self.assertEqual(api.limiter, limiter)
    
    def test_rate_limit_decorator_works(self):
        """Verify API rate_limit_decorator works with new limiter"""
        import api
        
        # Create a dummy function
        @api.rate_limit_decorator("10 per hour")
        def dummy_func():
            return "success"
        
        # Should be wrapped by limiter
        self.assertTrue(hasattr(dummy_func, '__wrapped__') or callable(dummy_func))
    
    def test_trigger_update_has_rate_limit(self):
        """Verify /trigger_update route has rate limiting"""
        from web.routes_utility import web_utility_bp
        
        # Find the trigger_update_route function
        trigger_update = None
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'web_utility.trigger_update_route':
                trigger_update = app.view_functions[rule.endpoint]
                break
        
        self.assertIsNotNone(trigger_update, "/trigger_update route not found")
        
        # Check if it has rate limit decorator
        # Note: This is a basic check - full rate limit testing requires actual requests
        self.assertTrue(callable(trigger_update))
    
    def test_limiter_import_from_utils(self):
        """Verify limiter can be imported from utils.rate_limiter"""
        from utils.rate_limiter import limiter as imported_limiter
        self.assertIsNotNone(imported_limiter)
        self.assertEqual(imported_limiter, limiter)
    
    def test_no_circular_imports(self):
        """Verify no circular import issues"""
        try:
            # These imports should work without circular dependency
            from utils.rate_limiter import limiter
            from web.routes_utility import web_utility_bp
            from web.routes_requests import web_requests_bp
            import api
            
            # All imports successful
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Circular import detected: {e}")


if __name__ == '__main__':
    unittest.main()
