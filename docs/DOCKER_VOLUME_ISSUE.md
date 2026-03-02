# Docker Volume Issue - CRITICAL (FIXED in v1.6.5+)

## Status: FIXED

As of commit `06b8ab8`, the entrypoint script now automatically removes old `utils.py` files during container startup. Users can update normally without manual intervention.

## What Was Fixed

1. **utils/legacy.py** - Added missing imports (commit `0e1b992`)
2. **entrypoint.sh** - Updated to handle Phase 8 migration automatically (commit `06b8ab8`):
   - Removed `utils.py` from UPDATE_FILES list
   - Added `utils/` package to UPDATE_DIRS list
   - Added automatic cleanup of old `utils.py` on startup
   - Updated CRITICAL_FILES to treat `utils` as a package directory

## For Users: Normal Update Process

**Docker Users:**
```bash
docker pull ghcr.io/softerfish/seekandwatch:latest
docker restart seekandwatch
```

**Unraid Users:**
1. Click "Check for Updates" in Docker tab
2. Click "Update" when available
3. Container will auto-migrate on startup

The entrypoint script will automatically:
- Detect old `utils.py` in `/config`
- Back it up to `.migration_backups/utils.py.pre-phase8`
- Remove the old file
- Copy the new `utils/` package from the image

## Problem (Historical Context)

Your Docker container had `/config` volume mounted, and that directory contained OLD Python files from before Phase 8 migration. The error showed:

```
File "/config/utils.py", line 839, in sync_plex_library
    if is_system_locked():
NameError: name 'is_system_locked' is not defined
```

This meant `/config/utils.py` (the OLD monolithic file) was being used instead of the new `utils/legacy.py` in the container.

## Why This Happened

Docker volumes OVERRIDE container files. When you mount `/path/to/config:/config`, any Python files in that directory take precedence over the app's code.

The entrypoint script had logic to copy `utils.py` to `/config` when IS_APP_DIR=true (when users mount their app directory as `/config` for development). This was causing old files to persist across updates.

## Manual Cleanup (Only if Needed)

If you're on an older version and experiencing issues, you can manually clean up:

**Files to DELETE from your host's config directory:**
- `utils.py` (old monolithic file)
- `utils_cleaned.py` (temporary file)
- `utils_old_backup.py` (temporary file)

**Files to KEEP in config directory:**
- `seekandwatch.db` (your database)
- `plex_cache.json` (cache file)
- Any other data files
- Backup folders

## How to Manually Fix (Old Versions Only)

1. Find your config directory on the host (check your docker-compose.yml or Unraid template)
2. Delete old Python files:
   ```bash
   cd /path/to/your/config
   rm -f utils.py utils_cleaned.py utils_old_backup.py
   ```
3. Restart the container:
   ```bash
   docker restart seekandwatch
   ```

## Prevention

The `/config` volume should ONLY contain:
- Database files (seekandwatch.db)
- Cache files (plex_cache.json)
- User data
- Backups

It should NOT contain Python source code. The app code lives in the container, not the volume.

## Verification

After updating to v1.6.5+, check the logs. You should see:
```
PHASE 8 MIGRATION: Removing old utils.py (now using utils/ package)...
✓ Old utils.py removed (backup saved to .migration_backups/)
```

You should NOT see `/config/utils.py` in any error messages. All imports should come from the container's `/app` directory.
