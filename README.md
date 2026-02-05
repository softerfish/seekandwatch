# SeekAndWatch

![Version](https://img.shields.io/badge/version-1.5.3-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) (submitted) ![License](https://img.shields.io/badge/License-MIT-green.svg)

**Star begging:** If this app saves you from endless scrolling, a star for the project helps a lot.

Self-hosted Plex companion: Smart Discovery from your watch history, add movies/shows via Radarr/Sonarr, Kometa builder, Plex collections, Overseerr, Tautulli. One dashboard -less scrolling, more watching.

**[SeekAndWatch Cloud](https://www.SeekAndWatch.com) (beta)** – Hosted option so friends and family can request from your Plex server without needing access to your apps. You approve or deny; requests sync to Radarr, Sonarr, or Overseerr. Zero port forwarding.

**Documentation:** [Wiki](https://github.com/softerfish/seekandwatch/wiki) - install, Smart Discovery, Plex Collections, Radarr, Sonarr, Kometa builder, troubleshooting.

---

## What is SeekAndWatch?

SeekAndWatch is a self-hosted Plex companion that turns your library into a smart “what should we watch?” hub. It connects Plex, Tautulli, TMDB, Overseerr, Radarr, and Sonarr in one dashboard so you can discover, decide, and request without switching tabs.

Goal: spend less time browsing, more time watching. It uses your watch history and owned libraries (Plex, Radarr, Sonarr) to surface stuff you don’t have yet and gives you tools to build collections without editing YAML.

---

## Table of Contents

- [Key Features](#key-features)
- [SeekAndWatch Cloud (Beta)](#seekandwatch-cloud-beta)
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
- **Radarr & Sonarr Scanner** (optional)  - Background scan of your Radarr/Sonarr libraries so those items are treated as "owned" and excluded from Smart Discovery (in addition to Plex).

### Kometa Config Builder (no YAML needed)

- Visual builder for Kometa overlays and collections with toggles.
- Live preview for overlays, ratings, codecs, content badges.
- Library templates, undo/redo, comparison (current vs saved), performance estimates.
- Import configs (paste or URL); generates clean configs you can refine later.

### Plex collections

- **90+ preset collections** - decades, genres, studios, themes, international, awards. Categories are collapsible so you can focus on what you use.
- **Visibility** - Home, Library recommended, and Friends checkboxes on every collection; changes apply to Plex right away (no need to run the collection again).
- **Library Browser** - Live view of all collections on your Plex server with the same visibility toggles. In Plex you can reorder and change options under Settings → Manage → Libraries → Manage Recommendations.
- Auto-update (daily/weekly/manual), sync strict or append-only, bulk list import (IMDb/Letterboxd/Reddit) with smart matching, custom builder.

### Library quality & requests

- Background Alias Discovery to reduce duplicate recommendations; blocklist for titles you never want to see.
- Ignore specific Plex users in recommendation history.
- **Overseerr** for one-click requests; **Radarr/Sonarr** for direct add; track past requests across all three.
- Tautulli integration for trending on server.

### System & security

- Backup/restore (including import); one-click updates for manual Docker installs (Unraid App Store installs update via App Store only).
- System logs and health for scans and scheduled jobs; multi-user accounts with admin controls; security safeguards for logins, forms, and file handling.

---

## SeekAndWatch Cloud (Beta)

**SeekAndWatch Cloud** is a hosted service that lets your friends and family request movies and TV shows from your Plex server without needing access to Plex, Radarr, or Sonarr. Requests land in your Cloud dashboard for you to approve or deny; approved requests sync to Radarr, Sonarr, or Overseerr on your self-hosted SeekAndWatch instance.

- **Zero network config** – Your local server polls the Cloud for new requests. No port forwarding, VPNs, or exposing your IP.
- **You stay in control** – Approve or deny each request; optional master invite codes for registration.
- **Passkey & recovery** – Sign in with passkeys or password; one-time recovery codes for account recovery.

Cloud is currently **in beta**. To request access: [r/SeekAndWatch](https://www.reddit.com/r/SeekAndWatch) – post or send a mod a PM.

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

**SeekAndWatch Cloud (beta)**
v1.5.3
- csrf tokens have been changed. Currently in the previous app, you'd be given a fresh CSRF before each action, which was nice unless you timeout in one window or logout and go back to the first window. Now: 
	- actions now fetch a fresh CSRF token before sending, so long-open or other tabs no longer hit "Invalid CSRF token"
	- logout and login/register notify other tabs via localStorage so they reload and stay in sync
	- when a tab becomes visible again, the app checks the session and redirects to login if the user was logged out elsewhere
- login with Plex
- many UI fixes
- more details in My requests
- small bugfixes

**SeekAndWatch Local**
- a complete overhaul of the library system. Too many movies and tv series were slipping through the cracks even with the aliases database. We now use the Plex API to import your library, list all movie/tv sections. For each item we get a TMDB ID by using Plex guids (when present), then resolving IMDb or TVDB guids through the TMDB API, and if needed searching TMDB by title and year. Those TMDB IDs (with Plex title and type) are saved in the TmdbAlias table so the app can treat them as owned and use them for collections and already in library checks
- removed Plex CacheRemoved Background Aliases scanner
- added a back to the top on the results page
- a lot of UI fixes

<details>
  <summary><b>Past Changelog</b></summary>

v1.5.2

**SeekAndWatch Cloud (beta)** – [https://www.SeekAndWatch.com](https://www.SeekAndWatch.com)
- server owners can get notifications of new requests and users will get a notification when it's approved or denied
- added trailers, tmdb ratings, and several genres as well as an upcoming category
- added Passkey support
- bugfixes
- we now filter out titles already owned in your Plex database from being requested using login with plex or syncing your library with plex
- you can import members on your server by linking to Plex
- emails when a user requests/filled/security warnings
- server owners can revoke invites, control who can request what, or an across the board setting

**SeekAndWatch Local**
- a complete overhaul of the api file
- Smart Disvovery has been revamped. Each search should be pretty different now
- Plex Collections now have a delete button without refreshing the page
- several bugfixes
- small cosmetic fixes
- SeekAndWatch Cloud now shows who made the request, tmdb link and a trailer
- Plex Collections will remember what dropdown category you have clicked to open and what tab you're on (movies or tv)
- fixed Collection Name in Import List plus you can now add these on Plex Home, Library Recommendations and Friends
- fixed preview matches on Custom Builder
- SeekAndWatch now checks with Sonarr and Radarr if you actually have the file before allowing you to request. We used to show a recommendation and allow you to request and then give you an error you already have that in Radarr or Sonarr even if you do not have the file. Now we do not show you these as options to request and is tagges as owned
- fixed preview overlay for TV shrinking to a small box

v1.5.1

**SeekAndWatch Cloud (beta)** – [https://www.SeekAndWatch.com](https://www.SeekAndWatch.com)
- Hosted option so friends and family can request from your Plex server without needing access to Plex or Radarr/Sonarr. You approve or deny; requests sync to Radarr, Sonarr, or Overseerr.
- To request access: [r/SeekAndWatch](https://www.reddit.com/r/SeekAndWatch) – post or send a mod a PM.
- Zero network config – your local server polls the Cloud for requests; no port forwarding or exposing your IP.

Improvements and Bugfixes
- 140+ ready to go 1 click plex collections to choose from
- one time login recovery codes given upon registration and can be regenerated in settings
- you can now change your password in settings
- 1 click updater back to working again

v1.4.1

Bugfixes and security:
- GitHub CodeQL fixes
- custom builder fixed
- bugs on results page
- sonarr and radarr automatic download fixes. Clicking back in the browser fixes to actually load the library

Features:
- added a calendar that pulls all your Radarr and Sonarr releases. You can click on shows and movies in the calendar to add and see history
- account recovery can be done via recovery codes now found in Settings -> System & Maintenance and use the Account recovery section
- Plex collections can now be added to home, library, and friends home screens
- plex collections now minimized
- added additional collections
- added delete option for collections

Additional:
- updated docker-compose

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
- new and updated for the wiki. Smart Discovery, Radarr, Sonarr, Installation & Updates (including Docker/Unraid one-click updater), and wiki homepage

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