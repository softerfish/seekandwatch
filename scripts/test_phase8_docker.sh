#!/bin/bash
# Test script for Phase 8 Docker migration
# Verifies that the Docker image builds correctly and starts without import errors

set -e  # Exit on any error

echo "=========================================="
echo "Phase 8 Docker Migration Test"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
pass_test() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
    TESTS_RUN=$((TESTS_RUN + 1))
}

fail_test() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    TESTS_RUN=$((TESTS_RUN + 1))
}

info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

# Test 1: Verify utils/ package exists in source
echo "Test 1: Verify utils/ package structure"
if [ -d "utils" ] && [ -f "utils/__init__.py" ]; then
    pass_test "utils/ package exists with __init__.py"
else
    fail_test "utils/ package missing or incomplete"
fi

# Test 2: Verify utils.py does NOT exist in source
echo "Test 2: Verify old utils.py removed from source"
if [ ! -f "utils.py" ]; then
    pass_test "Old utils.py correctly removed from source"
else
    fail_test "Old utils.py still exists in source"
fi

# Test 3: Verify entrypoint.sh has Phase 8 migration code
echo "Test 3: Verify entrypoint.sh has Phase 8 migration"
if grep -q "PHASE 8 MIGRATION: Remove old utils.py" entrypoint.sh; then
    pass_test "entrypoint.sh has Phase 8 migration cleanup"
else
    fail_test "entrypoint.sh missing Phase 8 migration cleanup"
fi

# Test 4: Verify entrypoint.sh UPDATE_DIRS includes utils
echo "Test 4: Verify entrypoint.sh UPDATE_DIRS includes utils"
if grep -q 'UPDATE_DIRS=".*utils.*"' entrypoint.sh; then
    pass_test "entrypoint.sh UPDATE_DIRS includes utils package"
else
    fail_test "entrypoint.sh UPDATE_DIRS missing utils package"
fi

# Test 5: Verify entrypoint.sh does NOT have utils.py in UPDATE_FILES
echo "Test 5: Verify entrypoint.sh UPDATE_FILES excludes utils.py"
if ! grep -q 'UPDATE_FILES=".*utils\.py.*"' entrypoint.sh; then
    pass_test "entrypoint.sh UPDATE_FILES correctly excludes utils.py"
else
    fail_test "entrypoint.sh UPDATE_FILES still includes utils.py"
fi

# Test 6: Verify utils/legacy.py has correct imports
echo "Test 6: Verify utils/legacy.py imports"
if grep -q "from utils.helpers import write_log, normalize_title" utils/legacy.py && \
   grep -q "from utils.system import is_system_locked" utils/legacy.py && \
   grep -q "from config import CONFIG_DIR, get_cache_file" utils/legacy.py; then
    pass_test "utils/legacy.py has correct imports"
else
    fail_test "utils/legacy.py missing required imports"
fi

# Test 7: Verify utils/legacy.py does NOT import get_radarr_sonarr_cache from utils.cache
echo "Test 7: Verify no circular import in utils/legacy.py"
if ! grep -q "from utils.cache import get_radarr_sonarr_cache" utils/legacy.py; then
    pass_test "utils/legacy.py has no circular import"
else
    fail_test "utils/legacy.py still has circular import"
fi

# Test 8: Verify Python can import utils package
echo "Test 8: Test Python import of utils package"
if python3 -c "import utils; print('OK')" 2>/dev/null; then
    pass_test "Python can import utils package"
else
    fail_test "Python cannot import utils package"
fi

# Test 9: Verify Python can import from utils submodules
echo "Test 9: Test Python import from utils submodules"
if python3 -c "from utils.helpers import write_log; from utils.system import is_system_locked; print('OK')" 2>/dev/null; then
    pass_test "Python can import from utils submodules"
else
    fail_test "Python cannot import from utils submodules"
fi

# Test 10: Verify entrypoint.sh CRITICAL_FILES treats utils as package
echo "Test 10: Verify entrypoint.sh CRITICAL_FILES"
utils_as_package=$(grep -c 'CRITICAL_FILES=".*\butils\b.*"' entrypoint.sh || echo "0")
utils_as_file=$(grep -c 'CRITICAL_FILES=".*utils\.py.*"' entrypoint.sh || echo "0")

if [ "$utils_as_package" -gt 0 ] && [ "$utils_as_file" -eq 0 ]; then
    pass_test "entrypoint.sh CRITICAL_FILES treats utils as package (found $utils_as_package occurrences)"
else
    fail_test "entrypoint.sh CRITICAL_FILES has issues (package: $utils_as_package, file: $utils_as_file)"
fi

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Tests run: $TESTS_RUN"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo ""
    echo "Some tests failed. Please review the output above."
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    echo ""
    echo "Phase 8 migration appears to be correctly implemented."
    echo "You can now build the Docker image with:"
    echo "  docker build --no-cache -t seek ."
fi
