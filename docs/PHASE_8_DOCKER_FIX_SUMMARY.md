# Phase 8 Docker Fix Summary

## Problem

After Phase 8 migration (utils.py -> utils/ package), Docker containers were crashing on startup with import errors. The issue was that old code in `/config` volume mount was overriding the new code from the Docker image.

## Root Cause

The entrypoint.sh script had multiple references to `utils.py` as a file instead of `utils/` as a package directory. This caused:

1. Old `utils.py` being copied during updates
2. Validation checks failing because `utils.py` didn't exist
3. Legacy code paths treating `utils` as a file instead of a directory

## Fixes Applied

### Commit 559b3a1: Remove utils.py from Legacy Code Paths

Updated 7 locations in entrypoint.sh where legacy code still referenced `utils.py`:

1. Line 704: CRITICAL_FILES in legacy layout detection
2. Line 707: for loop in legacy layout detection  
3. Line 745: CRITICAL_FILES in legacy move section
4. Line 748: for loop in legacy move section
5. Line 758: critical file check
6. Line 782: CRITICAL_FILES in cleanup root section
7. Line 784: for loop in cleanup root section

All changed from `utils.py` to `utils` (package directory).

### Previous Fixes (Already Applied)

- Commit 0e1b992: Added missing imports to utils/legacy.py
- Commit 06b8ab8: Updated UPDATE_FILES/UPDATE_DIRS in entrypoint.sh
- Commit 51e4799: Fixed CRITICAL_FILES validation (first occurrence)
- Commit c53c133: Fixed final validation check
- Commit 77b5410: Fixed get_cache_file import location
- Commit b0dc066: Removed circular import

## Testing

Created comprehensive test scripts to verify the fix:

- `scripts/test_phase8_docker.sh` (bash version)
- `scripts/test_phase8_docker.ps1` (PowerShell version)

Both scripts run 10 tests covering:

1. utils/ package structure exists
2. Old utils.py removed from source
3. entrypoint.sh has Phase 8 migration code
4. UPDATE_DIRS includes utils package
5. UPDATE_FILES excludes utils.py
6. utils/legacy.py has correct imports
7. No circular imports
8. Python can import utils package
9. Python can import from utils submodules
10. CRITICAL_FILES treats utils as package (6 occurrences)

All tests pass.

## Docker Build Instructions

To rebuild with the fixes:

```bash
cd /mnt/user/appdata/seek
docker build --no-cache -t seek .
docker rm -f seek
docker run -d --name seek -p 5002:5000 -v /mnt/user/appdata/seek:/config --restart unless-stopped seek
docker logs -f seek
```

The `--no-cache` flag is critical to ensure Docker doesn't use cached layers with the old code.

## What Happens on Startup

1. Entrypoint detects IS_APP_DIR=true (because /config has app files)
2. Compares Docker image version vs installed version
3. If image is newer, updates files from image to /config
4. Phase 8 migration cleanup removes old utils.py if it exists
5. Validates all CRITICAL_FILES exist (including utils/ package)
6. Starts the application

## Verification

After container starts, verify:

```bash
# Check logs for successful startup
docker logs seek

# Should see:
# - "Using /config directly as app directory"
# - "Docker image version: 1.6.6"
# - "✓ App is up to date" or "🔄 UPDATING"
# - "PHASE 8 MIGRATION: Removing old utils.py" (if old file existed)
# - Gunicorn startup messages
# - No ImportError or NameError messages
```

## Files Modified

1. `entrypoint.sh` - 7 additional fixes for legacy code paths
2. `docs/PHASE_8_HOTFIXES.md` - Added Issue 7 documentation
3. `scripts/test_phase8_docker.sh` - New test script (bash)
4. `scripts/test_phase8_docker.ps1` - New test script (PowerShell)

## Status

All Phase 8 Docker migration issues are now resolved. The application should start successfully in Docker containers with both fresh installs and updates from older versions.
