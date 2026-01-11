# 🚀 SeekAndWatch
![Version](https://img.shields.io/badge/version-1.0.0-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

**Stop scrolling. Start watching.**

🚀 SeekAndWatch
Your Media Server's New Brain.

SeekAndWatch is a powerful, self-hosted discovery and analytics dashboard. It doesn't just guess what you want to watch. It analyzes your actual Plex history, visualizes your server habits with Tautulli, and lets you fill the gaps in your library via Overseerr.

It solves the "What do we watch?" problem by combining deep taste analysis with powerful filtering (streaming services, genres, ratings) and one-click requesting.

✨ Why use this?
- 🧠 Deep Context Awareness: Scans your last 500 Plex history items (movies or TV) to build a real-time taste profile.
- 📊 Tautulli Power-Ups: Embeds your server stats directly in the dashboard. Visualize trends, top users, and play counts without switching apps.
⚡ Actionable Recommendations: Don't just find a movie —> request it. Fully integrated with Overseerr & Jellyseerr for instant one-click downloads.
- 🕵️‍♂️ Advanced Filtering: Filter recommendations by what's actually available on your streaming services (Netflix, Disney+, etc.), specific genres, or minimum ratings.
- 🎲 I'm Feeling Lucky: The ultimate cure for analysis paralysis. Hit one button to find a high-rated match and auto-request it immediately.
- 🚫 Smart Blocklist: Hated a movie or TV show? Ban it. SeekAndWatch allows you to blacklist titles so they never clutter your feed again.

## ✨ Features
- 🧠 Smart Analysis:** Scans your last **500 Plex history items** to build a real-time taste profile.
- 🎯 Precision Filtering:** Don't just find "Action movies." Find *Action movies* rated **7.0+** that are currently streaming on **Netflix** or **Disney+**.
- ⚡ One-Click Requests:** Found something? Click "Request" to instantly send it to **Overseerr** or **Jellyseerr**.
- 🎲 I'm Feeling Lucky:** Can't decide? Hit the Lucky button to pick a high-rated match and auto-request it.
- 📊 Tautulli Stats:** View server trends and top users directly within the app.
- 🚫 Blocklist:** Permanently ban specific titles (or entire shows) from ever being recommended again.
- 🛡️ Multi-User Friendly:** Admin settings allow you to ignore specific users (e.g., kids' profiles) so they don't mess up your recommendations.

## 🛠️ Prerequisites
- Plex Server** (Local or Remote)
- TMDB API Key** (Free from [themoviedb.org](https://www.themoviedb.org/settings/api))
- Overseerr** (Optional, but required for the "Request" button to work)
- Tautulli** (Optional, for the Stats page)

## 🐳 Installation
### Unraid (Recommended)
1.  Go to the **Docker** tab in Unraid.
2.  At the bottom, under "Template Repositories", enter this repo URL or manually add the container.
3.  **Easier Method:** Copy the `seekandwatch.xml` from this repo into your flash drive at `/boot/config/plugins/dockerMan/templates-user/`.
4.  Go to **Docker > Add Container** and select "SeekAndWatch" from the User Templates dropdown.
