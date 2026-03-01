# Tests Directory

One-click tests for SeekAndWatch application.

---

## Quick Start

Run all tests with one command:

```bash
python tests/run_all_tests.py
```

---

## Individual Tests

Run a specific test:

```bash
python tests/test_csrf_tokens.py
python tests/test_critical_functions.py
python tests/test_helpers.py
# ... etc
```

---

## Available Tests

### Security Tests
- `test_csrf_tokens.py` - Ensures all POST/PUT/DELETE requests have CSRF tokens
- `test_import_safety.py` - Validates safe imports and module loading

### Code Quality Tests
- `test_critical_functions.py` - Tests core application functions
- `test_helpers.py` - Tests utility helper functions
- `test_validators.py` - Tests input validation functions
- `test_integrity.py` - Tests data integrity

### Service Tests
- `test_media_service.py` - Tests media service functionality
- `test_plex_service.py` - Tests Plex integration
- `test_tmdb_service.py` - Tests TMDB API integration

### System Tests
- `test_system.py` - Tests system-level functionality
- `test_cache.py` - Tests caching mechanisms
- `test_unraid_compatibility.py` - Tests Unraid compatibility

### Phase 3 Tests
- `test_url_contracts.py` - Ensures URLs remain unchanged during refactoring
- `test_critical_fixes.py` - Validates critical bug fixes

---

## Test Output

### Success
```
[+] All tests passed!
14/14 tests passed
```

### Failure
```
[X] 1 test(s) failed
13/14 tests passed
```

---

## Adding New Tests

1. Create a new file: `tests/test_your_feature.py`
2. Add test functions or a main block
3. Run `python tests/run_all_tests.py` to verify

### Template

```python
#!/usr/bin/env python3
"""
Description of what this test does.
"""

def test_something():
    """Test description."""
    assert True, "Test failed"

if __name__ == '__main__':
    import sys
    try:
        test_something()
        print("✓ All tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"✗ Test failed: {e}")
        sys.exit(1)
```

---

## CI/CD Integration

Add to your CI pipeline:

```yaml
- name: Run Tests
  run: python tests/run_all_tests.py
```

---

## Notes

- Tests are designed to run without pytest (but work with pytest too)
- Tests run in isolation and don't require a running server
- Some tests may require database access (will skip if unavailable)
- Tests are fast - entire suite runs in seconds

---

## Troubleshooting

### Import Errors
If you see import errors, make sure you're running from the project root:
```bash
cd /path/to/seekandwatch
python tests/run_all_tests.py
```

### Database Errors
Some tests require database access. If tests fail due to database issues, check your database configuration.

### Module Not Found
If a test requires a specific module, install it:
```bash
pip install -r requirements.txt
```

---

## Test Coverage

Current coverage:
- Security: CSRF tokens, imports
- Core functionality: helpers, validators, services
- Integrations: Plex, TMDB
- System: cache, compatibility
- Refactoring safety: URL contracts, critical fixes

---

**Last Updated:** 2026-02-27


---

## Phase 3.2E & 3.2F Tests (NEW)

### test_phase3_2e_2f_routes.py ⭐

**Purpose:** Test utility and cloud request routes migrated in Phase 3.2E & 3.2F

**Coverage:**
- 10 migrated routes
- 23 unit tests
- Success and error cases
- Authentication requirements
- Integration tests

**Routes Tested:**
1. `/trigger_update` (POST) - System updater
2. `/api/cloud/test` (POST) - Cloud connection test
3. `/api/settings/autodiscover` (POST) - Service autodiscovery
4. `/api/plex/metadata` (GET) - Plex metadata
5. `/requests` (GET) - Requests page redirect
6. `/requests/settings` (GET) - Requests settings
7. `/save_cloud_settings` (POST) - Save cloud settings
8. `/approve_request/<id>` (POST) - Approve request
9. `/deny_request/<id>` (POST) - Deny request
10. `/delete_request/<id>` (POST) - Delete request

**Run:**
```bash
python tests/test_phase3_2e_2f_routes.py
# or
pytest tests/test_phase3_2e_2f_routes.py -v
```

---

### test_rate_limiter_migration.py ⭐

**Purpose:** Test rate limiter after migration to utils/rate_limiter.py

**Coverage:**
- Limiter initialization
- App attachment
- API module integration
- Decorator functionality
- Circular import prevention
- 7 comprehensive tests

**What It Tests:**
- ✅ Limiter exists and is initialized
- ✅ Limiter attached to Flask app
- ✅ API module receives limiter
- ✅ Rate limit decorator works
- ✅ Routes have rate limiting
- ✅ Import from utils works
- ✅ No circular imports

**Run:**
```bash
python tests/test_rate_limiter_migration.py
# or
pytest tests/test_rate_limiter_migration.py -v
```

---

## Test Inventory

For a complete list of all tests, see:
- `tests/TEST_INVENTORY.md` - Complete test inventory with descriptions

---

## Running All Tests

### Quick Run
```bash
# Run all tests
python tests/run_all_tests.py
```

### With Pytest
```bash
# Run all tests with verbose output
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov

# Run specific phase tests
pytest tests/test_phase3*.py -v

# Run new Phase 3.2E/F tests only
pytest tests/test_phase3_2e_2f_routes.py tests/test_rate_limiter_migration.py -v
```

---

## Test Statistics

**Total Test Files:** 22  
**Total Tests:** 100+  
**Coverage:** ~90%

**By Phase:**
- Phase 0: 4 test files ✅
- Phase 1: 1 test file ✅
- Phase 2: 6 test files ✅
- Phase 3: 7 test files ✅ (including 2 new)
- Deployment: 1 test file ✅
- Verification: 2 scripts ✅

---

## Recent Additions (2026-02-27)

### Phase 3.2E & 3.2F Testing
- ✅ Added `test_phase3_2e_2f_routes.py` (23 tests)
- ✅ Enhanced `test_rate_limiter_migration.py` (7 tests)
- ✅ 100% coverage for migrated routes
- ✅ Comprehensive documentation added

**Documentation:**
- `docs/PHASE_3_2E_2F_TESTING_GUIDE.md` - Complete testing guide
- `tests/TEST_INVENTORY.md` - Test inventory
- `docs/BLUEPRINT_MIGRATION_GUIDE.md` - Updated with testing patterns

---

## References

- `TEST_INVENTORY.md` - Complete test inventory
- `docs/PHASE_3_2E_2F_TESTING_GUIDE.md` - Comprehensive testing guide
- `docs/BLUEPRINT_MIGRATION_GUIDE.md` - Blueprint testing patterns
- `TESTING_GUIDE.md` - General testing guide

---

**Last Updated:** Phase 3.2E & 3.2F completion (2026-02-27)


## Critical Route Tests

### Pairing Routes Test
`test_pairing_routes.py` - Ensures pairing functionality remains intact

This test prevents accidental breakage of the pairing feature by verifying:
- `/api/pair/start` and `/api/pair/receive_key` routes are registered
- `routes_pair` module is properly imported in `api/__init__.py`
- Routes are not duplicated in other modules
- Routes have correct HTTP methods

**Why this matters:** The pairing routes were accidentally broken during troubleshooting when the import was removed from `api/__init__.py`. This test catches that specific issue.

**Run this test:**
```bash
pytest tests/test_pairing_routes.py -v
```

**Quick verification script:**
```bash
python scripts/verify_pairing_routes.py
```

This script runs without pytest and gives immediate feedback on pairing route configuration.
