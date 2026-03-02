#!/bin/bash
# Automated Docker install/update testing for Phase 8 migration
# Tests both fresh installs and updates from old versions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_BASE_DIR="/tmp/seekandwatch_test_$$"
ERRORS_FOUND=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ERRORS_FOUND=$((ERRORS_FOUND + 1))
}

cleanup_test() {
    local test_name=$1
    log_info "Cleaning up test: $test_name"
    docker rm -f "seek_test_${test_name}" 2>/dev/null || true
    rm -rf "${TEST_BASE_DIR}/${test_name}" 2>/dev/null || true
}

check_container_health() {
    local container_name=$1
    local max_wait=30
    local waited=0
    
    log_info "Waiting for container to start..."
    
    while [ $waited -lt $max_wait ]; do
        if docker logs "$container_name" 2>&1 | grep -q "Booting worker with pid"; then
            sleep 2  # Give it a moment to fully boot
            
            # Check if it crashed
            if docker logs "$container_name" 2>&1 | grep -q "Worker failed to boot"; then
                log_error "Container crashed during boot"
                docker logs "$container_name" 2>&1 | tail -50
                return 1
            fi
            
            # Check for import errors
            if docker logs "$container_name" 2>&1 | grep -q "ImportError\|ModuleNotFoundError\|NameError"; then
                log_error "Import error detected"
                docker logs "$container_name" 2>&1 | grep -A 5 "Error"
                return 1
            fi
            
            log_info "Container started successfully"
            return 0
        fi
        
        sleep 1
        waited=$((waited + 1))
    done
    
    log_error "Container failed to start within ${max_wait}s"
    docker logs "$container_name" 2>&1 | tail -50
    return 1
}

# Test 1: Fresh install with empty config
test_fresh_install() {
    local test_name="fresh_install"
    log_info "========================================="
    log_info "TEST: Fresh Install (Empty Config)"
    log_info "========================================="
    
    cleanup_test "$test_name"
    mkdir -p "${TEST_BASE_DIR}/${test_name}"
    
    docker run -d \
        --name "seek_test_${test_name}" \
        -v "${TEST_BASE_DIR}/${test_name}:/config" \
        seek:latest
    
    if check_container_health "seek_test_${test_name}"; then
        log_info "✓ Fresh install test PASSED"
    else
        log_error "✗ Fresh install test FAILED"
    fi
    
    cleanup_test "$test_name"
}

# Test 2: Install with app directory mount (IS_APP_DIR=true)
test_app_dir_mount() {
    local test_name="app_dir_mount"
    log_info "========================================="
    log_info "TEST: App Directory Mount"
    log_info "========================================="
    
    cleanup_test "$test_name"
    mkdir -p "${TEST_BASE_DIR}/${test_name}"
    
    # Copy app files to config (simulates mounting app dir as /config)
    cp -r "$PROJECT_ROOT"/* "${TEST_BASE_DIR}/${test_name}/" 2>/dev/null || true
    
    docker run -d \
        --name "seek_test_${test_name}" \
        -v "${TEST_BASE_DIR}/${test_name}:/config" \
        seek:latest
    
    if check_container_health "seek_test_${test_name}"; then
        # Check that utils/ package exists, not utils.py
        if docker exec "seek_test_${test_name}" test -d /config/utils && \
           docker exec "seek_test_${test_name}" test -f /config/utils/__init__.py && \
           ! docker exec "seek_test_${test_name}" test -f /config/utils.py; then
            log_info "✓ App directory mount test PASSED (utils/ package present, utils.py absent)"
        else
            log_error "✗ App directory mount test FAILED (wrong utils structure)"
        fi
    else
        log_error "✗ App directory mount test FAILED (container didn't start)"
    fi
    
    cleanup_test "$test_name"
}

# Test 3: Update from old version with utils.py
test_update_with_old_utils() {
    local test_name="update_old_utils"
    log_info "========================================="
    log_info "TEST: Update from Old Version (with utils.py)"
    log_info "========================================="
    
    cleanup_test "$test_name"
    mkdir -p "${TEST_BASE_DIR}/${test_name}"
    
    # Create a fake old utils.py
    cat > "${TEST_BASE_DIR}/${test_name}/utils.py" << 'EOF'
# Old monolithic utils.py file
def old_function():
    pass
EOF
    
    # Create minimal database
    touch "${TEST_BASE_DIR}/${test_name}/seekandwatch.db"
    
    docker run -d \
        --name "seek_test_${test_name}" \
        -v "${TEST_BASE_DIR}/${test_name}:/config" \
        seek:latest
    
    sleep 5  # Give migration time to run
    
    if check_container_health "seek_test_${test_name}"; then
        # Check that old utils.py was removed/backed up
        if ! docker exec "seek_test_${test_name}" test -f /config/utils.py; then
            log_info "✓ Update test PASSED (old utils.py removed)"
        else
            log_error "✗ Update test FAILED (old utils.py still present)"
        fi
        
        # Check that backup was created
        if docker exec "seek_test_${test_name}" test -f /config/.migration_backups/utils.py.pre-phase8; then
            log_info "✓ Backup created successfully"
        else
            log_warn "⚠ Backup not found (may not be critical)"
        fi
    else
        log_error "✗ Update test FAILED (container didn't start)"
    fi
    
    cleanup_test "$test_name"
}

# Test 4: Update with nested app/app structure
test_nested_structure() {
    local test_name="nested_structure"
    log_info "========================================="
    log_info "TEST: Nested app/app Structure"
    log_info "========================================="
    
    cleanup_test "$test_name"
    mkdir -p "${TEST_BASE_DIR}/${test_name}/app/app"
    
    # Create nested structure with old utils.py
    cat > "${TEST_BASE_DIR}/${test_name}/app/app/utils.py" << 'EOF'
# Nested old utils.py
def nested_function():
    pass
EOF
    
    touch "${TEST_BASE_DIR}/${test_name}/seekandwatch.db"
    
    docker run -d \
        --name "seek_test_${test_name}" \
        -v "${TEST_BASE_DIR}/${test_name}:/config" \
        seek:latest
    
    sleep 5
    
    if check_container_health "seek_test_${test_name}"; then
        log_info "✓ Nested structure test PASSED"
    else
        log_error "✗ Nested structure test FAILED"
    fi
    
    cleanup_test "$test_name"
}

# Test 5: Check Python imports work
test_python_imports() {
    local test_name="python_imports"
    log_info "========================================="
    log_info "TEST: Python Import Validation"
    log_info "========================================="
    
    cleanup_test "$test_name"
    mkdir -p "${TEST_BASE_DIR}/${test_name}"
    
    docker run -d \
        --name "seek_test_${test_name}" \
        -v "${TEST_BASE_DIR}/${test_name}:/config" \
        seek:latest
    
    sleep 5
    
    if check_container_health "seek_test_${test_name}"; then
        # Test critical imports
        if docker exec "seek_test_${test_name}" python3 -c "
from utils import *
from utils.legacy import sync_plex_library
from utils.helpers import write_log, normalize_title
from utils.system import is_system_locked, set_system_lock, remove_system_lock
from utils.cache import get_radarr_sonarr_cache
from config import get_cache_file
print('All imports successful')
" 2>&1 | grep -q "All imports successful"; then
            log_info "✓ Python imports test PASSED"
        else
            log_error "✗ Python imports test FAILED"
            docker exec "seek_test_${test_name}" python3 -c "from utils import *" 2>&1 || true
        fi
    else
        log_error "✗ Python imports test FAILED (container didn't start)"
    fi
    
    cleanup_test "$test_name"
}

# Main execution
main() {
    log_info "Starting Docker scenario tests..."
    log_info "Project root: $PROJECT_ROOT"
    log_info "Test directory: $TEST_BASE_DIR"
    
    # Build the image first
    log_info "Building Docker image..."
    cd "$PROJECT_ROOT"
    docker build -t seek:latest . > /dev/null 2>&1
    
    if [ $? -ne 0 ]; then
        log_error "Failed to build Docker image"
        exit 1
    fi
    
    log_info "Docker image built successfully"
    echo ""
    
    # Run tests
    test_fresh_install
    echo ""
    
    test_app_dir_mount
    echo ""
    
    test_update_with_old_utils
    echo ""
    
    test_nested_structure
    echo ""
    
    test_python_imports
    echo ""
    
    # Summary
    log_info "========================================="
    log_info "TEST SUMMARY"
    log_info "========================================="
    
    if [ $ERRORS_FOUND -eq 0 ]; then
        log_info "✓ All tests PASSED!"
        exit 0
    else
        log_error "✗ Found $ERRORS_FOUND error(s)"
        exit 1
    fi
}

# Cleanup on exit
trap "rm -rf $TEST_BASE_DIR" EXIT

main "$@"
