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

# 4. Migrate from old /config/app structure to /config (if needed)
# Old installations had files in /config/app, but we always use /config directly now
if [ -d "/config/app" ] && [ -f "/config/app/app.py" ] && [ ! -f "/config/app.py" ]; then
    echo "Migrating from /config/app to /config (one-time migration)..."
    # Move all files from /config/app to /config
    for item in /config/app/* /config/app/.*; do
        if [ -e "$item" ] && [ "$(basename "$item")" != "." ] && [ "$(basename "$item")" != ".." ]; then
            item_name=$(basename "$item")
            if [ ! -e "/config/$item_name" ]; then
                echo "  Moving $item_name from /config/app to /config"
                mv "$item" "/config/"
            fi
        fi
    done
    # Remove empty /config/app directory
    if [ -z "$(ls -A /config/app 2>/dev/null)" ]; then
        rmdir /config/app
        echo "  Removed empty /config/app directory"
    fi
fi

# 4. Detect if /config contains app files (normal case - users mount app directory as /config)
IS_APP_DIR=false
if [ -f "/config/app.py" ] && [ -f "/config/api.py" ] && [ -d "/config/templates" ]; then
    IS_APP_DIR=true
fi

# 4. Prepare writable app dir for self-updates
if [ "$IS_APP_DIR" = "true" ]; then
    # User mounted app directory as /config, use it directly
    APP_DIR="/config"
    echo "Using /config directly as app directory (detected app directory mount)"
    
    # Check if there's a nested app structure and flatten it recursively
    # IMPORTANT: Detect version mismatches to avoid mixing incompatible files
    CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
    
    # Function to extract version from app.py
    get_version_from_app() {
        local app_file="$1"
        if [ -f "$app_file" ]; then
            grep -oP 'VERSION\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' "$app_file" 2>/dev/null | head -1 | grep -oP '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"' || echo "unknown"
        else
            echo "unknown"
        fi
    }
    
    # Function to check if a directory structure is "complete" (has all critical files)
    is_complete_structure() {
        local dir="$1"
        local missing=0
        for crit_file in $CRITICAL_FILES; do
            if [ ! -f "$dir/$crit_file" ]; then
                missing=$((missing + 1))
            fi
        done
        [ $missing -le 1 ]
    }
    
    # Detect all nested app directories and their versions
    echo "🔍 Scanning for nested app structures and version conflicts..."
    declare -A app_versions
    declare -A app_completeness
    declare -A app_timestamps
    
    # Check /config version
    if [ -f "/config/app.py" ]; then
        app_versions["/config"]=$(get_version_from_app "/config/app.py")
        if is_complete_structure "/config"; then
            app_completeness["/config"]="complete"
        else
            app_completeness["/config"]="incomplete"
        fi
        # Get average modification time of critical files
        total_time=0
        file_count=0
        for crit_file in $CRITICAL_FILES; do
            if [ -f "/config/$crit_file" ]; then
                file_time=$(stat -f%m "/config/$crit_file" 2>/dev/null || stat -c%Y "/config/$crit_file" 2>/dev/null || echo "0")
                total_time=$((total_time + file_time))
                file_count=$((file_count + 1))
            fi
        done
        if [ $file_count -gt 0 ]; then
            app_timestamps["/config"]=$((total_time / file_count))
        else
            app_timestamps["/config"]=0
        fi
    fi
    
    # Check all nested app directories
    current_path="/config"
    while [ -d "${current_path}/app" ]; do
        current_path="${current_path}/app"
        if [ -f "$current_path/app.py" ]; then
            app_versions["$current_path"]=$(get_version_from_app "$current_path/app.py")
            if is_complete_structure "$current_path"; then
                app_completeness["$current_path"]="complete"
            else
                app_completeness["$current_path"]="incomplete"
            fi
            # Get average modification time
            total_time=0
            file_count=0
            for crit_file in $CRITICAL_FILES; do
                if [ -f "$current_path/$crit_file" ]; then
                    file_time=$(stat -f%m "$current_path/$crit_file" 2>/dev/null || stat -c%Y "$current_path/$crit_file" 2>/dev/null || echo "0")
                    total_time=$((total_time + file_time))
                    file_count=$((file_count + 1))
                fi
            done
            if [ $file_count -gt 0 ]; then
                app_timestamps["$current_path"]=$((total_time / file_count))
            else
                app_timestamps["$current_path"]=0
            fi
        fi
    done
    
    # Warn about version mismatches
    unique_versions=$(printf '%s\n' "${app_versions[@]}" | sort -u | grep -v "^unknown$" | wc -l)
    if [ "$unique_versions" -gt 1 ]; then
        echo "⚠️ WARNING: Found files from different versions!"
        for path in "${!app_versions[@]}"; do
            echo "   $path: version ${app_versions[$path]} (${app_completeness[$path]})"
        done
        echo "   The script will prefer complete structures and newer timestamps."
        echo "   Mixing versions may cause errors. Consider backing up before proceeding."
    fi
    
    # Flatten nested structures, preferring complete and newer versions
    max_iterations=10
    iteration=0
    
    while [ $iteration -lt $max_iterations ]; do
        # Find the deepest nested app directory starting from /config/app
        deepest_app="/config"
        if [ -d "/config/app" ]; then
            deepest_app="/config/app"
            while [ -d "${deepest_app}/app" ]; do
                deepest_app="${deepest_app}/app"
            done
        fi
        
        # If we found a nested app directory (deeper than /config), flatten it
        if [ "$deepest_app" != "/config" ] && [ -d "$deepest_app" ]; then
            parent_dir=$(dirname "$deepest_app")
            
            # Check if we should prefer the nested structure entirely
            nested_version="${app_versions[$deepest_app]:-unknown}"
            parent_version="${app_versions[$parent_dir]:-unknown}"
            nested_complete="${app_completeness[$deepest_app]:-incomplete}"
            parent_complete="${app_completeness[$parent_dir]:-incomplete}"
            nested_time="${app_timestamps[$deepest_app]:-0}"
            parent_time="${app_timestamps[$parent_dir]:-0}"
            
            prefer_nested=false
            if [ "$nested_complete" = "complete" ] && [ "$parent_complete" != "complete" ]; then
                prefer_nested=true
                echo "⚠️ Found nested app structure at $deepest_app."
                echo "   Preferring nested structure (complete vs incomplete parent)"
            elif [ "$nested_time" -gt "$parent_time" ] && [ "$nested_complete" = "complete" ]; then
                prefer_nested=true
                echo "⚠️ Found nested app structure at $deepest_app."
                echo "   Preferring nested structure (newer and complete)"
            else
                echo "⚠️ Found nested app structure at $deepest_app. Flattening to $parent_dir..."
            fi
            
            # Move files from deepest nested app to parent directory
            # Compare timestamps and keep the newer version, especially for critical files
            for item in "$deepest_app"/* "$deepest_app"/.*; do
                if [ -e "$item" ] && [ "$(basename "$item")" != "." ] && [ "$(basename "$item")" != ".." ]; then
                    item_name=$(basename "$item")
                    dest_path="$parent_dir/$item_name"
                    
                    # Check if this is a critical file
                    is_critical=false
                    for crit_file in $CRITICAL_FILES; do
                        if [ "$item_name" = "$crit_file" ]; then
                            is_critical=true
                            break
                        fi
                    done
                    
                    if [ ! -e "$dest_path" ]; then
                        # File doesn't exist in destination, move it
                        echo "  Moving $item_name from $deepest_app to $parent_dir"
                        mv "$item" "$dest_path"
                    else
                        # File exists in both places
                        if [ "$prefer_nested" = "true" ] && [ "$is_critical" = "true" ]; then
                            # Prefer nested structure for critical files
                            echo "  Replacing $item_name with version from preferred nested structure"
                            cp "$dest_path" "$dest_path.backup" 2>/dev/null || true
                            mv "$item" "$dest_path"
                        elif [ "$item" -nt "$dest_path" ]; then
                            # Nested file is newer - replace destination
                            echo "  Replacing $item_name with newer version from $deepest_app"
                            # Backup old file first (just in case)
                            if [ "$is_critical" = "true" ]; then
                                cp "$dest_path" "$dest_path.backup" 2>/dev/null || true
                            fi
                            mv "$item" "$dest_path"
                        elif [ "$dest_path" -nt "$item" ]; then
                            # Destination is newer - keep it, remove nested
                            echo "  Keeping newer $item_name in $parent_dir, removing from $deepest_app"
                            rm -rf "$item"
                        else
                            # Same timestamp - keep destination, remove nested (destination takes precedence)
                            echo "  Same timestamp for $item_name, keeping $parent_dir version"
                            rm -rf "$item"
                        fi
                    fi
                fi
            done
            
            # Remove empty nested app directory
            if [ -z "$(ls -A "$deepest_app" 2>/dev/null)" ]; then
                rmdir "$deepest_app"
                echo "  Removed empty nested directory $deepest_app"
            fi
            
            iteration=$((iteration + 1))
        else
            # No more nested app directories found, we're done
            break
        fi
    done
    
    if [ $iteration -ge $max_iterations ]; then
        echo "⚠️ WARNING: Reached maximum flattening iterations. There may be a circular structure."
    elif [ $iteration -gt 0 ]; then
        echo "✅ Finished flattening nested app structures ($iteration level(s) flattened)"
    fi
    
    # Ensure all files from image are present
    echo "Ensuring all app files are present..."
    cp -an /app/. "$APP_DIR/" 2>/dev/null || true
else
    # Normal case: /config should contain app files
    # If /config is empty or missing files, copy from image
    APP_DIR="/config"
    
    # Check if /config already has app files
    if [ -f "/config/app.py" ] && [ -f "/config/api.py" ]; then
        echo "Using existing app files in /config"
    else
        # /config is empty or missing files, copy from image
        echo "Seeding app files into /config from Docker image..."
        cp -an /app/. "$APP_DIR/" 2>/dev/null || true
    fi
fi

# 4b. Cleanup legacy layouts (one-time, safe moves)
# Note: This section handles old /config/app structures, but we now always use /config directly
CLEANUP_FLAG="/config/.sw_cleanup_done"
if [ "$IS_APP_DIR" != "true" ]; then
    # Only run cleanup if /config is NOT an app directory
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

        # Detect and fix nested app/app structure (recursively handles any depth)
        # IMPORTANT: Detect version mismatches to avoid mixing incompatible files
        CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
        
        # Function to extract version from app.py
        get_version_from_app() {
            local app_file="$1"
            if [ -f "$app_file" ]; then
                # Extract VERSION = "x.x.x" from app.py
                grep -oP 'VERSION\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' "$app_file" 2>/dev/null | head -1 | grep -oP '"[0-9]+\.[0-9]+\.[0-9]+"' | tr -d '"' || echo "unknown"
            else
                echo "unknown"
            fi
        }
        
        # Function to check if a directory structure is "complete" (has all critical files)
        is_complete_structure() {
            local dir="$1"
            local missing=0
            for crit_file in $CRITICAL_FILES; do
                if [ ! -f "$dir/$crit_file" ]; then
                    missing=$((missing + 1))
                fi
            done
            # Consider complete if missing 1 or fewer critical files (some might be optional)
            [ $missing -le 1 ]
        }
        
        # First, detect all nested app directories and their versions
        echo "🔍 Scanning for nested app structures and version conflicts..."
        declare -A app_versions
        declare -A app_completeness
        declare -A app_timestamps
        
        # Check /config/app version
        if [ -f "/config/app/app.py" ]; then
            app_versions["/config/app"]=$(get_version_from_app "/config/app/app.py")
            if is_complete_structure "/config/app"; then
                app_completeness["/config/app"]="complete"
            else
                app_completeness["/config/app"]="incomplete"
            fi
            # Get average modification time of critical files
            total_time=0
            file_count=0
            for crit_file in $CRITICAL_FILES; do
                if [ -f "/config/app/$crit_file" ]; then
                    file_time=$(stat -f%m "/config/app/$crit_file" 2>/dev/null || stat -c%Y "/config/app/$crit_file" 2>/dev/null || echo "0")
                    total_time=$((total_time + file_time))
                    file_count=$((file_count + 1))
                fi
            done
            if [ $file_count -gt 0 ]; then
                app_timestamps["/config/app"]=$((total_time / file_count))
            else
                app_timestamps["/config/app"]=0
            fi
        fi
        
        # Check all nested app directories
        current_path="/config/app"
        while [ -d "${current_path}/app" ]; do
            current_path="${current_path}/app"
            if [ -f "$current_path/app.py" ]; then
                app_versions["$current_path"]=$(get_version_from_app "$current_path/app.py")
                if is_complete_structure "$current_path"; then
                    app_completeness["$current_path"]="complete"
                else
                    app_completeness["$current_path"]="incomplete"
                fi
                # Get average modification time
                total_time=0
                file_count=0
                for crit_file in $CRITICAL_FILES; do
                    if [ -f "$current_path/$crit_file" ]; then
                        file_time=$(stat -f%m "$current_path/$crit_file" 2>/dev/null || stat -c%Y "$current_path/$crit_file" 2>/dev/null || echo "0")
                        total_time=$((total_time + file_time))
                        file_count=$((file_count + 1))
                    fi
                done
                if [ $file_count -gt 0 ]; then
                    app_timestamps["$current_path"]=$((total_time / file_count))
                else
                    app_timestamps["$current_path"]=0
                fi
            fi
        done
        
        # Warn about version mismatches
        unique_versions=$(printf '%s\n' "${app_versions[@]}" | sort -u | grep -v "^unknown$" | wc -l)
        if [ "$unique_versions" -gt 1 ]; then
            echo "⚠️ WARNING: Found files from different versions!"
            for path in "${!app_versions[@]}"; do
                echo "   $path: version ${app_versions[$path]} (${app_completeness[$path]})"
            done
            echo "   The script will prefer complete structures and newer timestamps."
            echo "   Mixing versions may cause errors. Consider backing up before proceeding."
        fi
        
        # Flatten nested structures, preferring complete and newer versions
        max_iterations=10
        iteration=0
        
        while [ $iteration -lt $max_iterations ]; do
            # Find the deepest nested app directory
            deepest_app="/config/app"
            while [ -d "${deepest_app}/app" ]; do
                deepest_app="${deepest_app}/app"
            done
            
            # If we found a nested app directory (deeper than /config/app), flatten it
            if [ "$deepest_app" != "/config/app" ]; then
                parent_app=$(dirname "$deepest_app")
                
                # Check if we should prefer the nested structure entirely
                nested_version="${app_versions[$deepest_app]:-unknown}"
                parent_version="${app_versions[$parent_app]:-unknown}"
                nested_complete="${app_completeness[$deepest_app]:-incomplete}"
                parent_complete="${app_completeness[$parent_app]:-incomplete}"
                nested_time="${app_timestamps[$deepest_app]:-0}"
                parent_time="${app_timestamps[$parent_app]:-0}"
                
                prefer_nested=false
                if [ "$nested_complete" = "complete" ] && [ "$parent_complete" != "complete" ]; then
                    prefer_nested=true
                    echo "⚠️ Found nested app structure at $deepest_app."
                    echo "   Preferring nested structure (complete vs incomplete parent)"
                elif [ "$nested_time" -gt "$parent_time" ] && [ "$nested_complete" = "complete" ]; then
                    prefer_nested=true
                    echo "⚠️ Found nested app structure at $deepest_app."
                    echo "   Preferring nested structure (newer and complete)"
                else
                    echo "⚠️ Found nested app structure at $deepest_app. Flattening to $parent_app..."
                fi
                
                # Move files from deepest nested app to parent app
                # Compare timestamps and keep the newer version, especially for critical files
                for item in "$deepest_app"/* "$deepest_app"/.*; do
                    if [ -e "$item" ] && [ "$(basename "$item")" != "." ] && [ "$(basename "$item")" != ".." ]; then
                        item_name=$(basename "$item")
                        dest_path="$parent_app/$item_name"
                        
                        # Check if this is a critical file
                        is_critical=false
                        for crit_file in $CRITICAL_FILES; do
                            if [ "$item_name" = "$crit_file" ]; then
                                is_critical=true
                                break
                            fi
                        done
                        
                        if [ ! -e "$dest_path" ]; then
                            # File doesn't exist in destination, move it
                            echo "  Moving $item_name from $deepest_app to $parent_app"
                            mv "$item" "$dest_path"
                        else
                            # File exists in both places
                            if [ "$prefer_nested" = "true" ] && [ "$is_critical" = "true" ]; then
                                # Prefer nested structure for critical files
                                echo "  Replacing $item_name with version from preferred nested structure"
                                cp "$dest_path" "$dest_path.backup" 2>/dev/null || true
                                mv "$item" "$dest_path"
                            elif [ "$item" -nt "$dest_path" ]; then
                                # Nested file is newer - replace destination
                                echo "  Replacing $item_name with newer version from $deepest_app"
                                # Backup old file first (just in case)
                                if [ "$is_critical" = "true" ]; then
                                    cp "$dest_path" "$dest_path.backup" 2>/dev/null || true
                                fi
                                mv "$item" "$dest_path"
                            elif [ "$dest_path" -nt "$item" ]; then
                                # Destination is newer - keep it, remove nested
                                echo "  Keeping newer $item_name in $parent_app, removing from $deepest_app"
                                rm -rf "$item"
                            else
                                # Same timestamp - keep destination, remove nested (destination takes precedence)
                                echo "  Same timestamp for $item_name, keeping $parent_app version"
                                rm -rf "$item"
                            fi
                        fi
                    fi
                done
                
                # Remove empty nested app directory
                if [ -z "$(ls -A "$deepest_app" 2>/dev/null)" ]; then
                    rmdir "$deepest_app"
                    echo "  Removed empty nested directory $deepest_app"
                fi
                
                iteration=$((iteration + 1))
            else
                # No more nested app directories found, we're done
                break
            fi
        done
        
        if [ $iteration -ge $max_iterations ]; then
            echo "⚠️ WARNING: Reached maximum flattening iterations. There may be a circular structure."
        elif [ $iteration -gt 0 ]; then
            echo "✅ Finished flattening nested app structures ($iteration level(s) flattened)"
        fi

        echo "⚠️ Legacy layout detected. Save a backup ZIP to your desktop before continuing."
        # Move old root app files into the live app folder, comparing timestamps
        CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
        if [ -d "/config/app" ]; then
            for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
                if [ -e "/config/$path" ]; then
                    # Check if this is a critical file
                    is_critical=false
                    for crit_file in $CRITICAL_FILES; do
                        if [ "$path" = "$crit_file" ]; then
                            is_critical=true
                            break
                        fi
                    done
                    
                    if [ ! -e "/config/app/$path" ]; then
                        # File doesn't exist in app, move it
                        echo "Moving $path from /config root to /config/app..."
                        mkdir -p "/config/app/$(dirname "$path")"
                        mv "/config/$path" "/config/app/$path"
                    elif [ "/config/$path" -nt "/config/app/$path" ]; then
                        # Root file is newer - replace app version
                        echo "Replacing $path in app/ with newer version from root"
                        if [ "$is_critical" = "true" ]; then
                            cp "/config/app/$path" "/config/app/$path.backup" 2>/dev/null || true
                        fi
                        mv "/config/$path" "/config/app/$path"
                    else
                        # App file is newer or same - keep app version, remove root
                        echo "Keeping newer $path in app/, removing from root"
                        rm -rf "/config/$path"
                    fi
                fi
            done
        fi

        touch "$CLEANUP_FLAG"
    fi
fi

# Legacy: Move files from /config root to /config/app (only for old installations)
# This is kept for backward compatibility but shouldn't be needed anymore
# Skip this if /config IS the app directory (normal case now)
CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
if [ "$IS_APP_DIR" != "true" ] && [ -d "/config/app" ]; then
    for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
        if [ -e "/config/$path" ]; then
            # Move to /config/app if it doesn't exist there, or if it's newer
            if [ ! -e "/config/app/$path" ] || [ "/config/$path" -nt "/config/app/$path" ]; then
                echo "Moving $path from /config to /config/app..."
                mkdir -p "/config/app/$(dirname "$path")"
                mv "/config/$path" "/config/app/$path"
            else
                # File exists in app and is newer or same
                # Check if this is a critical file - never delete those
                is_critical=false
                for crit_file in api.py utils.py models.py presets.py app.py; do
                    if [ "$path" = "$crit_file" ]; then
                        is_critical=true
                        break
                    fi
                done
                
                # Only remove from root if it's NOT a critical file
                if [ "$is_critical" = "false" ]; then
                    rm -rf "/config/$path"
                else
                    # For critical files, keep a backup copy in root as safety net
                    echo "Keeping critical file $path in /config root as backup"
                fi
            fi
        fi
    done
fi

# Optional: if the host parent is mounted, clean legacy files there too.
# Set CLEANUP_ROOT=/host_config and mount the parent to that path.
# BUT: Never delete critical files from CLEANUP_ROOT - they might be backups
# Skip this if /config IS the app directory
if [ "$IS_APP_DIR" != "true" ] && [ -n "$CLEANUP_ROOT" ] && [ -d "$CLEANUP_ROOT" ]; then
    CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
    for path in api.py app.py utils.py models.py presets.py requirements.txt README.md docker-compose.yml Dockerfile entrypoint.sh icon.png templates static images .gitignore; do
        if [ -e "$CLEANUP_ROOT/$path" ]; then
            # Check if this is a critical file - don't delete those
            is_critical=false
            for crit_file in $CRITICAL_FILES; do
                if [ "$path" = "$crit_file" ]; then
                    is_critical=true
                    break
                fi
            done
            
            # Only delete non-critical files
            if [ "$is_critical" = "false" ]; then
                rm -rf "$CLEANUP_ROOT/$path"
            else
                echo "Preserving critical file $path in CLEANUP_ROOT as backup"
            fi
        fi
    done
fi

# Fill in any missing app files from the image (no overwrite for most files).
# BUT: Always ensure critical files exist and are valid
if [ -d "$APP_DIR" ]; then
    echo "Ensuring $APP_DIR has all required files..."
    
    # First, copy all files from image (no overwrite for non-critical files)
    cp -an /app/. "$APP_DIR/" 2>/dev/null || true
    
    # Ensure critical files exist and are valid - ALWAYS ensure they're good
    # Priority: 1) Image, 2) /config root backup (if APP_DIR is not /config), 3) existing APP_DIR (if valid)
    CRITICAL_FILES="api.py utils.py models.py presets.py app.py"
    for file in $CRITICAL_FILES; do
        file_needs_restore=false
        restore_source=""
        
        # Check if file exists and is valid
        if [ ! -f "$APP_DIR/$file" ]; then
            file_needs_restore=true
            echo "WARNING: $file missing from $APP_DIR"
        elif [ ! -s "$APP_DIR/$file" ]; then
            file_needs_restore=true
            echo "WARNING: $file is empty in $APP_DIR"
        else
            # File exists, check if it's suspiciously small (likely corrupted)
            file_size=$(stat -f%z "$APP_DIR/$file" 2>/dev/null || stat -c%s "$APP_DIR/$file" 2>/dev/null || echo "0")
            if [ "$file_size" -lt 100 ]; then
                file_needs_restore=true
                echo "WARNING: $file appears corrupted (only $file_size bytes) in $APP_DIR"
            fi
        fi
        
        # Restore if needed - prefer image, fallback to /config root (only if APP_DIR is not /config)
        if [ "$file_needs_restore" = "true" ]; then
            if [ -f "/app/$file" ]; then
                echo "Restoring $file from Docker image to $APP_DIR..."
                cp "/app/$file" "$APP_DIR/$file"
            elif [ "$APP_DIR" != "/config" ] && [ -f "/config/$file" ]; then
                # Only check /config root backup if APP_DIR is not /config itself
                echo "Restoring $file from /config root backup to $APP_DIR..."
                cp "/config/$file" "$APP_DIR/$file"
            else
                echo "ERROR: $file not found in Docker image!"
                if [ "$APP_DIR" != "/config" ]; then
                    echo "       Also checked /config root backup - not found there either."
                fi
                echo "       This file is required. Please ensure $file is in your source files when building the Docker image."
                echo "       Current APP_DIR: $APP_DIR"
                echo ""
                echo "CRITICAL: Missing required file $file. The application cannot start without it."
                echo "          Please restore $file from your source repository or backup."
                exit 1
            fi
        fi
    done
    
    # Final verification - ensure all critical files exist before starting
    missing_critical=false
    for file in $CRITICAL_FILES; do
        if [ ! -f "$APP_DIR/$file" ] || [ ! -s "$APP_DIR/$file" ]; then
            echo "ERROR: Critical file $file is still missing or empty after restoration attempts!"
            missing_critical=true
        fi
    done
    
    if [ "$missing_critical" = "true" ]; then
        echo ""
        echo "FATAL: Cannot start application - required files are missing."
        echo "       Please restore the missing files from your source repository or backup."
        exit 1
    fi
    
    # Cleanup: Remove /config/app if it exists and we're using /config directly
    # Only do this after verifying all critical files exist in /config
    if [ "$APP_DIR" = "/config" ] && [ -d "/config/app" ]; then
        # Check if /config/app is empty or only contains old/unused files
        app_dir_contents=$(find /config/app -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
        if [ "$app_dir_contents" -eq 0 ]; then
            echo "Cleaning up empty /config/app directory..."
            rmdir /config/app 2>/dev/null || true
        else
            # Check if /config/app has any critical files that aren't in /config
            has_critical_in_app=false
            for file in $CRITICAL_FILES; do
                if [ -f "/config/app/$file" ] && [ ! -f "/config/$file" ]; then
                    has_critical_in_app=true
                    break
                fi
            done
            
            if [ "$has_critical_in_app" = "false" ]; then
                # /config/app exists but doesn't have critical files we need
                # All critical files are in /config, safe to remove /config/app
                echo "Cleaning up /config/app directory (all critical files are in /config)..."
                rm -rf /config/app
                echo "✅ Removed /config/app directory"
            fi
        fi
    fi
fi

chown -R appuser:appuser "$APP_DIR"
export APP_DIR

# 5. Start the App
# We use 'gosu' (or su-exec) to drop from Root -> appuser securely.
# This ensures the app runs as the user, not as root.
echo "Starting Application..."
exec gosu appuser gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 --chdir "$APP_DIR" app:app