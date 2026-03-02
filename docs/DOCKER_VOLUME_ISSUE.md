# Docker Volume Issue - CRITICAL

## Problem

Your Docker container has `/config` volume mounted, and that directory contains OLD Python files from before Phase 8 migration. The error shows:

```
File "/config/utils.py", line 839, in sync_plex_library
    if is_system_locked():
NameError: name 'is_system_locked' is not defined
```

This means `/config/utils.py` (the OLD monolithic file) is being used instead of the new `utils/legacy.py` in the container.

## Why This Happens

Docker volumes OVERRIDE container files. When you mount `/path/to/config:/config`, any Python files in that directory take precedence over the app's code.

## Solution

You need to REMOVE old Python files from your `/config` directory on the host. These files should NOT be in the config volume:

**Files to DELETE from your host's config directory:**
- `utils.py` (old monolithic file)
- `utils_cleaned.py` (temporary file)
- `utils_old_backup.py` (temporary file)
- Any other `.py` files that aren't data/config

**Files to KEEP in config directory:**
- `seekandwatch.db` (your database)
- `plex_cache.json` (cache file)
- Any other data files
- Backup folders

## How to Fix

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

After fixing, check the logs. You should NOT see `/config/utils.py` in any error messages. All imports should come from the container's `/app` directory.
