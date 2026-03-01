"""
Phase 2 Verification Script

Comprehensive verification of all Phase 2 modules.
Checks imports, functions, backward compatibility, and more.
"""

import sys
import os
import importlib

# Add parent directory to path so we can import from utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def print_result(test_name, passed, message=""):
    """Print test result"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status}: {test_name}")
    if message:
        print(f"    {message}")


def verify_module_exists(module_path):
    """Verify a module can be imported"""
    try:
        importlib.import_module(module_path)
        return True, None
    except ImportError as e:
        return False, str(e)


def verify_function_exists(module_path, function_name):
    """Verify a function exists in a module"""
    try:
        module = importlib.import_module(module_path)
        return hasattr(module, function_name) and callable(getattr(module, function_name))
    except Exception as e:
        return False


def verify_file_exists(filepath):
    """Verify a file exists"""
    return os.path.exists(filepath)


def main():
    """Run all verification checks"""
    print_header("PHASE 2 VERIFICATION")
    print("\nVerifying all Phase 2 modules and functions...\n")
    
    total_tests = 0
    passed_tests = 0
    
    # ========================================================================
    # Module 1: utils/helpers.py
    # ========================================================================
    print_header("Module 1: utils/helpers.py")
    
    # Check module exists
    total_tests += 1
    success, error = verify_module_exists("utils.helpers")
    passed_tests += 1 if success else 0
    print_result("Module imports", success, error if not success else "")
    
    # Check functions
    functions = ["write_log", "normalize_title", "_sanitize_log_message", "_write_log_internal"]
    for func in functions:
        total_tests += 1
        success = verify_function_exists("utils.helpers", func)
        passed_tests += 1 if success else 0
        print_result(f"Function '{func}' exists", success)
    
    # Check test file
    total_tests += 1
    success = verify_file_exists("tests/test_helpers.py")
    passed_tests += 1 if success else 0
    print_result("Test file exists", success)
    
    # ========================================================================
    # Module 2: utils/system.py
    # ========================================================================
    print_header("Module 2: utils/system.py")
    
    # Check module exists
    total_tests += 1
    success, error = verify_module_exists("utils.system")
    passed_tests += 1 if success else 0
    print_result("Module imports", success, error if not success else "")
    
    # Check functions
    functions = ["is_system_locked", "set_system_lock", "remove_system_lock", 
                 "get_lock_status", "reset_stuck_locks"]
    for func in functions:
        total_tests += 1
        success = verify_function_exists("utils.system", func)
        passed_tests += 1 if success else 0
        print_result(f"Function '{func}' exists", success)
    
    # Check test file
    total_tests += 1
    success = verify_file_exists("tests/test_system.py")
    passed_tests += 1 if success else 0
    print_result("Test file exists", success)
    
    # ========================================================================
    # Module 3: utils/cache.py
    # ========================================================================
    print_header("Module 3: utils/cache.py")
    
    # Check module exists
    total_tests += 1
    success, error = verify_module_exists("utils.cache")
    passed_tests += 1 if success else 0
    print_result("Module imports", success, error if not success else "")
    
    # Check functions
    functions = ["load_results_cache", "save_results_cache", "load_history_cache",
                 "save_history_cache", "get_history_cache", "set_history_cache",
                 "get_tmdb_rec_cache", "set_tmdb_rec_cache", "score_recommendation",
                 "diverse_sample"]
    for func in functions:
        total_tests += 1
        success = verify_function_exists("utils.cache", func)
        passed_tests += 1 if success else 0
        print_result(f"Function '{func}' exists", success)
    
    # Check test file
    total_tests += 1
    success = verify_file_exists("tests/test_cache.py")
    passed_tests += 1 if success else 0
    print_result("Test file exists", success, "TODO: Create test file" if not success else "")
    
    # ========================================================================
    # Module 4: utils/validators.py
    # ========================================================================
    print_header("Module 4: utils/validators.py")
    
    # Check module exists
    total_tests += 1
    success, error = verify_module_exists("utils.validators")
    passed_tests += 1 if success else 0
    print_result("Module imports", success, error if not success else "")
    
    # Check functions
    functions = ["get_session_filters", "validate_url", "validate_url_safety", "validate_path"]
    for func in functions:
        total_tests += 1
        success = verify_function_exists("utils.validators", func)
        passed_tests += 1 if success else 0
        print_result(f"Function '{func}' exists", success)
    
    # Check test file
    total_tests += 1
    success = verify_file_exists("tests/test_validators.py")
    passed_tests += 1 if success else 0
    print_result("Test file exists", success, "TODO: Create test file" if not success else "")
    
    # ========================================================================
    # Backward Compatibility
    # ========================================================================
    print_header("Backward Compatibility")
    
    # Check that old imports still work (from utils)
    old_imports = [
        ("utils", "write_log"),
        ("utils", "normalize_title"),
        ("utils", "is_system_locked"),
        ("utils", "set_system_lock"),
        ("utils", "remove_system_lock"),
    ]
    
    for module, func in old_imports:
        total_tests += 1
        try:
            mod = importlib.import_module(module)
            success = hasattr(mod, func)
            passed_tests += 1 if success else 0
            print_result(f"Old import: from {module} import {func}", success)
        except Exception as e:
            print_result(f"Old import: from {module} import {func}", False, str(e))
    
    # ========================================================================
    # Feature Flags
    # ========================================================================
    print_header("Feature Flags")
    
    # Check feature flags exist
    try:
        from utils.feature_flags import FeatureFlags
        flags_to_check = [
            "NEW_HELPERS",
            "NEW_SYSTEM_UTILS",
            "NEW_CACHE_SYSTEM",
            "NEW_VALIDATORS",
        ]
        
        for flag_name in flags_to_check:
            total_tests += 1
            success = hasattr(FeatureFlags, flag_name)
            passed_tests += 1 if success else 0
            print_result(f"Feature flag '{flag_name}' exists", success)
    except Exception as e:
        print_result("Feature flags module", False, str(e))
    
    # ========================================================================
    # Documentation
    # ========================================================================
    print_header("Documentation")
    
    docs = [
        "PHASE_2_PROGRESS.md",
        "PHASE_2_MODULES_COMPLETE.md",
    ]
    
    for doc in docs:
        total_tests += 1
        success = verify_file_exists(doc)
        passed_tests += 1 if success else 0
        print_result(f"Documentation '{doc}' exists", success)
    
    # ========================================================================
    # Code Quality Checks
    # ========================================================================
    print_header("Code Quality")
    
    # Check for docstrings
    modules_to_check = [
        "utils.helpers",
        "utils.system",
        "utils.cache",
        "utils.validators",
    ]
    
    for module_path in modules_to_check:
        total_tests += 1
        try:
            module = importlib.import_module(module_path)
            has_docstring = module.__doc__ is not None and len(module.__doc__.strip()) > 0
            passed_tests += 1 if has_docstring else 0
            print_result(f"Module '{module_path}' has docstring", has_docstring)
        except Exception as e:
            print_result(f"Module '{module_path}' has docstring", False, str(e))
    
    # ========================================================================
    # Summary
    # ========================================================================
    print_header("VERIFICATION SUMMARY")
    
    percentage = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\nTotal Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {percentage:.1f}%")
    
    if percentage == 100:
        print("\n[SUCCESS] ALL CHECKS PASSED!")
        print("Phase 2 modules are ready for integration.")
        return 0
    elif percentage >= 80:
        print("\n[WARNING] MOST CHECKS PASSED")
        print(f"Some issues need attention ({total_tests - passed_tests} failures).")
        return 1
    else:
        print("\n[ERROR] MANY CHECKS FAILED")
        print("Phase 2 modules need significant work.")
        return 2


if __name__ == "__main__":
    sys.exit(main())

