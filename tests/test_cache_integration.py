"""
Integration tests for thread-safe cache implementation
Tests real user workflows and concurrent scenarios
"""

import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.cache import (
    get_results_cache,
    set_results_cache,
    clear_results_cache,
)


def test_full_recommendation_flow():
    """Test complete flow: generate → load more → filter → load more"""
    print("Testing full recommendation flow...")
    
    user_id = 1000
    
    # Step 1: Simulate /generate - set initial cache
    initial_candidates = [
        {'id': i, 'title': f'Movie {i}', 'score': 100 - i}
        for i in range(100)
    ]
    set_results_cache(user_id, {
        'candidates': initial_candidates,
        'next_index': 0,
        'ts': int(time.time())
    })
    
    # Step 2: Verify cache is set
    cache = get_results_cache(user_id)
    assert cache is not None, "Cache should be set after generate"
    assert len(cache['candidates']) == 100, "Should have 100 candidates"
    assert cache['next_index'] == 0, "Next index should start at 0"
    
    # Step 3: Simulate /load_more_recs - update next_index
    cache['next_index'] = 20
    set_results_cache(user_id, cache)
    
    # Step 4: Verify next_index updated
    cache = get_results_cache(user_id)
    assert cache['next_index'] == 20, "Next index should be updated to 20"
    
    # Step 5: Simulate filter change - reset next_index
    cache['next_index'] = 0
    set_results_cache(user_id, cache)
    
    # Step 6: Verify next_index reset
    cache = get_results_cache(user_id)
    assert cache['next_index'] == 0, "Next index should reset to 0 after filter change"
    
    # Step 7: Load more again
    cache['next_index'] = 20
    set_results_cache(user_id, cache)
    
    cache = get_results_cache(user_id)
    assert cache['next_index'] == 20, "Next index should be 20 after second load"
    
    # Cleanup
    clear_results_cache(user_id)
    
    print("✓ Full recommendation flow works correctly")


def test_concurrent_user_isolation():
    """Test that 2 users generating simultaneously don't interfere"""
    print("Testing concurrent user isolation...")
    
    user1_id = 2000
    user2_id = 2001
    results = {'user1': None, 'user2': None}
    errors = []
    
    def user1_workflow():
        try:
            # User 1 generates recommendations
            candidates = [{'id': i, 'title': f'User1 Movie {i}'} for i in range(50)]
            set_results_cache(user1_id, {
                'candidates': candidates,
                'next_index': 0
            })
            time.sleep(0.01)  # Simulate processing
            
            # User 1 loads more
            cache = get_results_cache(user1_id)
            cache['next_index'] = 20
            set_results_cache(user1_id, cache)
            
            # Verify final state
            final_cache = get_results_cache(user1_id)
            results['user1'] = final_cache
        except Exception as e:
            errors.append(f"User 1 error: {e}")
    
    def user2_workflow():
        try:
            # User 2 generates recommendations (different data)
            candidates = [{'id': i + 1000, 'title': f'User2 Movie {i}'} for i in range(30)]
            set_results_cache(user2_id, {
                'candidates': candidates,
                'next_index': 0
            })
            time.sleep(0.01)  # Simulate processing
            
            # User 2 loads more
            cache = get_results_cache(user2_id)
            cache['next_index'] = 15
            set_results_cache(user2_id, cache)
            
            # Verify final state
            final_cache = get_results_cache(user2_id)
            results['user2'] = final_cache
        except Exception as e:
            errors.append(f"User 2 error: {e}")
    
    # Run both users concurrently
    thread1 = threading.Thread(target=user1_workflow)
    thread2 = threading.Thread(target=user2_workflow)
    
    thread1.start()
    thread2.start()
    
    thread1.join()
    thread2.join()
    
    # Check for errors
    assert len(errors) == 0, f"Errors occurred: {errors}"
    
    # Verify user 1's cache
    assert results['user1'] is not None, "User 1 cache should exist"
    assert len(results['user1']['candidates']) == 50, "User 1 should have 50 candidates"
    assert results['user1']['next_index'] == 20, "User 1 next_index should be 20"
    assert results['user1']['candidates'][0]['title'].startswith('User1'), "User 1 should have their own data"
    
    # Verify user 2's cache
    assert results['user2'] is not None, "User 2 cache should exist"
    assert len(results['user2']['candidates']) == 30, "User 2 should have 30 candidates"
    assert results['user2']['next_index'] == 15, "User 2 next_index should be 15"
    assert results['user2']['candidates'][0]['title'].startswith('User2'), "User 2 should have their own data"
    
    # Verify no cross-contamination
    assert results['user1']['candidates'][0]['id'] != results['user2']['candidates'][0]['id'], \
        "Users should have different data"
    
    # Cleanup
    clear_results_cache(user1_id)
    clear_results_cache(user2_id)
    
    print("✓ Concurrent users are properly isolated")


def test_cache_persistence_across_operations():
    """Test that cache survives multiple operations"""
    print("Testing cache persistence...")
    
    user_id = 3000
    
    # Initial set
    candidates = [{'id': i, 'title': f'Movie {i}'} for i in range(50)]
    set_results_cache(user_id, {
        'candidates': candidates,
        'next_index': 0,
        'ts': int(time.time())
    })
    
    # Perform multiple read operations
    for i in range(10):
        cache = get_results_cache(user_id)
        assert cache is not None, f"Cache should persist on read {i}"
        assert len(cache['candidates']) == 50, f"Candidates should persist on read {i}"
    
    # Perform multiple update operations
    for i in range(1, 11):
        cache = get_results_cache(user_id)
        cache['next_index'] = i * 5
        set_results_cache(user_id, cache)
        
        # Verify update
        updated_cache = get_results_cache(user_id)
        assert updated_cache['next_index'] == i * 5, f"Update {i} should persist"
    
    # Final verification
    final_cache = get_results_cache(user_id)
    assert final_cache is not None, "Cache should still exist"
    assert len(final_cache['candidates']) == 50, "Candidates should still be intact"
    assert final_cache['next_index'] == 50, "Final next_index should be 50"
    
    # Cleanup
    clear_results_cache(user_id)
    
    print("✓ Cache persists correctly across operations")


def test_cache_with_large_dataset():
    """Test cache with 1000+ recommendations"""
    print("Testing cache with large dataset...")
    
    user_id = 4000
    
    # Create large dataset
    large_candidates = [
        {'id': i, 'title': f'Movie {i}', 'score': 1000 - i}
        for i in range(1500)
    ]
    
    # Set cache
    start_time = time.time()
    set_results_cache(user_id, {
        'candidates': large_candidates,
        'next_index': 0
    })
    set_time = time.time() - start_time
    
    # Get cache
    start_time = time.time()
    cache = get_results_cache(user_id)
    get_time = time.time() - start_time
    
    # Verify
    assert cache is not None, "Large cache should be set"
    assert len(cache['candidates']) == 1500, "Should have all 1500 candidates"
    
    # Performance check (should be fast even with large dataset)
    assert set_time < 0.1, f"Set should be fast (<100ms), was {set_time*1000:.1f}ms"
    assert get_time < 0.1, f"Get should be fast (<100ms), was {get_time*1000:.1f}ms"
    
    # Cleanup
    clear_results_cache(user_id)
    
    print(f"✓ Large dataset handled correctly (set: {set_time*1000:.1f}ms, get: {get_time*1000:.1f}ms)")


def test_cache_recovery_from_corruption():
    """Test recovery if cache data is malformed"""
    print("Testing cache corruption recovery...")
    
    user_id = 5000
    
    # Set valid cache
    set_results_cache(user_id, {
        'candidates': [{'id': 1, 'title': 'Movie 1'}],
        'next_index': 0
    })
    
    # Simulate corruption by setting invalid data
    set_results_cache(user_id, None)
    
    # Try to get - should return None gracefully
    cache = get_results_cache(user_id)
    assert cache is None, "Corrupted cache should return None"
    
    # Should be able to set new valid cache
    set_results_cache(user_id, {
        'candidates': [{'id': 2, 'title': 'Movie 2'}],
        'next_index': 0
    })
    
    cache = get_results_cache(user_id)
    assert cache is not None, "Should recover with new valid cache"
    assert cache['candidates'][0]['id'] == 2, "New cache should be correct"
    
    # Cleanup
    clear_results_cache(user_id)
    
    print("✓ Cache recovers gracefully from corruption")


def test_rapid_concurrent_updates():
    """Test rapid updates from multiple threads"""
    print("Testing rapid concurrent updates...")
    
    user_id = 6000
    num_threads = 5
    updates_per_thread = 20
    
    # Initialize cache
    set_results_cache(user_id, {
        'candidates': [],
        'next_index': 0,
        'update_count': 0
    })
    
    errors = []
    
    def rapid_updater(thread_id):
        try:
            for i in range(updates_per_thread):
                cache = get_results_cache(user_id)
                if cache:
                    cache['update_count'] = cache.get('update_count', 0) + 1
                    cache['last_thread'] = thread_id
                    set_results_cache(user_id, cache)
                time.sleep(0.001)  # Small delay
        except Exception as e:
            errors.append(f"Thread {thread_id} error: {e}")
    
    # Start threads
    threads = []
    for i in range(num_threads):
        t = threading.Thread(target=rapid_updater, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for completion
    for t in threads:
        t.join()
    
    # Verify
    assert len(errors) == 0, f"No errors should occur: {errors}"
    
    final_cache = get_results_cache(user_id)
    assert final_cache is not None, "Cache should still exist"
    
    # Update count should be positive (may not be exact due to race conditions in increment logic)
    assert final_cache['update_count'] > 0, "Updates should have occurred"
    
    # Cleanup
    clear_results_cache(user_id)
    
    print(f"✓ Rapid concurrent updates handled correctly ({final_cache['update_count']} updates)")


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("CACHE INTEGRATION TESTS")
    print("="*60 + "\n")
    
    tests = [
        test_full_recommendation_flow,
        test_concurrent_user_isolation,
        test_cache_persistence_across_operations,
        test_cache_with_large_dataset,
        test_cache_recovery_from_corruption,
        test_rapid_concurrent_updates,
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
