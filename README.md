# SeekAndWatch

![Version](https://img.shields.io/badge/version-1.4.0-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) (submitted) ![License](https://img.shields.io/badge/License-MIT-green.svg)

**GitHub repo description** (paste in Settings → General → Description):

> Self-hosted Plex companion: Smart Discovery from your watch history, add movies/shows via Radarr/Sonarr, Kometa builder, Plex collections, Overseerr, Tautulli. One dashboard -less scrolling, more watching.

If this saves you from endless scrolling, a star helps.

**Documentation:** [Wiki](https://github.com/softerfish/seekandwatch/wiki)  - install, Smart Discovery, Radarr, Sonarr, Kometa builder, troubleshooting.

---

## What is SeekAndWatch?

SeekAndWatch is a self-hosted Plex companion that turns your library into a smart “what should we watch?” hub. It connects Plex, Tautulli, TMDB, Overseerr, Radarr, and Sonarr in one dashboard so you can discover, decide, and request without switching tabs.

Goal: spend less time browsing, more time watching. It uses your watch history and owned libraries (Plex, Radarr, Sonarr) to surface stuff you don’t have yet and gives you tools to build collections without editing YAML.

---

## Table of Contents

- [Key Features](#key-features)
- [Requirements](#requirements)
- [Installation](#installation)
- [How to Update](#how-to-update)
- [Changelog](#changelog)
- [Screenshots](#screenshots)

---

## Key Features

### Smart Discovery (built from your taste)

- Uses your last 5,000 plays to build a taste profile and recommend titles you don’t own or haven’t watched.
- Seed-based recommendations (pick movies/shows you like; get similar stuff) plus **I’m Feeling Lucky** for random picks.
- Filters: genre, year, rating, **Certified Fresh** (Rotten Tomatoes), future releases only, international & obscure.
- **Owned items hidden**  - Plex library plus optional Radarr/Sonarr scanner so recommendations exclude what you already have.
- Randomized results each run; load more without regenerating.
- Instant trailers in the app; optional OMDB for Rotten Tomatoes/critic scores.

### Radarr & Sonarr

- **Add movies/shows from the app**  - Request from Smart Discovery or elsewhere; opens in Radarr/Sonarr with quality profile and root folder.
- **Media page**  - View your Radarr/Sonarr libraries (requested, monitored, downloaded), open in Radarr/Sonarr, toggle monitored, search/refresh.
- **Radarr & Sonarr Scanner** (optional)  - Background scan of your Radarr/Sonarr libraries so those items are treated as “owned” and excluded from Smart Discovery (in addition to Plex).

### Kometa Config Builder (no YAML needed)

- Visual builder for Kometa overlays and collections with toggles.
- Live preview for overlays, ratings, codecs, content badges.
- Library templates, undo/redo, comparison (current vs saved), performance estimates.
- Import configs (paste or URL); generates clean configs you can refine later.

### Plex collections

- Auto-collections with schedules (daily/weekly/manual); sync strict or append-only.
- Bulk list import (IMDb/Letterboxd/Reddit) with smart matching.
- Library browser to see existing Plex collections; custom builder and presets.

### Library quality & requests

- Background Alias Discovery to reduce duplicate recommendations; blocklist for titles you never want to see.
- Ignore specific Plex users in recommendation history.
- **Overseerr** for one-click requests; **Radarr/Sonarr** for direct add; track past requests across all three.
- Tautulli integration for trending on server.

### System & security

- Backup/restore (including import); one-click updates for manual Docker installs (Unraid App Store installs update via App Store only).
- System logs and health for scans and scheduled jobs; multi-user accounts with admin controls; security safeguards for logins, forms, and file handling.

---

## Requirements

| Service | Status | Why |
| :--- | :--- | :--- |
| **Plex** | Recommended | Library access and watch history; ownership filtering in Smart Discovery. |
| **TMDB API Key** | **Required** | Posters, metadata, recommendations. Free at [themoviedb.org](https://www.themoviedb.org/settings/api). |
| **Radarr / Sonarr** | Optional | Add movies/shows from the app; Media page; optional scanner for “owned” filtering. |
| **Overseerr** | Optional | One-click requests. |
| **Tautulli** | Optional | Trending on server. |
| **OMDB API Key** | Optional | Rotten Tomatoes / critic scores in Smart Discovery. |

---

## Installation

Full install and troubleshooting: [Wiki  - Install & Troubleshooting](https://github.com/softerfish/seekandwatch/wiki).

### Unraid (waiting on approval)

1. Open **Apps** in Unraid, search for **SeekAndWatch**, click **Install**.
2. If you install via Unraid App Store, you must update only through the App Store (in-app one-click updater is disabled for that install).

### Docker (manual)

Replace `/path/to/config` with where you want your database and settings (e.g. `/mnt/user/appdata/seekandwatch`). Then open http://&lt;YOUR_SERVER_IP&gt;:5000

```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```

### Docker Compose

From the repo root:

```bash
docker compose up -d
```

---

## How to Update

- **Manual Docker installs:** Use the version badge in the app (one-click updater) or run `docker pull ghcr.io/softerfish/seekandwatch:latest` and recreate the container. Your database and config in `/config` are not touched.
- **Unraid App Store installs:** Update only through the Unraid App Store.
- **Manual steps (if you prefer):** See [Wiki  - Install & Troubleshooting](https://github.com/softerfish/seekandwatch/wiki).

---

## Changelog

v1.4.0
This is a pretty huge update

New features:
- added Radarr/Sonarr support just like you're (almost) in their apps. Monitor, unmonitor, search, interactive search and more to save from having to switch tabs. This will continue to be worked on
- track past requests to Overseerr, Radarr, and Sonarr
- all Settings API URLs will auto-fill based on the IP SeekAndWatch is installed on
- a complete new layout. The old style was getting cluttered too fast
- Radarr & Sonarr Scanner separate background scanner that syncs your Radarr/Sonarr libraries into the app. Items in Radarr/Sonarr are treated as "owned" and excluded from Smart Discovery (in addition to Plex). Configurable in Settings (enable/disable, scan interval, "Force refresh")


Tweaks and bugfixes:
- all logs on one page now in the logs section on the left navbar
- improved 1-click updater to be smarter and recognize nested folder installs to keep the most up to date folder
- Smart Discovery tweaks
- fix for Analyzing your taste / homepage flashing when generating from the review page

Docs:
- new and updated for the wiki. Smart Discovery, Radarr, Sonarr, Installation & Updates (including Docker/Unraid one-click updater),  and wiki homepage

<details>
  <summary><b>Past Changelog</b></summary>
v1.3.2
- finished last of the security updates
- finished Kometa import config files -> copy and paste or by URL

v1.3.1
- fixes for GitHub CodeQL findings
- changed header icons around a bit
- removed stats.html page for Tautulli stats. This page does not seem to be needed
- added custom search range for Tautulli most popular on server
- rewrote how it works on Smart Discovery
- fixed Tatulli spacing for run_order form 4 to 2

Kometa updates added: 
library templates -> save library configurations as reusable templates
undo/redo -> track changes for undo/redo
comparison mode -> compare current config vs saved config
performance indicators -> estimate run time based on selected options

- started the Wiki https://github.com/softerfish/seekandwatch/wiki

v1.3.0
- finished one click updates for non-unraid app installs. unraid users will have to use appstore updates when the app is approved
- users can import backup files now
- many small Smart Discovery improvements not limited to, but including: parallelize TMDB recommendation fetches, cache plex history for 1 hour, and instead of pure shuffle for review, we now score items by vote average × vote count and keep shuffle as a tie‑breaker
- fixed checkmark that will remove titles from influence recommendations

v1.2.4
- I accidently broke TV requests in v1.2.3. Quick repair to get that going again
- added search by future releases
- improved search results and added a checkbox to search for obscure instead of mixing them in standard results

v1.2.3
- moving all styling into a static/style.css file. There might be some broken styling here and there
- added an ignore library to the Smart Discovery search
- removed all search filters from the I'm Feeling Lucky results page 
- in Plex Collections, you now have a live view of all collections currently existing on your Plex server
- refine searches by US content rating (G, PG, PG-13...)
- included a docker-compose.yml

v1.2.2
- added trending on tatulli server to Smart Discovery
- added no more items when Smart Discovery results end
- added block icon to results page
- started adding variables to overlays under content ratings, content, and part of media
- genre options are now checkboxes
- changed layout of filters on review and results pages
- added GitHub link and version in the header
- removed YouTube and Overseerr link in the header

v1.2.1
Increased overlays on Kometa Builder

v1.2.0
- added protections to block password guessing attacks and prevent malicious file access without slowing down your dashboard
- optimized traffic limits to ensure the app runs smoothly even if you leave SeekAndWatch open 24/7
- added permission handling (entrypoint.sh) that automatically adapts to Unraid (PUID 99) or standard Docker setups, eliminating "Permission Denied" errors
- users now stay logged in even after the server restarts or updates
- addedd an adjustable time for running daily Plex Collections
- added TV show status tags to posters in Smart Discovery 
- leading space in api keys will be removed if included in a copy+paste. " 12345" instead of "12345"
- external requests timeout changed to 10 seconds

v1.1.1
- added tooltips to Kometa fields
- added template variables for collections: limit, sort_by, collection_mode, sync_mode, include, exclude
- added several collection defaults for Movies and TV. Overlays to follow
- added a startup routine to auto clear stuck "Busy" flags in the database if the container is killed during a scan
- I'm feeling lucky will now filter owned movies
- faster collection generation

Accounts
First-User-Admin: the first user to register is now automatically granted admin privileges. Subsequent users register as standard users. When the app starts, it will ask, "are there users in the database? Yes. Are there admins? No." It will automatically crown the first user found (ID 1) as the admin. Other users can be promoted to admin in User Settings. Currently, this change gives access to User Management tab access in Settings to promote, demote, and delete accounts

Builder
- live Preview now correctly identifies movies you already own instead of listing everything as missing
- fixed the rating slider number overlapping with the label on some screens

Security fixes:
- added dynamic SECRET_KEY generation using the secrets library to prevent session hijacking and unauthorized admin access
- added safety checks to the search and blocklist screens to ensure special characters in movie titles are displayed as text instead of being interpreted as code
- added a security check to every button and form 
- the new restore function now validates file paths before extraction to prevent malicious overwrites of system files
- tightened Kometa Config security. The system blindly trusted the configuration data saved in the database. We added a verification step to ensure that loaded settings are treated strictly as text, preventing any commands from running automatically if a hacker messed with your database

v1.1.0
This release has a lot of bugfixes, changes and many tweaks to improve speed and accuracy. This is the first app I've made, so I'm learning how to improve as I go with a lot of time and research. If you have any suggestions or comments, here's the new subreddit: https://www.reddit.com/r/SeekAndWatch/

- added a basic kometa yml file generator. It's at the point of working, but you will need to make edits with variables if you check a lot of boxes for collections. I will be improving this in the coming weeks.
- improved hiding recommended content in your plex library with alternative names using a new feature that sends items from your plex cache to tmdb to find and save movie/tv aliases to your alias database
- removed community alias database. You will only have aliases for your own media
- added additional filters on review page that continue on results page
- moved blocklist to settings
- added loading screen to dashboard TV/Movies search
- added tmdb and overseerrlinks to posters as well as rottentomatos and tmdb ratings
- increased Smart Discovery scan to analyze the last 5000 history entries incase one out of several users hasn't watched for a while
- moved Plex cache, alias database, and logs to the settings page. Split settings page into APIs & Connections | Scanners & Cache | System & Maintenance | Logs
- added a notice to Smart Discovery and Plex Collections page
- removed recently added from Smart Discovery page
- last 1000 keywords used in smart discovery are cached for future use avoiding new API calls while loading "more results" or future searches to avoid excessive calls and risk banning. this is found as Keyword Memory (Cache) inside the Settings page under Scanners & Cache 
- instead of checking movies one-by-one, it downloads the tags for all 30 movies at the same time
- started to overhaul the Plex collection manager. Trending lists are now fully syncable. All other lists the user can now choose between syncing and adaptive. 
- we now scan 50 pages of tmdb lists for collection creation
- added a notice to update if available


v1.0.2
- added Login | Register for login screen to make it more clear
- many small bugfixes
- fixed ignore users history for recommendations
- added api testing in settings
</details>


This product uses the TMDB API but is not endorsed or certified by TMDB.

---

## Screenshots

<details>
  <summary><b>View screenshots (v1.4.0)</b></summary>
  <br>

| Smart Discovery (1) | Smart Discovery (2) | Smart Discovery (3) |
| :---: | :---: | :---: |
| <img src="images/smart-discovery1.png" alt="Smart Discovery - Step 1" width="400"> | <img src="images/smart-discovery2.png" alt="Smart Discovery - Step 2" width="400"> | <img src="images/smart-discovery3.png" alt="Smart Discovery - Step 3" width="400"> |

| Kometa Builder |
| :---: | :---: |
| <img src="images/kometa.png" alt="Kometa Main Config" width="400"> |

| Plex Collections |
| :---: |
| <img src="images/plexcollections.png" alt="Plex Collections" width="800"> |

</details>
