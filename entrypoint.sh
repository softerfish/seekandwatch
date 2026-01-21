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

# 4. Start the App
# We use 'gosu' (or su-exec) to drop from Root -> appuser securely.
# This ensures the app runs as the user, not as root.
echo "Starting Application..."
exec gosu appuser gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 app:app