# SeekAndWatch Cloud - Server Owners Guide

This guide covers all settings for server owners in both the **local SeekAndWatch app** and the **SeekAndWatch Cloud web app**.

---

## Table of Contents

1. [Local App: Requests Settings](#local-app-requests-settings)
2. [Local App: APIs & Connections](#local-app-apis--connections)
3. [Web App: Dashboard](#web-app-dashboard)
4. [Web App: Settings](#web-app-settings)
5. [Instant Sync (Webhook) - Recommended](#instant-sync-webhook---recommended)
6. [Plex Library Sync](#plex-library-sync)
7. [Inviting Friends](#inviting-friends)
8. [FAQ](#faq)

---

## Local App: Requests Settings

**Location:** Sidebar -> SeekAndWatch Cloud -> Requests Settings

### SeekAndWatch Cloud API Key
- **What it is:** A secret key that links your local app to your cloud account.
- **Where to get it:** Cloud Dashboard -> Local Server Connection -> Generate New Key.
- **Tip:** The key is shown once. Save it somewhere safe.

### Movies Handler
- **Radarr** - Approved movies go directly to Radarr.

### TV Shows Handler
- **Sonarr** - Approved TV shows go directly to Sonarr.

### Enable cloud sync
- **Checked:** The app polls the cloud for approved requests and sends them to your handlers.
- **Unchecked:** The key is saved but no syncing runs.

### Poll interval min / max (seconds)
- How often the app checks for new approved requests.
- **Default:** 75-120 seconds.
- **Minimum:** 30 seconds.
- Leave blank to use defaults.

---

## Local App: APIs & Connections

**Location:** Sidebar -> Settings -> APIs & Connections

These settings are used when the local app sends approved requests to your services.

### Radarr
| Setting | Description |
|---------|-------------|
| **URL** | Your Radarr instance (e.g. `http://192.168.1.50:7878`). |
| **API Key** | Found in Radarr -> Settings -> General. |
| **Root Folder** | Where movies are stored. |
| **Quality Profile** | Which profile to use for new movies. |

### Sonarr
| Setting | Description |
|---------|-------------|
| **URL** | Your Sonarr instance (e.g. `http://192.168.1.50:8989`). |
| **API Key** | Found in Sonarr -> Settings -> General. |
| **Root Folder** | Where TV shows are stored. |
| **Quality Profile** | Which profile to use for new shows. |
| **Language Profile** | (Sonarr v3) Which language profile to use. |

### Plex
| Setting | Description |
|---------|-------------|
| **URL** | Your Plex server (e.g. `http://192.168.1.50:32400`). |
| **Token** | Your Plex token. Use "Link Plex account" to get it automatically. |

---

## Web App: Dashboard

**Location:** [seekandwatch.com/dashboard.php](https://seekandwatch.com/dashboard.php)

### TMDB Configuration
- **TMDB API Key** - Enables search and poster images. Get a free key from [themoviedb.org](https://www.themoviedb.org/).
- **Test** - Verify your key works.

### Sync my library
- **Last run** - When the library was last synced from Plex.
- **Status** - Idle, Running, or Completed.
- **Auto-sync from Plex** - Set an interval (12h, 24h, 48h, weekly) for automatic syncing.
- **Sync from Plex now** - Manually trigger a sync.

### Local Server Connection
- **Generate New Key** - Creates a new API key for your local app. Invalidates any existing key.
- **Copy** - Copy the key to paste in your local app.

### Invite Friends
- **Create Invite Link** - Generate a one-time link to share with friends.
- **Import from Plex** - If you've linked Plex, import friends from your Plex server to send invites.

### News & Announcements (global announcements)
- Post a short message (e.g. "Server maintenance tonight 8-10pm") that appears once on the dashboard for all users (friends and owners). Cuts down "why isn't it working?" questions. You can delete old announcements from the list.
- In some setups this is under **Admin -> Admin Home -> Global Announcements**.

### Request stats (Admin)
- If you have admin access: **Admin -> Admin Home** shows a **Request stats** card with:
  - **Requests this month** - Count of requests created in the current month.
  - **Most requested titles** - Top titles by request count (with type and count).
  - **Most active requesters** - Who's requesting the most (with request count).
- Helps you see what's popular and who's most engaged.

### Pending Requests
- See a quick count of pending requests.
- Click to go to the full Requests page.

---

## Web App: Settings

**Location:** [seekandwatch.com/settings.php](https://seekandwatch.com/settings.php)

### Account Info
- **First Name** - How you're addressed.
- **Email** - For login and notifications.
- **Current Password** - Required to save changes.

### Change Password
- Set a new password (minimum 8 characters).

### Plex Account
- **Link with Plex** - Connect your Plex account for:
  - Signing in with Plex.
  - Syncing your library from the cloud.
  - Importing friends to send invites.
- **Unlink Plex account** - Disconnect your Plex account.

### Notification Preferences
| Notification | Default | Description |
|--------------|---------|-------------|
| Email me when someone requests something | ON | Get notified of new requests. |
| Email me when I request something myself | OFF | Get notified of your own test requests. |
| Email me when my request is filled | ON | (For friends) Notified when request is ready. |
| **Weekly digest email** | ON | One email per week with a summary (e.g. new requests to approve, requests filled this week, new in library). Turn off in Settings -> Notifications if you prefer not to get it. |
| Email me when I log in from a new device | ON | Security alert for new logins. |
| Password changed | ON | Confirmation when password changes. |
| Email changed | ON | Confirmation when email changes. |
| Passkey added/removed | ON | Security alerts for passkey changes. |
| Copy of invite link when I create one | ON | Email yourself a backup of invite links. |
| Reminder if I haven't set up the API | ON | Nudge to complete setup. |

### Library (Owners)
- Shows how many items are synced (TMDB IDs).
- Note: Sync in progress prevents some actions.

---

## Instant Sync (Webhook) - Recommended

**We recommend using webhooks** for instant sync. This allows the cloud to notify your app **immediately** when a request is approved, instead of waiting for the 2-minute poll.

### Why Use Webhooks?

| Without Webhook | With Webhook |
|-----------------|--------------|
| Polls every 75-120 seconds | Instant notification |
| 1-2 minute delay | < 1 second delay |
| More API calls | Fewer API calls |

### Quick Tunnels (Easiest Method - Recommended)

The fastest way to set up webhooks is using **Quick Tunnels** (powered by Cloudflare):

**Step-by-step:**

1. **Open Requests Settings**
   - Go to **Sidebar -> SeekAndWatch Cloud -> Requests Settings**

2. **Scroll to Webhook Notifications**
   - Find the **Webhook notifications** section (below the API key and handlers)

3. **Enable the Tunnel**
   - Click the green **Enable Tunnel** button
   - Wait 5-10 seconds while the tunnel starts

4. **Verify It's Working**
   - You'll see a status message: "Tunnel active: https://[random-words].trycloudflare.com"
   - The button changes to **Disable Tunnel** (red)
   - Your webhook URL is automatically registered with the cloud

**That's it!** The app will now receive instant notifications when requests are approved.

### What You'll See

When the tunnel is active:
- **Status:** "Tunnel active: https://[random-words].trycloudflare.com"
- **Provider:** Cloudflare
- **Type:** Quick Tunnel
- **Green indicator** next to the status

When the tunnel is starting:
- **Status:** "Starting tunnel..."
- **Yellow indicator**

When the tunnel is disabled:
- **Status:** "Tunnel disabled"
- **Gray indicator**
- **Enable Tunnel** button (green)

### Persistent Tunnels (Advanced)

If you want a **permanent URL** that doesn't change when you restart the app, you can use a **Persistent Tunnel**. This requires more setup but gives you a stable URL.

**Requirements:**
- A **Cloudflare account** (free)
- Your own **domain** (e.g., example.com)
- Domain must be added to Cloudflare

**Step-by-step:**

1. **Create a Cloudflare API Token**
   - Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/)
   - Go to **My Profile -> API Tokens**
   - Click **Create Token**
   - Use the **Edit Cloudflare Tunnels** template
   - Or create a custom token with these permissions:
     - **Account** -> **Cloudflare Tunnel** -> **Edit**
   - Click **Continue to summary** -> **Create Token**
   - **Copy the token** (shown once)

2. **Enter Token in SeekAndWatch**
   - Go to **Sidebar -> SeekAndWatch Cloud -> Requests Settings**
   - Scroll to **Webhook notifications**
   - Click **Show Advanced Options**
   - Paste your token in **Cloudflare API Token**
   - Enter your **Tunnel Name** (e.g., "seekandwatch-tunnel")
   - Click **Save Settings**

3. **Enable the Tunnel**
   - Click **Enable Tunnel**
   - Wait 10-20 seconds (persistent tunnels take longer to start)
   - You'll see: "Tunnel active: https://[your-tunnel-name].[your-domain].com"

4. **Verify in Cloudflare**
   - Go to Cloudflare Dashboard -> **Zero Trust** -> **Networks** -> **Tunnels**
   - You should see your tunnel listed as "Healthy"

**Benefits of Persistent Tunnels:**
- Same URL every time (even after restarts)
- Your own domain
- More control over DNS and routing
- Better for production use

**Drawbacks:**
- More complex setup
- Requires Cloudflare account and domain
- Takes longer to start (10-20 seconds vs 5-10 seconds)

---

### How Webhooks Work

Here's what happens when a request is approved:

1. **Friend requests a movie** on the cloud (web app)
2. **You approve it** on the cloud dashboard
3. **Cloud sends webhook** to your tunnel URL (instant)
4. **Your local app receives it** via the tunnel
5. **App adds to Radarr/Sonarr** immediately
6. **Friend sees "Approved"** status right away

**Backup polling:** Even with webhooks active, the app still polls the cloud every hour as a failsafe. If your internet drops briefly or the tunnel restarts, the next poll will catch any missed requests.

---

### Troubleshooting Webhooks

**Tunnel won't start**

**Symptom:** Click "Enable Tunnel" but it stays on "Starting tunnel..." or shows an error.

**Fixes:**
- Check your internet connection
- Make sure port 443 (HTTPS) is not blocked by your firewall
- Try disabling and re-enabling the tunnel
- Check the app logs (Settings -> Logs) for errors
- For persistent tunnels: verify your Cloudflare API token is valid

**Tunnel keeps disconnecting**

**Symptom:** Tunnel status shows "Tunnel active" then switches to "Tunnel disabled" repeatedly.

**Fixes:**
- Check your internet stability
- For quick tunnels: this is normal if your IP changes frequently (use persistent tunnel instead)
- For persistent tunnels: check Cloudflare dashboard for tunnel health
- Restart the app

**Requests still take 1-2 minutes**

**Symptom:** Tunnel is active but requests aren't instant.

**Fixes:**
- Verify the webhook URL is registered on the cloud:
  - Go to cloud Dashboard -> Local Server Connection
  - You should see your tunnel URL listed
- Check that "Enable cloud sync" is checked in Requests Settings
- Test the webhook manually:
  - Approve a test request on the cloud
  - Check app logs (Settings -> Logs) for "Webhook received" message
- If no webhook message appears, the cloud might not be sending to your URL

**"Webhook URL registration failed"**

**Symptom:** Tunnel starts but shows "Failed to register webhook URL with cloud"

**Fixes:**
- Check your API key is correct in Requests Settings
- Verify the cloud is reachable (test in browser: https://seekandwatch.com)
- Try regenerating your API key on the cloud and updating it in the app
- Save settings and try enabling the tunnel again

**Persistent tunnel shows "Tunnel not found" in Cloudflare**

**Symptom:** App says tunnel is active but Cloudflare dashboard shows no tunnel.

**Fixes:**
- Verify your API token has **Cloudflare Tunnel: Edit** permissions
- Check the tunnel name doesn't have special characters (use letters, numbers, hyphens only)
- Try a different tunnel name
- Disable tunnel, wait 30 seconds, enable again

**Quick tunnel URL changes every restart**

**Symptom:** Every time you restart the app, the tunnel URL is different.

**This is normal for quick tunnels.** They use random URLs. If you need a stable URL, use a persistent tunnel instead.

---

### Webhook vs Polling Comparison

| Feature | Polling Only | With Webhook |
|---------|--------------|--------------|
| **Delay** | 75-120 seconds | < 1 second |
| **API calls** | Every 75-120 seconds | Only when needed + hourly backup |
| **Setup** | None (automatic) | Click "Enable Tunnel" |
| **Ports needed** | None | None |
| **Internet required** | Yes | Yes |
| **Failsafe** | N/A | Hourly poll as backup |

---

### FAQs

**Do I need to open ports on my router?**  
No! Tunnels create a secure *outbound* connection from your app to Cloudflare. The cloud sends webhooks to Cloudflare, and Cloudflare forwards them through the tunnel to your app. You don't need to touch your router settings, open ports, or use a VPN.

**What is the "Webhook Failsafe"?**  
Even with a tunnel active, the app still polls the cloud every hour (instead of every 75-120 seconds). This ensures no requests are missed if your internet drops briefly or the tunnel restarts.

**Can I use my own webhook URL (not a tunnel)?**  
Not currently. The app only supports Cloudflare tunnels for webhooks. If you have a public IP and want to use your own URL, you'd need to set up a reverse proxy and modify the app code.

**Does the tunnel work with Docker?**  
Yes! Tunnels work perfectly in Docker. The app handles everything inside the container.

**Does the tunnel work on Unraid?**  
Yes! Whether you installed via Docker or the Unraid App Store, tunnels work the same way.

**What if I don't want to use webhooks?**  
That's fine! The app will continue polling every 75-120 seconds. Webhooks are optional but recommended for better responsiveness.

**Can I see webhook activity?**  
Yes! Check the app logs (Settings -> Logs). You'll see messages like:
- "Tunnel started: https://..."
- "Webhook received: request_id=123"
- "Webhook processed: added to Radarr"

**How much bandwidth do webhooks use?**  
Very little. Each webhook is a tiny JSON message (< 1 KB). Even with heavy use, you'll use less bandwidth than polling.

**What happens if the tunnel dies while I'm away?**  
The hourly failsafe poll will catch any missed requests. When you restart the app (or it auto-restarts), the tunnel will start again automatically if it was enabled before.

---

## Plex Library Sync

Library sync lets the cloud know what you already own so friends see "Available" instead of requesting duplicates.

### How It Works

1. Your Plex library is scanned (via Plex token on the cloud).
2. Each item is matched to a TMDB ID.
3. Only TMDB IDs are stored on the cloud (not titles, posters, or file paths).

### Setup

1. **Link Plex** on the cloud Settings page.
2. On the Dashboard, click **Sync from Plex now** or set an auto-sync interval.

### Auto-Sync Intervals

| Interval | Description |
|----------|-------------|
| Off (manual only) | Only sync when you click the button. |
| Every 12 hours | Good for fast-changing libraries. |
| Every 24 hours | Recommended for most users. |
| Every 48 hours | For slower-changing libraries. |
| Weekly | Minimal syncing. |

### What Gets Synced

- TMDB IDs for movies and TV shows in your Plex library.
- Nothing else (no titles, paths, or actual media).

### Library size limits

Each sync adds up to **10,000 movies** and **10,000 TV shows** at a time. Already-imported titles are skipped so the next run can add more; run sync again (or use auto-sync) until your full library is in.

- **Per-type cap per run:** Up to **10,000** movies and **10,000** TV shows are added per sync. Existing owned items are left in place; only *new* IDs (not already imported) are added, up to 10k of each type. So large libraries sync over multiple runs. Server admins can change this (e.g. in Admin → API Throttle or `system_settings.sync_owned_max_ids_per_type`, 500–50,000).
- **Plex sync run time:** A single Plex sync run is limited to about 30 minutes. Very large libraries may need multiple runs (e.g. hourly cron); items that need TVDB→TMDB resolution are queued and processed over subsequent runs.
- **Request body size (API sync):** If you sync from the local app via the Cloud API, the request body is limited (default 2 MB). Larger payloads get "Request body too large" (413). Admins can raise `sync_owned_max_body_bytes` (about 512 KB–10 MB) if needed.

If your full library is not all synced, run sync again (or rely on auto-sync); already-imported items are skipped and the next run adds more. To allow more than 10k per type per run, ask your server admin to increase `sync_owned_max_ids_per_type`.

---

## Inviting Friends

### Create an Invite Link

1. Go to the cloud Dashboard.
2. Click **Invite Friends** -> **Create Invite Link** (or **Manage Friends** -> **Create invite** in some setups).
3. Copy the link and share it (email, message, etc.). You'll get an email copy of the link if "Copy of invite link when I create one" is on in Settings -> Notifications.

### Import from Plex

If you've linked Plex:
1. Click **Import from Plex**.
2. Select friends from your Plex friends list.
3. Send invites directly.

### Managing Invites

- Each link is typically one-time use.
- You can create multiple links.
- Revoke access by removing the friend from your account (if supported).

### Request notes

Friends can add an optional note when requesting (e.g. "season 2 only" or "prefer 4K"). You see the note when approving the request. Notes are cleared when the request is filled or denied.

### What Friends Can Do

Friends see: **Your requests** carousel (pending + recently filled; filled items drop off after 7 days), **You have X pending request(s)** summary with link to My History, **Recently added** (titles you marked available), request notes when requesting, weekly digest email (default on), and friendly empty states. See [Friends Guide](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud-Friends-Guide) for full details.

---

## FAQ

### Where do I see request stats?

**Admin -> Admin Home.** The "Request stats" card shows requests this month, most requested titles (with type and count), and most active requesters. Helps you see what's popular and who's most engaged.

### What is the weekly digest?

One email per week with a short summary: e.g. new requests to approve, requests filled this week, and new in library. Default is on for owners and friends. Turn it off in Settings -> Notifications if you don't want it. The cloud must run a weekly cron job to send it; if you self-host the cloud, see the cloud docs for cron_digest setup.

### What are request notes?

When a friend requests a title they can add an optional note (e.g. "season 2 only"). You see it when approving. Notes are cleared when the request is filled or denied.

### How do I post a message to all users?

Use **News & Announcements** on the Dashboard (or **Admin -> Admin Home -> Global Announcements** in some setups). Type your message (e.g. "Server maintenance tonight 8-10pm") and post. It appears once on the dashboard for all users.
