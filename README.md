# 🚀 SeekAndWatch
![Version](https://img.shields.io/badge/version-1.0.2-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

⭐ **Show Your Support By Clicking The Star!**
If SeekAndWatch has been helpful to you in any way, please consider giving this repository a star. Your gesture will greatly support our efforts and help others discover the project.

---


**SeekAndWatch** is a self-hosted dashboard that turns your passive Plex library into something you can actually use.

It connects your library (Plex), your stats (Tautulli), and your requests (Overseerr) into one clean interface. Create dynamic collections like *"80s Sci-Fi"* or *"Zombie Movies"* that auto-update with new matches. 

It analyzes what you've been watching, figures out what you might like next, and gives you tools to build better collections without the headache.

No more scrolling endlessly. Just find something good and hit play.

---

## 🚀 What does it do?

### 1. Smart Discovery
* **It knows what you like:** The app looks at the last 500 things you watched to build a custom taste profile for you.
* **Seed-Based Recommendations:** It uses your history as "Seeds" to find similar movies or shows you haven't seen yet.
* **Stream & Score:** Filter results by Rotten Tomatoes scores or check if they are streaming on Netflix, Prime, or Disney+ right now.

### 2. Powerful Tools
* **Bulk Import:** Have a list of movies from a Reddit thread or IMDb? Copy the text, paste it into the **Bulk Importer**, and we'll instantly turn it into a Plex Collection.
* **Auto-Collections:** Create dynamic collections like *"80s Sci-Fi"* or *"Zombie Movies"* that auto-update every week with new matches.
* **Instant Requests:** Found something missing? One click sends it straight to Overseerr.

### 3. Fun & Easy
* **I'm Feeling Lucky:** Can't decide? Click one button and let the app pick a highly-rated movie for you.
* **Spin the Wheel:** A fun visual way to pick a movie when you (or your group) can't make up your mind.
* **Trailers:** Watch trailers instantly without leaving the dashboard.

---

## 🔧 Under the Hood
We built this to be robust but easy on your server.

* **Local Caching:** We build a tiny local index of your library so searches are instant and we don't hammer your Plex server.
* **Community Aliases:** We sync with a community database to make sure tricky titles (like *Furious 7* vs *Fast & Furious 7*) always match correctly.
* **Auto-Backups:** Sleep easy. Your database and settings are backed up automatically every 48 hours.

---

## 📋 What you need

| Service | Status | Usage |
| :--- | :--- | :--- |
| **Plex** | **Required** | To scan your library and history. |
| **TMDB API Key** | **Required** | For metadata and discovery. (Free at [themoviedb.org](https://www.themoviedb.org/settings/api)) |
| **Overseerr** | Recommended | To request new movies/shows. |
| **Tautulli** | Recommended | To show user stats. |
| **OMDB API Key** | Optional | For Rotten Tomatoes/Critic scores. |

---

## 🐳 Installation

### Unraid (has not been submitted yet)
1.  Go to the **Apps** tab in Unraid.
2.  Search for `SeekAndWatch`.
3.  Click **Install**.

### Docker (Manual)
If you prefer to install manually, you can run the GitHub install command from the Command Line in Unraid (the `>_` in the header). Access via http://<YOUR_UNRAID_IP>:5000 after install has completed. Access via http://<YOUR_SERVER_IP>:5000

```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```  
Once it's running, just go to: http://<YOUR_SERVER_IP>:5000

How to Update
To force an update to the latest version:

Bash
# 1. Get the new version
docker pull ghcr.io/softerfish/seekandwatch:latest

# 2. Reset the container
docker stop seekandwatch
docker rm seekandwatch

# 3. Start it back up
```bash
docker run -d \
  --name=seekandwatch \
  -p 5000:5000 \
  -v /path/to/config:/config \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/softerfish/seekandwatch:latest
```  
  
### Changelog
1.0.2
- added Login | Register for login screen to make it more clear
- many small bugfixes
- fixed ignore users history for recommendations
- added api testing in settings
