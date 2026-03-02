# Radarr

SeekAndWatch can talk to Radarr so you can add movies from Smart Discovery (or elsewhere in the app) straight into Radarr. It can also show your Radarr library on the Media page and use Radarr (plus the optional scanner) to know what you "own" so those titles don’t clutter recommendations.

**Where to configure:** **Settings → APIs & Connections** (first tab) → **Radarr & Sonarr** section.

---

## What you get

- **Add to Radarr** – Request a movie from the app; it’s added to Radarr with your chosen root folder and quality profile, and Radarr can search for it.
- **Media page (Requested)** – The **Media → Requested** tab lists items you’ve added to Radarr from the app. It does not show your full Radarr library in-app (use Radarr itself to browse and manage movies).
- **Ownership for Smart Discovery** – If you enable the **Radarr & Sonarr Scanner** in Settings, movies in Radarr are treated as "owned" and are hidden from Smart Discovery results. Only movies that **have a file** (downloaded) count as owned; movies in Radarr with no file yet ("Not Available") are not considered owned, so you can still see and request them from the app.
- **Quality profiles** – When adding a movie, the app can list your Radarr quality profiles so you can pick one; if none is chosen, it uses the first available profile.

---

## What you need

- **Radarr** installed and reachable (same machine, Docker, or another server).
- **Radarr URL** – Base URL, e.g. `http://192.168.1.10:7878`. No trailing slash; don’t include `/api`.
- **Radarr API key** – In Radarr: **Settings → General → Security → API Key**.
- **TMDB API key** – Required in SeekAndWatch for adding by TMDB ID and for ownership checks. Add it under **Settings → APIs & Connections → Metadata APIs** in the app.
- **Radarr** must have at least one **root folder** and one **quality profile**; the app uses the first of each if you don’t pick one.

---

## How it works

- **Add movie** – You pick a movie (e.g. from Smart Discovery). The app sends Radarr the TMDB ID, title, year, root folder path, quality profile ID, and options (e.g. search for movie). Radarr adds the movie and can start searching.
- **Ownership** – The **Radarr & Sonarr Scanner** (Settings) periodically fetches your Radarr movie list and stores TMDB IDs (and titles) only for movies that **have a file** (Radarr’s `hasFile`). Movies in Radarr with no file yet are not marked as owned, so they can still appear in Smart Discovery and be requested. When Smart Discovery builds recommendations, it skips any movie that’s in that owned list (or in Plex/aliases).

---

## Setup

1. In **Radarr**: create at least one root folder and one quality profile (**Settings → Media Management** / **Quality**).
2. In **SeekAndWatch**: open **Settings → APIs & Connections** and scroll to **Radarr & Sonarr**.
3. Enter **Radarr URL** (e.g. `http://192.168.1.10:7878`).
4. Enter **Radarr API Key** (from Radarr → **Settings → General → Security → API Key**).
5. Click **Test** or save; the app will check the connection.
6. (Optional) In the same Settings page, enable **Radarr & Sonarr Scanner** and set an interval so Radarr movies are used for "owned" filtering in Smart Discovery.

---

## How to use it

- **From Smart Discovery (or any movie card)** – Use the "Request" or "Add to Radarr" action. The movie is added to Radarr; open Radarr to browse, manage quality, and run search/refresh.
- **Requested list** – Items you add via the app appear on **Media → Requested**.
- **Quality profile** – When adding a movie, you can pick a quality profile in the request dialog; otherwise the app uses the first profile from Radarr.

---

## Troubleshooting

**"Radarr not configured"**  
- Set **Radarr URL** and **Radarr API Key** in **Settings → APIs & Connections → Radarr & Sonarr** and save. Make sure Radarr is running and reachable at that URL.

**"Failed to fetch root folders" / "No root folders configured"**  
- In Radarr go to **Settings → Media Management → Root Folders** and add at least one root folder. Then try again from the app.

**"No quality profiles configured" / "Failed to fetch quality profiles"**  
- In Radarr go to **Settings → Quality → Quality Profiles** and create at least one profile. Reload the app and try adding a movie again.

**"Already in your library"**  
- The movie is already in Radarr **and** has a file (or is considered owned via Plex). Movies in Radarr with no file yet ("Not Available") are not treated as owned; if you see this for such a movie, run a **Force Refresh** on the Radarr & Sonarr Scanner so the app’s cache is updated.

**"Failed to add movie" or error from Radarr**  
- Check Radarr logs (**Settings → System → Logs**). Common causes: invalid root folder path, wrong quality profile ID, or Radarr returned an error (e.g. duplicate, validation). The app shows Radarr’s message when it can.

**Add movie works but I don’t see it on Media → Requested**  
- Refresh the Requested tab. Items added from the app are stored in the app; if they still don’t appear, check that you’re on the same account and that the list isn’t filtered (e.g. by source).

**Smart Discovery still shows movies I have in Radarr**  
- Enable the **Radarr & Sonarr Scanner** in Settings and run a **Force Refresh**. The app needs to scan Radarr periodically to mark those movies as owned.

**Connection test fails**  
- Confirm URL (no trailing slash, no `/api`), correct API key, and that the SeekAndWatch server can reach Radarr (same host or network). If Radarr is on HTTPS or a different port, fix the URL accordingly.

---

## Quick reference

| What | Where |
|------|--------|
| Radarr URL & API key in SeekAndWatch | Settings → APIs & Connections → Radarr & Sonarr |
| Radarr API key in Radarr | Settings → General → Security → API Key |
| Root folders | Radarr → Settings → Media Management → Root Folders |
| Quality profiles | Radarr → Settings → Quality → Quality Profiles |
| Add movie | Smart Discovery / movie card → Request → Radarr |
| View requested items (incl. app adds) | Media → Requested |
| Use Radarr for "owned" | Settings → Radarr & Sonarr Scanner → Enable + Force Refresh |

---

## Related

- **[Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr)** - Same app setup for TV shows; Radarr & Sonarr are configured in the same section.
- **[SeekAndWatch Cloud - Server Owners](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud---Server-Owners-Guide)** - When you use SeekAndWatch Cloud, approved **movie** requests can be sent to Radarr. The Radarr URL and API key you set here are used when the Movies handler is set to **Radarr** in **SeekAndWatch Cloud -> Requests Settings**.
