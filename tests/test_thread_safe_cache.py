"""
Tests for thread-safe RESULTS_CACHE implementation
Verifies that cache operations are safe under concurrent access
"""

import threading
import time
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.cache import (
    get_results_cache,
    set_results_cache,
    clear_results_cache,
    RESULTS_CACHE_LOCK
)


def test_set_and_get_results_cache():
    """Test basic set and get operations"""
    print("Testing set and get operations...")
    user_id = 1
    test_data = {
        'candidates': [{'id': 1, 'title': 'Test Movie'}],
        'next_index': 0
    }
    
    set_results_cache(user_id, test_data)
    result = get_results_cache(user_id)
    
    assert result is not None, "Cache should not be None"
    assert result['candidates'] == test_data['candidates'], "Candidates mismatch"
    assert result['next_index'] == test_data['next_index'], "Next index mismatch"
    print("✓ Set and get operations work correctly")


def test_get_nonexistent_cache():
    """Test getting cache for user that doesn't exist"""
    print("Testing get for nonexistent user...")
    result = get_results_cache(99999)
    assert result is None, "Should return None for nonexistent user"
    print("✓ Returns None for nonexistent user")


def test_clear_results_cache():
    """Test clearing cache for a user"""
    print("Testing clear cache...")
    user_id = 2
    test_data = {'candidates': [], 'next_index': 0}
    
    set_results_cache(user_id, test_data)
    assert get_results_cache(user_id) is not None, "Cache should exist after set"
    
    clear_results_cache(user_id)
    assert get_results_cache(user_id) is None, "Cache should be None after clear"
    print("✓ Clear cache works correctly")


def test_concurrent_writes():
    """Test multiple threads writing to different user caches"""
    print("Testing concurrent writes to different users...")
    num_threads = 10
    threads = []
    
    def write_cache(user_id):
        data = {
            'candidates': [{'id': user_id, 'title': f'Movie {user_id}'}],
            'next_index': user_id
        }
        set_results_cache(user_id, data)
    
    # Start threads
    for i in range(num_threads):
        t = threading.Thread(target=write_cache, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for all threads
    for t in threads:
        t.join()
    
    # Verify all writes succeeded
    for i in range(num_threads):
        cache = get_results_cache(i)
        assert cache is not None, f"Cache for user {i} should exist"
        assert cache['next_index'] == i, f"Next index for user {i} should be {i}"
    
    print("✓ Concurrent writes work correctly")


def test_concurrent_read_write():
    """Test concurrent reads and writes to same user cache"""
    print("Testing concurrent reads and writes...")
    user_id = 100
    num_operations = 50
    results = []
    
    # Initialize cache
    set_results_cache(user_id, {'candidates': [], 'next_index': 0})
    
    def read_cache():
        for _ in range(num_operations):
            result = get_results_cache(user_id)
            results.append(result is not None)
            time.sleep(0.001)
    
    def write_cache():
        for i in range(num_operations):
            data = {'candidates': [], 'next_index': i}
            set_results_cache(user_id, data)
            time.sleep(0.001)
    
    # Start reader and writer threads
    reader = threading.Thread(target=read_cache)
    writer = threading.Thread(target=write_cache)
    
    reader.start()
    writer.start()
    
    reader.join()
    writer.join()
    
    # All reads should have succeeded (no race conditions)
    assert all(results), "All reads should succeed without race conditions"
    print("✓ Concurrent reads and writes work correctly")


def test_lock_is_released():
    """Verify locks are properly released"""
    print("Testing lock release...")
    user_id = 300
    
    # Test get
    set_results_cache(user_id, {'candidates': [], 'next_index': 0})
    get_results_cache(user_id)
    acquired = RESULTS_CACHE_LOCK.acquire(blocking=False)
    if acquired:
        RESULTS_CACHE_LOCK.release()
    assert acquired, "Lock should be released after get"
    
    # Test set
    set_results_cache(user_id, {'candidates': [], 'next_index': 1})
    acquired = RESULTS_CACHE_LOCK.acquire(blocking=False)
    if acquired:
        RESULTS_CACHE_LOCK.release()
    assert acquired, "Lock should be released after set"
    
    # Test clear
    clear_results_cache(user_id)
    acquired = RESULTS_CACHE_LOCK.acquire(blocking=False)
    if acquired:
        RESULTS_CACHE_LOCK.release()
    assert acquired, "Lock should be released after clear"
    
    print("✓ Locks are properly released")


def test_isolated_user_caches():
    """Test that different users have isolated caches"""
    print("Testing user cache isolation...")
    user1_data = {'candidates': [{'id': 1}], 'next_index': 10}
    user2_data = {'candidates': [{'id': 2}], 'next_index': 20}
    
    set_results_cache(1, user1_data)
    set_results_cache(2, user2_data)
    
    # Verify isolation
    cache1 = get_results_cache(1)
    cache2 = get_results_cache(2)
    
    assert cache1['next_index'] == 10, "User 1 next_index should be 10"
    assert cache2['next_index'] == 20, "User 2 next_index should be 20"
    assert cache1['candidates'][0]['id'] == 1, "User 1 candidate id should be 1"
    assert cache2['candidates'][0]['id'] == 2, "User 2 candidate id should be 2"
    
    print("✓ User caches are properly isolated")


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("THREAD-SAFE CACHE TESTS")
    print("="*60 + "\n")
    
    tests = [
        test_set_and_get_results_cache,
        test_get_nonexistent_cache,
        test_clear_results_cache,
        test_concurrent_writes,
        test_concurrent_read_write,
        test_lock_is_released,
        test_isolated_user_caches,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

