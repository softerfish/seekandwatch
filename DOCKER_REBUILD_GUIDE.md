# Docker Rebuild Guide - Phase 8 Fixes

## Quick Rebuild Commands

```bash
cd /mnt/user/appdata/seek
docker build --no-cache -t seek .
docker rm -f seek
docker run -d --name seek -p 5002:5000 -v /mnt/user/appdata/seek:/config --restart unless-stopped seek
docker logs -f seek
```

## What to Look For in Logs

### Success Indicators
```
Starting SeekAndWatch...
User ID: 1000
Group ID: 1000
Using /config directly as app directory
Docker image version: 1.6.6
✓ App is up to date (v1.6.6)
PHASE 8 MIGRATION: Removing old utils.py (now using utils/ package)
✓ Old utils.py removed (backup saved to .migration_backups/)
Starting gunicorn
Booting worker with pid: XX
```

### Failure Indicators (Should NOT See These)
```
ImportError: cannot import name 'get_radarr_sonarr_cache' from 'utils.cache'
NameError: name 'is_system_locked' is not defined
WARNING: utils.py missing from /config
CRITICAL: Missing required file utils.py
Worker failed to boot
```

## If Build Fails

1. Make sure you used `--no-cache` flag
2. Check that you're in the correct directory (`/mnt/user/appdata/seek`)
3. Verify the source code has the latest commits:
   ```bash
   git log --oneline -5
   # Should show:
   # bd02be0 docs: add Phase 8 Docker fix summary
   # 41595e6 test: add Phase 8 Docker migration validation scripts
   # 8db25c3 docs: add Issue 7 to Phase 8 hotfixes documentation
   # 559b3a1 fix: remove all utils.py references from entrypoint.sh legacy code paths
   ```

## If Container Crashes on Startup

The old `/config` directory has stale code. Two options:

### Option 1: Clean Start (Recommended for Testing)
```bash
# Backup your database first
cp /mnt/user/appdata/seek/seekandwatch.db ~/seekandwatch.db.backup

# Remove old config (will be recreated from image)
docker rm -f seek
rm -rf /mnt/user/appdata/seek/*

# Restore just the database
cp ~/seekandwatch.db.backup /mnt/user/appdata/seek/seekandwatch.db

# Run container (will seed fresh files from image)
docker run -d --name seek -p 5002:5000 -v /mnt/user/appdata/seek:/config --restart unless-stopped seek
```

### Option 2: Manual Cleanup (Keeps Everything)
```bash
# Stop container
docker rm -f seek

# Remove old utils files
rm -f /mnt/user/appdata/seek/utils.py
rm -f /mnt/user/appdata/seek/utils_cleaned.py
rm -f /mnt/user/appdata/seek/utils_old_backup.py

# Remove old utils package if it has bad imports
rm -rf /mnt/user/appdata/seek/utils/

# Start container (entrypoint will copy fresh utils/ from image)
docker run -d --name seek -p 5002:5000 -v /mnt/user/appdata/seek:/config --restart unless-stopped seek
```

## Testing Before Rebuild

Run the validation script to verify source code is correct:

```bash
# PowerShell (Windows)
.\scripts\test_phase8_docker.ps1

# Bash (Linux/Mac)
bash scripts/test_phase8_docker.sh
```

All 10 tests should pass before building.

## Commits Applied

1. `0e1b992` - Added missing imports to utils/legacy.py
2. `06b8ab8` - Updated entrypoint.sh UPDATE_FILES/UPDATE_DIRS
3. `51e4799` - Fixed CRITICAL_FILES validation (first occurrence)
4. `c53c133` - Fixed final validation check
5. `77b5410` - Fixed get_cache_file import location
6. `b0dc066` - Removed circular import
7. `559b3a1` - Fixed legacy code paths (7 locations)

## Current Status

Phase 8 migration is complete. All import errors have been fixed. The Docker container should start successfully with both fresh installs and updates from older versions.
