#!/usr/bin/env python3
"""
Master test runner - runs all tests in the tests/ directory.
Usage: python tests/run_all_tests.py
"""

import sys
import importlib.util
from pathlib import Path


def run_test_file(test_file):
    """Run a single test file."""
    print(f"\n{'='*60}")
    print(f"Running: {test_file.name}")
    print('='*60)
    
    try:
        # Import and run the test module
        spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # If module has a main block, it will run automatically
        return True
    except SystemExit as e:
        if e.code != 0:
            print(f"❌ {test_file.name} failed with exit code {e.code}")
            return False
        return True
    except Exception as e:
        print(f"❌ {test_file.name} failed with error: {e}")
        return False


def main():
    """Run all test files."""
    tests_dir = Path('tests')
    
    if not tests_dir.exists():
        print("❌ Tests directory not found")
        return 1
    
    # Find all test files
    test_files = sorted(tests_dir.glob('test_*.py'))
    
    if not test_files:
        print("⚠️  No test files found")
        return 0
    
    print(f"Found {len(test_files)} test files")
    
    results = {}
    for test_file in test_files:
        results[test_file.name] = run_test_file(test_file)
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print('='*60)
    
    passed = sum(1 for r in results.values() if r)
    failed = len(results) - passed
    
    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        symbol = "[+]" if result else "[X]"
        print(f"{symbol} {status}: {test_name}")
    
    print(f"\n{passed}/{len(results)} tests passed")
    
    if failed > 0:
        print(f"\n[X] {failed} test(s) failed")
        return 1
    else:
        print("\n[+] All tests passed!")
        return 0


if __name__ == '__main__':
    sys.exit(main())
