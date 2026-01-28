#!/bin/bash

# 1. Detect PUID/PGID (Unraid/LinuxServer standard)
# If the user didn't set them, default to 1000 (appuser) or 0 (root)
USER_ID=${PUID:-1000}
GROUP_ID=${PGID:-1000}

echo "Starting SeekAndWatch..."
echo "-----------------------------------"
echo "User ID: $USER_ID"
echo "Group ID: $GROUP_ID"
echo "-----------------------------------"

# 2. Update the 'appuser' to match the ID the user wants
# We use 'usermod' to change the ID of our existing user to match the host's ID
# This prevents "Permission Denied" errors on mounted folders.

if [ "$USER_ID" != "1000" ]; then
    echo "Switching appuser UID to $USER_ID..."
    usermod -o -u "$USER_ID" appuser
    groupmod -o -g "$GROUP_ID" appuser
fi

# 3. Fix Permissions
# We only touch /config because that's where the database lives.
echo "Fixing permissions for /config..."
chown -R appuser:appuser /config

# 4. Prepare writable app dir for self-updates
APP_DIR="/config/app"
if [ ! -d "$APP_DIR" ]; then
    echo "Seeding app files into $APP_DIR..."
    mkdir -p "$APP_DIR"
    cp -a /app/. "$APP_DIR/"
fi

# 4b. Cleanup legacy layouts (one-time, safe moves)
CLEANUP_FLAG="/config/.sw_cleanup_done"
if [ ! -f "$CLEANUP_FLAG" ]; then
    # Flatten nested /config/config if a prior run mapped /config twice.
    if [ -d "/config/config" ]; then
        echo "Found nested /config/config. Flattening layout..."
        for item in backups seekandwatch.db secret.key plex_cache.json scanner.log; do
            if [ -e "/config/config/$item" ] && [ ! -e "/config/$item" ]; then
                mv "/config/config/$item" "/config/"
            fi
        done
        if [ -d "/config/config/app" ] && [ ! -d "/config/app" ]; then
            mv "/config/config/app" "/config/app"
        fi
        if [ -z "$(ls -A /config/config 2>/dev/null)" ]; then
            rmdir /config/config
        fi
    fi

    echo "⚠️ Legacy layout detected. Save a backup ZIP to your desktop before continuing."
    # Move old root app files into the live app folder (without overwriting).
    if [ -d "/config/app" ]; then
        for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
            if [ -e "/config/$path" ] && [ ! -e "/config/app/$path" ]; then
                mkdir -p "/config/app/$(dirname "$path")"
                mv "/config/$path" "/config/app/$path"
            fi
        done
    fi

    touch "$CLEANUP_FLAG"
fi

# Always move any app files from /config root to /config/app, then remove from root
if [ -d "/config/app" ]; then
    for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
        if [ -e "/config/$path" ]; then
            # Move to /config/app if it doesn't exist there, or if it's newer
            if [ ! -e "/config/app/$path" ] || [ "/config/$path" -nt "/config/app/$path" ]; then
                echo "Moving $path from /config to /config/app..."
                mkdir -p "/config/app/$(dirname "$path")"
                mv "/config/$path" "/config/app/$path"
            else
                # File exists in app and is newer or same, just remove from root
                rm -rf "/config/$path"
            fi
        fi
    done
fi

# Optional: if the host parent is mounted, clean legacy files there too.
# Set CLEANUP_ROOT=/host_config and mount the parent to that path.
if [ -n "$CLEANUP_ROOT" ] && [ -d "$CLEANUP_ROOT" ]; then
    for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
        if [ -e "$CLEANUP_ROOT/$path" ]; then
            rm -rf "$CLEANUP_ROOT/$path"
        fi
    done
fi

# Fill in any missing app files from the image (no overwrite).
if [ -d "$APP_DIR" ]; then
    echo "Ensuring /config/app has all required files..."
    cp -an /app/. "$APP_DIR/" 2>/dev/null || true
    
    # Ensure critical files exist - check both image and fail if missing
    CRITICAL_FILES="api.py utils.py models.py presets.py"
    for file in $CRITICAL_FILES; do
        if [ ! -f "$APP_DIR/$file" ]; then
            if [ -f "/app/$file" ]; then
                echo "WARNING: $file missing, copying from image..."
                cp "/app/$file" "$APP_DIR/$file"
            else
                echo "ERROR: $file not found in image or /config/app! This file is required."
                echo "Please ensure $file is in your source files when copying to the NAS."
            fi
        fi
    done
fi

chown -R appuser:appuser "$APP_DIR"
export APP_DIR

# 5. Start the App
# We use 'gosu' (or su-exec) to drop from Root -> appuser securely.
# This ensures the app runs as the user, not as root.
echo "Starting Application..."
exec gosu appuser gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 --chdir "$APP_DIR" app:app