"""
Tests for Phase 3 helper modules.
Ensures all helpers work correctly before blueprint migration.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_session_helpers():
    """Test session helper functions"""
    print("Testing session helpers...")
    
    from utils.session_helpers import (
        SessionKeys, get_media_type, set_media_type,
        get_selected_titles, set_selected_titles,
        get_genre_filter, set_genre_filter,
        get_keywords, set_keywords,
        get_min_year, set_min_year,
        get_min_rating, set_min_rating,
        clear_filters
    )
    
    # Test SessionKeys class exists
    assert hasattr(SessionKeys, 'MEDIA_TYPE')
    assert hasattr(SessionKeys, 'SELECTED_TITLES')
    assert hasattr(SessionKeys, 'GENRE_FILTER')
    
    # Test all functions are callable
    assert callable(get_media_type)
    assert callable(set_media_type)
    assert callable(get_selected_titles)
    assert callable(set_selected_titles)
    assert callable(get_genre_filter)
    assert callable(set_genre_filter)
    assert callable(get_keywords)
    assert callable(set_keywords)
    assert callable(get_min_year)
    assert callable(set_min_year)
    assert callable(get_min_rating)
    assert callable(set_min_rating)
    assert callable(clear_filters)
    
    print("✓ Session helpers structure validated")
    return True

def test_user_helpers():
    """Test user helper functions"""
    print("Testing user helpers...")
    
    from utils.user_helpers import (
        get_current_user_settings,
        get_current_user_id,
        is_user_authenticated,
        is_user_admin,
        require_settings
    )
    
    # Test all functions are callable
    assert callable(get_current_user_settings)
    assert callable(get_current_user_id)
    assert callable(is_user_authenticated)
    assert callable(is_user_admin)
    assert callable(require_settings)
    
    print("✓ User helpers structure validated")
    return True

def test_cache_service():
    """Test cache service"""
    print("Testing cache service...")
    
    from services.cache_service import (
        CacheService,
        get_cache_service,
        set_results_cache,
        get_results_cache,
        clear_results_cache
    )
    
    # Test CacheService class
    cache = CacheService()
    assert hasattr(cache, 'set')
    assert hasattr(cache, 'get')
    assert hasattr(cache, 'delete')
    assert hasattr(cache, 'clear_user')
    assert hasattr(cache, 'cleanup_expired')
    assert hasattr(cache, 'get_size')
    
    # Test basic operations
    cache.set(1, 'test', 'value', ttl_seconds=60)
    assert cache.get(1, 'test') == 'value'
    assert cache.get_size() >= 1
    
    cache.delete(1, 'test')
    assert cache.get(1, 'test') is None
    
    # Test convenience functions
    assert callable(get_cache_service)
    assert callable(set_results_cache)
    assert callable(get_results_cache)
    assert callable(clear_results_cache)
    
    print("✓ Cache service validated")
    return True

def test_template_helpers():
    """Test template helpers"""
    print("Testing template helpers...")
    
    from utils.template_helpers import (
        get_base_context,
        render_with_context,
        get_settings_context
    )
    
    # Test all functions are callable
    assert callable(get_base_context)
    assert callable(render_with_context)
    assert callable(get_settings_context)
    
    print("✓ Template helpers structure validated")
    return True

def test_db_helpers():
    """Test database helpers"""
    print("Testing database helpers...")
    
    from utils.db_helpers import (
        safe_commit,
        safe_add,
        safe_delete,
        safe_query,
        safe_get_or_create
    )
    
    # Test all functions are callable
    assert callable(safe_commit)
    assert callable(safe_add)
    assert callable(safe_delete)
    assert callable(safe_query)
    assert callable(safe_get_or_create)
    
    print("✓ Database helpers structure validated")
    return True

def test_message_helpers():
    """Test message helpers"""
    print("Testing message helpers...")
    
    from utils.message_helpers import (
        flash_success,
        flash_error,
        flash_warning,
        flash_info,
        flash_settings_required,
        flash_plex_error,
        flash_tmdb_error,
        flash_unauthorized
    )
    
    # Test all functions are callable
    assert callable(flash_success)
    assert callable(flash_error)
    assert callable(flash_warning)
    assert callable(flash_info)
    assert callable(flash_settings_required)
    assert callable(flash_plex_error)
    assert callable(flash_tmdb_error)
    assert callable(flash_unauthorized)
    
    print("✓ Message helpers structure validated")
    return True

def test_all_imports():
    """Test that all helpers can be imported without errors"""
    print("Testing all imports...")
    
    try:
        import utils.session_helpers
        import utils.user_helpers
        import services.cache_service
        import utils.template_helpers
        import utils.db_helpers
        import utils.message_helpers
        print("✓ All helper modules import successfully")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False

def run_all_tests():
    """Run all Phase 3 helper tests"""
    print("\n" + "="*60)
    print("PHASE 3 HELPER MODULES TEST SUITE")
    print("="*60 + "\n")
    
    tests = [
        ("Import Test", test_all_imports),
        ("Session Helpers", test_session_helpers),
        ("User Helpers", test_user_helpers),
        ("Cache Service", test_cache_service),
        ("Template Helpers", test_template_helpers),
        ("Database Helpers", test_db_helpers),
        ("Message Helpers", test_message_helpers),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            print(f"\n[{name}]")
            if test_func():
                passed += 1
                print(f"✓ {name} PASSED")
            else:
                failed += 1
                print(f"✗ {name} FAILED")
        except Exception as e:
            failed += 1
            print(f"✗ {name} FAILED: {e}")
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    if failed == 0:
        print("✓ ALL TESTS PASSED - Ready for Phase 3.2 blueprint migration!")
        return True
    else:
        print("✗ SOME TESTS FAILED - Fix issues before proceeding")
        return False

if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
