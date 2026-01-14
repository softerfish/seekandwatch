# 🚀 SeekAndWatch
![Version](https://img.shields.io/badge/version-1.0.1-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

⭐ **Show Your Support By Clicking The Star!**
If SeekAndWatch has been helpful to you in any way, please consider giving this repository a star. Your gesture will greatly support our efforts and help others discover the project.

---

**Stop scrolling. Start watching.**

### Your Media Server's Command Center.

SeekAndWatch is a powerful, self-hosted discovery and analytics dashboard that turns your passive library into an active experience. It doesn't just guess what you want to watch. It analyzes your actual Plex history, visualizes your habits with Tautulli, and lets you fill the gaps via Overseerr.

It solves the "What do we watch?" problem by combining deep taste analysis with powerful filtering, automated collection management, and instant requesting.

## ✨ Why use this? 
- **🧠 Deep Context Awareness:** Scans your last 500 Plex history items (movies or TV) to build a real-time taste profile.
- **⚡ The "Clipboard-to-Collection" Pipeline:** Have a list of movies on Reddit, Letterboxd, or IMDb? Copy the text, paste it into our **Bulk Importer**, and watch it become a Plex Collection in seconds.
- **👁️ Live Previews:** Don't blindly sync collections. Click the **Eye 👁️** button on any playlist to ping TMDB live and see exactly what movies will be added (and which ones you already own) before you commit.
- **🎰 Gamified Decisions:** Can't pick? Hit **"Spin the Wheel"** and let the app visually cycle through your top results to pick a winner for movie night.
- **🎬 Instant Trailers:** Watch trailers for any recommendation instantly inside a modal without ever leaving the dashboard.
- **📊 Tautulli Power-Ups:** Embeds your server stats directly in the dashboard. Visualize trends, top users, and play counts without switching apps.

---

## 🔥 Killer Feature #1: The Bulk List Importer
**From "Text File" to "Plex Collection" in 10 seconds.**

The Bulk Importer is the holy grail for power users.
* **Paste Anything:** Copy a raw list of titles from anywhere (Reddit threads, "Top 100" articles, text files). We handle newlines, commas, and pipes automatically.
* **Smart Matching:** We strip years, clean up titles, and match them against your specific Plex library.
* **Instant Result:** Create a brand new, static collection in Plex populated with the items you own, instantly.

## 🔥 Killer Feature #2: The Collection Builder
**Automate your curation.**

* **Build Custom Lists:** Use TMDB "Smart Tags" (Keywords) to create niche lists like *"80s Cyberpunk"*, *"Time Travel"*, or *"Zombie Outbreaks"*.
* **Netflix-Style Browser:** Browse your collections in categorized rows (Regional Trending, Decades, Franchises) rather than a cluttered grid.
* **Auto-Sync to Plex:** Set your collections to **"Daily"** or **"Weekly"** updates. The script will automatically scan TMDB for new matches and push them directly to your Plex Library.
* **Request Missing Items:** Preview a collection and instantly click **"Request All Missing"** to send every unowned movie to Overseerr in one go.

---

## ✨ Full Feature List
- **🍀 Seed-Based Discovery:** Scans your watch history to find "Seed" movies that generate fresh recommendations.
- **📋 Bulk Import:** Turn text lists into Plex Collections instantly.
- **🍅 Certified Fresh:** Filter recommendations by **Rotten Tomatoes** and **Metacritic** scores (via OMDB).
- **🎯 Precision Filtering:** Don't just find Action movies. Find *Action movies* rated 7.0+ that are currently streaming on Netflix or Disney+.
- **⚡ One-Click Requests:** Found something? Click "Request" to instantly send it to Overseerr.
- **🎲 I'm Feeling Lucky:** The ultimate cure for analysis paralysis. One click finds a high-rated match and auto-requests it.
- **👥 Multi-User Profiles:** Full multi-user support. Each household member gets their own isolated taste profile based on their specific Plex user history.
- **🚫 Blocklist:** Permanently ban specific titles (or entire shows) from ever being recommended again.
- **📡 Streaming Info:** Instantly see which services (Netflix, Prime, Hulu) offer a title in your specific region.

---

## 🔧 Under the Hood (Advanced Features)

SeekAndWatch isn't just a pretty face; it's built to be robust and server-friendly.

* **🛡️ Automated Backups:** Sleep easy. The app automatically backs up your database and settings every 2 days (configurable). You can restore from a zip file directly in the UI if anything goes wrong.
* **🌍 Community Alias Database:** Matching titles is hard. We maintain a synced database of alternative titles (e.g., matching "Fast & Furious 7" to "Furious 7") to ensure your imports work 100% of the time.
* **⚡ Local Caching Engine:** To prevent slowing down your Plex server, SeekAndWatch builds a lightweight local index of your library. This allows you to run massive searches and matches in milliseconds without hammering the Plex API.
* **📜 System Logs:** Full built-in logging viewer to track every collection sync, API request, and background task.
* **🚀 "What's New" Dashboard:** A visual scroller of the last 30 items added to your server, complete with posters and metadata, right on the home screen.

---

## 🛠️ Prerequisites
- **Plex Server** (Local or Remote)
- **TMDB API Key** (Free from [themoviedb.org](https://www.themoviedb.org/settings/api))
- **Overseerr** (Optional, but required for the Request button to work)
- **Tautulli** (Optional, for the Stats page)
- **OMDB Key** (Optional, required for Rotten Tomatoes/Critic scores)

---

## 🐳 Installation

### Unraid (Recommended) (Should be live soon)
1.  Go to the Apps tab in Unraid.
2.  Search for SeekAndWatch and install.

*Or*

**Option 2: Manual Docker Command for Unraid**
If you prefer to install manually, you can run the GitHub install command from the Command Line in Unraid (the `>_` in the header). Access via http://<YOUR_UNRAID_IP>:5000 after install has completed. Access via http://<YOUR_SERVER_IP>:5000

### GitHub Container Registry
```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```


### How to force an update

You can run these commands in your terminal.

1. Download the new "box" from GitHub:

docker pull seekandwatch/seekandwatch:latest

2. Stop the currently running app:

docker stop seekandwatch

3. Delete the old container: (Don't worry, your database and settings are safe in the /mnt/user/appdata/ folder).

docker rm seekandwatch

4. Start the new one:
```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```
 Access via http://<YOUR_SERVER_IP>:5000
  
