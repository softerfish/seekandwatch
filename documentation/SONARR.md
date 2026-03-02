# Sonarr

SeekAndWatch can talk to Sonarr so you can add TV shows from Smart Discovery (or elsewhere in the app) straight into Sonarr. It can also show your Sonarr library on the Media page and use Sonarr (plus the optional scanner) to know what you "own" so those shows don’t clutter recommendations.

**Where to configure:** **Settings → APIs & Connections** (first tab) → **Radarr & Sonarr** section.

---

## What you get

- **Add to Sonarr** – Request a show from the app; it’s added to Sonarr with your chosen root folder and quality profile, and Sonarr can search for missing episodes.
- **Media page (Requested)** – The **Media → Requested** tab lists items you’ve added to Sonarr from the app. It does not show your full Sonarr library in-app (use Sonarr itself to browse and manage series).
- **Ownership for Smart Discovery** – If you enable the **Radarr & Sonarr Scanner** in Settings, shows in Sonarr are treated as "owned" and are hidden from Smart Discovery results. Only shows that **have at least one episode file** count as owned; shows in Sonarr with no episodes yet are not considered owned, so you can still see and request them from the app.
- **Quality profiles** – When adding a show, the app can list your Sonarr quality profiles so you can pick one; if none is chosen, it uses the first available profile. (Sonarr also has **Language Profile**; the app uses the first language profile when adding a series.)

---

## What you need

- **Sonarr** installed and reachable (same machine, Docker, or another server).
- **Sonarr URL** – Base URL, e.g. `http://192.168.1.10:8989`. No trailing slash; don’t include `/api`.
- **Sonarr API key** – In Sonarr: **Settings → General → Security → API Key**.
- **TMDB API key** – Required in SeekAndWatch for adding by TMDB ID and for ownership checks. Add it under **Settings → APIs & Connections → Metadata APIs** in the app.
- **Sonarr** must have at least one **root folder** and one **quality profile**; the app uses the first of each if you don’t pick one.

---

## How it works

- **Add show** – You pick a TV show (e.g. from Smart Discovery). The app looks up the show in Sonarr via TMDB ID (`/api/v3/series/lookup?term=tmdb:{id}`), then sends Sonarr the series payload (root folder, quality profile, language profile, monitored, search for missing episodes). Sonarr adds the show and can start searching.
- **Ownership** – The **Radarr & Sonarr Scanner** (Settings) periodically fetches your Sonarr series list. For each show it gets TMDB ID (or looks it up from TVDB if needed) and stores it. Only series with at least one episode file are treated as owned. When Smart Discovery builds recommendations, it skips any show that’s in that list (or in Plex/aliases).

---

## Setup

1. In **Sonarr**: create at least one root folder and one quality profile (**Settings → Media Management** / **Quality**).
2. In **SeekAndWatch**: open **Settings → APIs & Connections** and scroll to **Radarr & Sonarr**.
3. Enter **Sonarr URL** (e.g. `http://192.168.1.10:8989`).
4. Enter **Sonarr API Key** (from Sonarr → **Settings → General → Security → API Key**).
5. Click **Test** or save; the app will check the connection.
6. (Optional) In the same Settings page, enable **Radarr & Sonarr Scanner** and set an interval so Sonarr shows are used for "owned" filtering in Smart Discovery.

---

## How to use it

- **From Smart Discovery (or any TV card)** – Use the "Request" or "Add to Sonarr" action. The show is added to Sonarr; open Sonarr to browse, manage quality, and run search/refresh.
- **Requested list** – Items you add via the app appear on **Media → Requested**.
- **Quality profile** – When adding a show, you can pick a quality profile in the request dialog; otherwise the app uses the first profile from Sonarr.

---

## Troubleshooting

**"Sonarr not configured"**  
- Set **Sonarr URL** and **Sonarr API Key** in **Settings → APIs & Connections → Radarr & Sonarr** and save. Make sure Sonarr is running and reachable at that URL.

**"Failed to fetch root folders" / "No root folders configured"**  
- In Sonarr go to **Settings → Media Management → Root Folders** and add at least one root folder. Then try again from the app.

**"No quality profiles configured" / "Failed to fetch quality profiles"**  
- In Sonarr go to **Settings → Quality → Quality Profiles** and create at least one profile. Reload the app and try adding a show again.

**"Show not found in Sonarr lookup"**  
- Sonarr couldn’t find the show by TMDB ID. Check that Sonarr is up to date and that the TMDB ID is correct. Sometimes Sonarr’s index needs a moment; try again shortly.

**"Already in your library"**  
- The show is already in Sonarr **and** has at least one episode file (or is considered owned via Plex). Shows in Sonarr with no episodes yet are not treated as owned; if you see this for such a show, run a **Force Refresh** on the Radarr & Sonarr Scanner so the app’s cache is updated.

**"Failed to add show" or error from Sonarr**  
- Check Sonarr logs (**Settings → System → Logs**). Common causes: invalid root folder path, wrong quality profile ID, or Sonarr returned an error (e.g. duplicate, validation). The app shows Sonarr’s message when it can.

**Add show works but I don’t see it on Media → Requested**  
- Refresh the Requested tab. Items added from the app are stored in the app; if they still don’t appear, check that you’re on the same account and that the list isn’t filtered (e.g. by source).

**Smart Discovery still shows shows I have in Sonarr**  
- Enable the **Radarr & Sonarr Scanner** in Settings and run a **Force Refresh**. The app needs to scan Sonarr periodically to mark those shows as owned. For Sonarr, the scanner may use TVDB ID and look up TMDB ID via TMDB’s find API if Sonarr doesn’t expose TMDB ID for every show.

**Connection test fails**  
- Confirm URL (no trailing slash, no `/api`), correct API key, and that the SeekAndWatch server can reach Sonarr (same host or network). If Sonarr is on HTTPS or a different port, fix the URL accordingly.

---

## Quick reference

| What | Where |
|------|--------|
| Sonarr URL & API key in SeekAndWatch | Settings → APIs & Connections → Radarr & Sonarr |
| Sonarr API key in Sonarr | Settings → General → Security → API Key |
| Root folders | Sonarr → Settings → Media Management → Root Folders |
| Quality profiles | Sonarr → Settings → Quality → Quality Profiles |
| Language profile (Sonarr v3) | Sonarr → Settings → Profiles → Language |
| Add show | Smart Discovery / TV card → Request → Sonarr |
| View requested items (incl. app adds) | Media → Requested |
| Use Sonarr for "owned" | Settings → Radarr & Sonarr Scanner → Enable + Force Refresh |

---

## Related

- **[Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr)** - Same app setup for movies; Radarr & Sonarr are configured in the same section.
- **[SeekAndWatch Cloud - Server Owners](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud---Server-Owners-Guide)** - When you use SeekAndWatch Cloud, approved **TV** requests can be sent to Sonarr. The Sonarr URL and API key you set here are used when the TV Shows handler is set to **Sonarr** in **SeekAndWatch Cloud -> Requests Settings**.
