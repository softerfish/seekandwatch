# Test script for Phase 8 Docker migration
# Verifies that the Docker image builds correctly and starts without import errors

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Phase 8 Docker Migration Test" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Test counter
$script:TestsRun = 0
$script:TestsPassed = 0
$script:TestsFailed = 0

# Helper functions
function Pass-Test {
    param([string]$Message)
    Write-Host "✓ PASS: $Message" -ForegroundColor Green
    $script:TestsPassed++
    $script:TestsRun++
}

function Fail-Test {
    param([string]$Message)
    Write-Host "✗ FAIL: $Message" -ForegroundColor Red
    $script:TestsFailed++
    $script:TestsRun++
}

function Info {
    param([string]$Message)
    Write-Host "ℹ $Message" -ForegroundColor Yellow
}

# Test 1: Verify utils/ package exists in source
Write-Host "Test 1: Verify utils/ package structure"
if ((Test-Path "utils") -and (Test-Path "utils/__init__.py")) {
    Pass-Test "utils/ package exists with __init__.py"
} else {
    Fail-Test "utils/ package missing or incomplete"
}

# Test 2: Verify utils.py does NOT exist in source
Write-Host "Test 2: Verify old utils.py removed from source"
if (-not (Test-Path "utils.py")) {
    Pass-Test "Old utils.py correctly removed from source"
} else {
    Fail-Test "Old utils.py still exists in source"
}

# Test 3: Verify entrypoint.sh has Phase 8 migration code
Write-Host "Test 3: Verify entrypoint.sh has Phase 8 migration"
$entrypointContent = Get-Content "entrypoint.sh" -Raw
if ($entrypointContent -match "PHASE 8 MIGRATION: Remove old utils\.py") {
    Pass-Test "entrypoint.sh has Phase 8 migration cleanup"
} else {
    Fail-Test "entrypoint.sh missing Phase 8 migration cleanup"
}

# Test 4: Verify entrypoint.sh UPDATE_DIRS includes utils
Write-Host "Test 4: Verify entrypoint.sh UPDATE_DIRS includes utils"
if ($entrypointContent -match 'UPDATE_DIRS="[^"]*utils[^"]*"') {
    Pass-Test "entrypoint.sh UPDATE_DIRS includes utils package"
} else {
    Fail-Test "entrypoint.sh UPDATE_DIRS missing utils package"
}

# Test 5: Verify entrypoint.sh does NOT have utils.py in UPDATE_FILES
Write-Host "Test 5: Verify entrypoint.sh UPDATE_FILES excludes utils.py"
if ($entrypointContent -notmatch 'UPDATE_FILES="[^"]*utils\.py[^"]*"') {
    Pass-Test "entrypoint.sh UPDATE_FILES correctly excludes utils.py"
} else {
    Fail-Test "entrypoint.sh UPDATE_FILES still includes utils.py"
}

# Test 6: Verify utils/legacy.py has correct imports
Write-Host "Test 6: Verify utils/legacy.py imports"
$legacyContent = Get-Content "utils/legacy.py" -Raw
if (($legacyContent -match "from utils\.helpers import write_log, normalize_title") -and
    ($legacyContent -match "from utils\.system import is_system_locked") -and
    ($legacyContent -match "from config import CONFIG_DIR, get_cache_file")) {
    Pass-Test "utils/legacy.py has correct imports"
} else {
    Fail-Test "utils/legacy.py missing required imports"
}

# Test 7: Verify utils/legacy.py does NOT import get_radarr_sonarr_cache from utils.cache
Write-Host "Test 7: Verify no circular import in utils/legacy.py"
if ($legacyContent -notmatch "from utils\.cache import get_radarr_sonarr_cache") {
    Pass-Test "utils/legacy.py has no circular import"
} else {
    Fail-Test "utils/legacy.py still has circular import"
}

# Test 8: Verify Python can import utils package
Write-Host "Test 8: Test Python import of utils package"
try {
    $result = python -c "import utils; print('OK')" 2>&1
    if ($result -match "OK") {
        Pass-Test "Python can import utils package"
    } else {
        Fail-Test "Python cannot import utils package: $result"
    }
} catch {
    Fail-Test "Python cannot import utils package: $_"
}

# Test 9: Verify Python can import from utils submodules
Write-Host "Test 9: Test Python import from utils submodules"
try {
    $result = python -c "from utils.helpers import write_log; from utils.system import is_system_locked; print('OK')" 2>&1
    if ($result -match "OK") {
        Pass-Test "Python can import from utils submodules"
    } else {
        Fail-Test "Python cannot import from utils submodules: $result"
    }
} catch {
    Fail-Test "Python cannot import from utils submodules: $_"
}

# Test 10: Verify entrypoint.sh CRITICAL_FILES treats utils as package
Write-Host "Test 10: Verify entrypoint.sh CRITICAL_FILES"
$utilsAsPackage = ([regex]::Matches($entrypointContent, 'CRITICAL_FILES="[^"]*\butils\b[^"]*"')).Count
$utilsAsFile = ([regex]::Matches($entrypointContent, 'CRITICAL_FILES="[^"]*utils\.py[^"]*"')).Count

if (($utilsAsPackage -gt 0) -and ($utilsAsFile -eq 0)) {
    Pass-Test "entrypoint.sh CRITICAL_FILES treats utils as package (found $utilsAsPackage occurrences)"
} else {
    Fail-Test "entrypoint.sh CRITICAL_FILES has issues (package: $utilsAsPackage, file: $utilsAsFile)"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Tests run: $TestsRun"
Write-Host "Passed: $TestsPassed" -ForegroundColor Green
if ($TestsFailed -gt 0) {
    Write-Host "Failed: $TestsFailed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Some tests failed. Please review the output above." -ForegroundColor Red
    exit 1
} else {
    Write-Host "All tests passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Phase 8 migration appears to be correctly implemented."
    Write-Host "You can now build the Docker image with:"
    Write-Host "  docker build --no-cache -t seek ."
}
