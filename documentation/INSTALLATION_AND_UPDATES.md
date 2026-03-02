# Installation & Update Guide

## Quick Start

### Who can use the one-click updater?

| Install method | One-click updater | How to update |
|----------------|-------------------|----------------|
| **Normal Docker** (pre-built image or build from source, manual install) | Yes | Use the version badge in the app, or `docker pull` and recreate the container |
| **Unraid App Store** (installed via Unraid Community Applications) | No | Update only through the Unraid App Store |

**Normal Docker users**  - No issues with auto updating. The one-click updater in the app works for manual Docker installs (including Unraid users who installed via Docker, not the App Store). Your database, backups, and cache are never modified; only app code is updated.

**Unraid users who installed via the App Store**  - You **must** update through the Unraid App Store only. The in-app one-click updater is disabled for App Store installations so it doesn’t conflict with Unraid’s update system. If you used the Unraid Community Applications (App Store) to install, use the App Store to update; the in-app updater won't work for you.

### Unraid App Store: "Update in App Store" not showing?

If you installed from the **Unraid Community Applications** (App Store) but the app still shows the **one-click updater** (or lets you try it and then tells you to use the App Store), the container is not being detected as an Unraid App Store install.

**Why:** The app detects Unraid App Store installs via an environment variable. The Community Applications template must pass that variable into the container. Inside the container we cannot see the Unraid host, so the only reliable signal is a variable set by the template.

**Fix (template must set the variable):**

1. **If you maintain the Unraid Community Applications template** for SeekAndWatch, add this to the template so every new install gets it:
   - **Variable:** `SEEKANDWATCH_UNRAID`
   - **Value:** `1`
   (Alternatively, `SEEKANDWATCH_SOURCE` = `unraid` works too.)

2. **If you already installed** and the template didn't set it, you can add it yourself:
   - In Unraid: **Docker** -> select **SeekAndWatch** -> **Edit**
   - Switch to **Advanced View** (top right)
   - **Add another Path, Port, Variable, or Label** -> **Variable**
   - **Key:** `SEEKANDWATCH_UNRAID`
   - **Value:** `1`
   - Apply and recreate the container. The app will then show "Unraid: update in App Store" and disable the one-click updater.

---

## Installation

### Standard Docker Installation

```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```

**Replace `/path/to/config`** with your actual config directory (e.g., `/mnt/user/appdata/seekandwatch`).

### What Happens on First Run

- **If you mount your project folder as `/config`** (e.g. manual build + mount): The entrypoint sees `app.py`, `api.py`, `templates/` in `/config` and runs the app from `/config` directly. No `app` subfolder is created.
- **If you use the pre-built image with an empty `/config`**: The entrypoint copies app code from the image into `/config` and runs from there. Your data (database, backups, cache) and app code all live in `/config`.

**You don't need to create an `app` folder**  - the app runs from `/config` (or your project root when mounted as `/config`).

---

## Understanding the File Structure

### No `app` subfolder  - that’s correct

The app **always** runs from a single directory. There is **no `app` subfolder** in normal installs.

**Manual Docker install (build from source + mount project as `/config`):**

You build the image from your project, then run with your project folder mounted as `/config`:

```bash
cd /mnt/user/appdata/seekandwatch
docker build --no-cache -t seekandwatch .
docker run -d --name seekandwatch -p 5000:5000 \
  -v /mnt/user/appdata/seekandwatch:/config \
  --restart unless-stopped seekandwatch
```

Your host folder (e.g. `seekandwatch`) already has `app.py`, `api.py`, `templates/`, etc. at the **root**. You mount that folder as `/config`. The entrypoint detects app files in `/config` and uses **`/config` directly** as the app directory. So inside the container:

- `/config` = your project root (app.py, api.py, templates/, static/, etc.)
- Database, backups, and cache files also live in `/config` (same folder)
- **No `/config/app` is created**  - your layout is correct.

**Pre-built image (e.g. `ghcr.io/softerfish/seekandwatch:latest`) with a dedicated config volume:**

You mount an empty (or data-only) folder as `/config`. The entrypoint copies app code from the image into `/config`. Again, app code and data end up in **`/config`** directly; no `app` subfolder.

### What you see in `/config` (Docker)

```
/config/                    ← Your mapped volume (project root or seeded by entrypoint)
├── app.py
├── api.py
├── utils.py
├── models.py
├── templates/
├── static/
├── ...
├── seekandwatch.db         ← Your database (SQLite)
├── backups/                 ← Your backups
├── plex_cache.json         ← Plex library cache
├── results_cache.json      ← Smart Discovery results cache (optional)
├── history_cache.json      ← Watch history cache (optional)
├── scanner.log             ← Background scanner logs
└── secret.key              ← Encryption key (if used)
```

**Legacy:** Very old installs used to have a `/config/app` layout. The entrypoint migrates those to `/config` and removes the empty `app` folder. New installs do not use `/config/app`.

---

## Updating

### One-Click Updater (Manual Installations Only)

If you installed manually (not via Unraid App Store), you can use the one-click updater:

1. Click the version badge in the header (top right)
2. If an update is available, you'll see a confirmation dialog
3. Click "Update" to download and install the latest release from GitHub

**How it works:**
- Fetches the latest release from GitHub
- Downloads the release archive
- Extracts files into your app directory (the same folder as `app.py`  - usually `/config` when using Docker)
- Restarts the application

**Restrictions:**
- **Disabled for Unraid App Store installs** (always shows instruction to update via App Store)
- **Available for manual Docker installs** when the app directory is writable (e.g. when you mount your project as `/config`)

### Manual Update (Docker Pull)

If you prefer to update manually:

```bash
# 1. Pull the new image
docker pull ghcr.io/softerfish/seekandwatch:latest

# 2. Stop and remove the old container
docker stop seekandwatch
docker rm seekandwatch

# 3. Start with the new image (same command as installation)
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```

The entrypoint will use `/config` (or your mounted project) as the app directory on first run.

### After an Update

- **Database:** New tables or columns are created automatically on first run after an update. You don't need to run any migration commands.
- **Cache files:** If the app adds new cache files, they are created when first needed. Old cache files are left as-is.
- **Restart:** For one-click updates, the app restarts itself. For Docker pull, the new container start is the restart.

### New Features (v1.6+)

- **One-Click Plex Linking:** You no longer need to hunt for an "X-Plex-Token". Just click **Link Plex account** in Settings, authorize at plex.tv, and the app will automatically find your server and save the token for you.
- **One-Click Cloud Pairing:** If you use SeekAndWatch Cloud, you can now connect your local app with a single click. No more copying and pasting API keys!
- **System Health Bar:** Check your dashboard to see a compact status bar. Green dots mean your services (Plex, Radarr, Sonarr, Cloud) are connected and ready to go.
- **Automatic IP Selection:** When you link Plex, the app intelligently chooses the best connection (like your local LAN IP) so things stay fast and reliable.

---

## Troubleshooting

### Files in the Wrong Location

If you see duplicate files in your `/config` folder after an update:

**Symptoms:**
- Files like `app.py`, `templates/`, `static/` appear in `/config` root
- App still runs, but you have duplicate files

**What to do:**
1. **Don't panic**  - your app is still running from `/config`
2. The cleanup script runs automatically on next container restart
3. If files persist, you can manually delete them (they're not being used)

**Safe to delete from `/config` root** (only if duplicates  - app runs from `/config`):
- `app.py`, `api.py`, `utils.py`, `models.py`, `presets.py`
- `templates/`, `static/`, `images/` folders
- `requirements.txt`, `README.md`, `Dockerfile`, `docker-compose.yml`
- `.gitignore`, `entrypoint.sh`, `icon.png`

**Never delete** (your data lives here):
- `seekandwatch.db`  - your database (users, settings, aliases, Radarr/Sonarr cache, etc.)
- `backups/`  - your backups
- `plex_cache.json`  - Plex library index
- `results_cache.json`, `history_cache.json`  - caches (recreated if missing, but you lose in-memory state)
- `scanner.log`  - scanner logs
- `secret.key`  - encryption key (if present)

### Missing Templates Error

If you see `TemplateNotFound: login.html` or similar:

**Cause:** The app directory (e.g. `/config`) is missing or incomplete (e.g. no `templates/` folder).

**Fix:**
1. Stop the container
2. If you use a pre-built image with an empty `/config`, delete the contents of `/config` (or the folder) and restart  - the entrypoint will seed app files from the image
3. If you mount your project as `/config`, ensure your project has `app.py`, `templates/`, etc. and restart the container

### Update Not Working

**For Unraid App Store users:**
- One-click updater is intentionally disabled
- Update via Unraid App Store only

**For manual installs:**
- Check that your app directory (e.g. `/config` when using Docker) is writable
- Check container logs: `docker logs seekandwatch` (or `seekandwatch`)
- Ensure you have internet access (needs to fetch from GitHub)

---

## FAQ

**Q: Do I need to manually create an `app` folder inside `/config`?**  
A: No. The app runs from `/config` directly (or your project root when you mount it as `/config`). No `app` subfolder is created.

**Q: Can I edit files in `/config` (app code)?**  
A: Yes, but if you use the one-click updater, those files will be overwritten on the next update.

**Q: Will my data be lost during updates?**  
A: No. Your database, backups, and cache files in `/config` are never touched by updates. Only the app code (e.g. `app.py`, `templates/`, etc.) in the same directory is updated.

**Q: Will adding new features (e.g. new database tables) break my install?**  
A: No. The app runs database migrations on startup. New tables and columns are created automatically when you update. Your existing data is preserved.

**Q: Can I use git to update?**  
A: The one-click updater uses GitHub releases, not git. If you want git-based updates, you'd need to map your git repo as a volume, but the release-based updater is recommended for most users.

---

## Need Help?

If you're still having issues:
1. Check the container logs: `docker logs seekandwatch`
2. Verify your volume mapping is correct
3. Ensure `/config` directory has proper permissions
4. Open an issue on GitHub with your error logs