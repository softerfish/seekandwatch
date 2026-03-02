# SeekAndWatch Cloud

[https://seekandwatch.com](https://seekandwatch.com)

SeekAndWatch Cloud is a **hosted web app** that lets your friends and family request movies and TV shows without needing access to your Plex, Radarr, or Sonarr. You run everything from home; the cloud never connects to your server.

---

## How It Works

### The Big Picture

```
┌─────────────────────┐         ┌─────────────────────┐         ┌─────────────────────┐
│   FRIENDS           │         │   SEEKANDWATCH      │         │   YOUR HOME         │
│   (any browser)     │         │   CLOUD             │         │   SERVER            │
│                     │         │   (web app)         │         │                     │
│  Browse & search    │ ──────> │  Stores requests    │ <────── │  Local SeekAndWatch │
│  Click "Request"    │         │  in your account    │         │  polls for requests │
│                     │         │                     │         │                     │
│                     │         │                     │         │  Sends approved     │
│                     │         │                     │ ──────> │  items to Radarr    │
│                     │         │                     │         │  or Sonarr          │
└─────────────────────┘         └─────────────────────┘         └─────────────────────┘
```

1. **Friends** visit the cloud site, browse or search, and click **Request** on titles they want.
2. **Requests** are stored in the cloud under your account.
3. **Your local SeekAndWatch app** polls the cloud (every 75-120 seconds by default) and picks up approved requests.
4. **Approved items** are automatically sent to Radarr or Sonarr on your home machine.
5. **No open ports, VPNs, or reverse proxies** - Your server always connects *out* to the cloud. The cloud never connects *in* to you.

### Instant Sync with Webhooks (Optional)
If you want requests to sync **immediately** (without waiting for the 2-minute poll), you can enable a **Cloudflare Tunnel** in the local app's Requests Settings. This creates a secure, private bridge that allows the cloud to notify your home server the second a request is approved.

### What Stays Private

- **Plex URL and tokens** - Never leave your machine.
- **Radarr/Sonarr API keys** - Only used locally.
- **Your media library** - The cloud only knows what you choose to sync (TMDB IDs for "already owned" filtering).

### Features at a glance

- **Friends:** Dashboard with "Your requests" carousel, request notes, and friendly status updates.
- **Owners:** One-click approval dashboard, detailed request stats, and automatic library syncing.
- **System Health:** A compact dashboard status bar shows you at a glance if Plex, Radarr, Sonarr, and the Cloud are connected.

---

## Quick Start

### 1. Create a Cloud Account
Go to [seekandwatch.com](https://seekandwatch.com) and register as a **server owner**. (Beta: you may need an invite code from r/SeekAndWatch.)

### 2. Connect Your Local App (One-Click Pairing)
The easiest way to connect is using the **One-Click Pair** button:
1. In your **local SeekAndWatch app**, go to **Sidebar -> SeekAndWatch Cloud -> Requests Settings**.
2. Click **One-Click Pair with Cloud**.
3. A window will open asking you to log in to the cloud and authorize the connection.
4. Once authorized, your API key is automatically saved!

### 3. Choose Your Handlers
1. On the same **Requests Settings** page, ensure **Movies Handler** is set to **Radarr** and **TV Shows Handler** is set to **Sonarr**.
2. Check **Enable cloud sync**.
3. Click **Save Settings**.

### 4. Invite Friends
On the cloud Dashboard, go to **Invite Friends** -> **Create Invite Link**. Share the link; friends use it to register and start requesting.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Server Owners Guide](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud-Server-Owners-Guide) | All settings in the local app and web app, webhook setup, Plex sync, and more. |
| [Friends Guide](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud-Friends-Guide) | How to register, browse, request, and check request status. |

---

## Troubleshooting

### Requests never show up in the local app
- Check that the API key is correct in **Requests Settings**.
- Ensure **Enable cloud sync** is checked.
- Make sure the local app is running and can reach the internet.
- Regenerate the key on the cloud if needed (that invalidates the old one).

### "Invalid key" or cloud returns an error
- Regenerate the API key on the cloud dashboard.
- Paste the new key in the local app's Requests Settings and save.

### Friend says "Already requested"
- That title is already in your queue. You can wait or manually reset/deny it so they can re-request.

### Approved request didn't go to Radarr/Sonarr
- Check your handler settings (Radarr/Sonarr URL and API key) in the local app's **Settings -> APIs & Connections**.
- Check the **Logs** page for errors.

### Friend can't register
- Each invite link is usually one-time use. Create a new link and share it again.

### I lost my API key
- Generate a new key on the cloud dashboard; the old one stops working immediately.

### I'm not getting the weekly digest email
- The digest is sent by the cloud once per week (e.g. Sunday). Ensure "Weekly digest email" is checked in Settings -> Notifications (default is on). If the cloud admin has not set up the weekly digest cron job, the digest will not be sent. Ask the server owner or cloud admin to confirm.

---

## Security & Privacy

- **Outbound only** - Your server connects out to the cloud; the cloud never initiates connections to you.
- **No media access** - The cloud cannot see, stream, or control your Plex library.
- **Encryption** - All traffic uses HTTPS. Sensitive data (tokens, names) is encrypted at rest.
- **Revocable** - You can regenerate your API key at any time to cut off access.
- **Optional sync** - Library sync (for "already owned" filtering) is opt-in and only sends TMDB IDs.

---

## Beta Notice

SeekAndWatch is currently in **beta**. To request access, go to [r/SeekAndWatch](https://www.reddit.com/r/SeekAndWatch/) and either **post for access** or **send a mod a PM**.