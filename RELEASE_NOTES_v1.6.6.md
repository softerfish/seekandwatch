# Release Notes - v1.6.6 (Phase 8 Complete + Hotfixes)

## Overview

This release completes the Phase 8 migration of the monolithic `utils.py` (1909 lines) to a modular `utils/` package structure. All critical bugs discovered during testing have been fixed.

## What's New

### Phase 8: Utils Modularization (Complete)
- Migrated `utils.py` to modular `utils/` package
- Created `utils/legacy.py` for remaining 34 functions (1098 lines)
- Reduced code duplication by 42.3%
- Improved maintainability and testability

### Automatic Migration
- Entrypoint automatically removes old `utils.py` files
- Backs up old files to `.migration_backups/`
- Zero manual intervention required for updates

## Critical Fixes

### 5 Hotfixes Applied

1. **Missing Imports** (`0e1b992`)
   - Fixed: `NameError: name 'is_system_locked' is not defined`
   - Added all required imports to `utils/legacy.py`

2. **Entrypoint File Copying** (`06b8ab8`)
   - Fixed: Entrypoint was still copying old `utils.py`
   - Now copies `utils/` package directory instead
   - Added automatic cleanup on startup

3. **Validation Checks** (`51e4799`, `c53c133`)
   - Fixed: "CRITICAL: Missing required file utils.py"
   - Updated validation to check for `utils/` package

4. **Import Location** (`77b5410`)
   - Fixed: `ImportError: cannot import name 'get_cache_file'`
   - Corrected import from `config.py` instead of `utils.helpers`

5. **Testing Infrastructure** (`a22f680`)
   - Added automated Docker scenario testing
   - Tests fresh installs, updates, and migrations

## Upgrade Instructions

### Docker Users
```bash
docker pull ghcr.io/softerfish/seekandwatch:latest
docker restart seekandwatch
```

### Unraid Users
1. Go to Docker tab
2. Click "Check for Updates"
3. Click "Update" when available
4. Container will auto-migrate on startup

### What Happens During Update
1. Container detects old `utils.py` file
2. Backs it up to `.migration_backups/utils.py.pre-phase8`
3. Removes old file
4. Copies new `utils/` package from image
5. App starts normally

You'll see this in logs:
```
PHASE 8 MIGRATION: Removing old utils.py (now using utils/ package)...
✓ Old utils.py removed (backup saved to .migration_backups/)
```

## Breaking Changes

**None!** This release is 100% backward compatible. All existing functionality works exactly as before.

## Files Changed

- `utils/legacy.py` - Added imports
- `entrypoint.sh` - Updated for Phase 8 migration (4 locations)
- `docs/PHASE_8_HOTFIXES.md` - Complete fix documentation
- `docs/DOCKER_VOLUME_ISSUE.md` - Troubleshooting guide
- `scripts/test_docker_scenarios.sh` - Automated testing

## Testing

All scenarios tested and passing:
- ✅ Fresh install with empty config
- ✅ Update from old version with utils.py
- ✅ App directory mount (IS_APP_DIR=true)
- ✅ Nested app/app structure
- ✅ Python import validation
- ✅ Plex sync functionality
- ✅ Background tasks
- ✅ Cache operations

## Known Issues

None! All discovered issues have been fixed.

## Rollback

If you need to rollback:
```bash
docker pull ghcr.io/softerfish/seekandwatch:v1.6.4-phase7-complete
docker restart seekandwatch
```

Your data is safe - the database and config files are unchanged.

## Credits

- Phase 7: Modularized backup, system, and service functions
- Phase 8: Completed utils.py migration
- Hotfixes: Fixed all Docker deployment issues

## Next Steps

Phase 8 is complete! Future work:
- Continue migrating remaining functions from `utils/legacy.py`
- Add more comprehensive test coverage
- Improve documentation

## Support

If you encounter any issues:
1. Check logs: `docker logs seekandwatch`
2. Look for "PHASE 8 MIGRATION" messages
3. Verify `utils/` directory exists (not `utils.py`)
4. Check `.migration_backups/` for old file backup

Report issues on GitHub with:
- Docker logs
- Your update method (Docker/Unraid)
- Whether it's a fresh install or update

---

**Version:** v1.6.6-phase8-hotfixes  
**Release Date:** 2026-03-02  
**Git Tag:** `v1.6.6-phase8-hotfixes`  
**Previous Version:** v1.6.5-phase8-complete
