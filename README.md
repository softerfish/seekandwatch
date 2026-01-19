# 🚀 SeekAndWatch
![Version](https://img.shields.io/badge/version-1.1.0-blue.svg) ![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg) ![Unraid](https://img.shields.io/badge/Unraid-Template-orange.svg) ![License](https://img.shields.io/badge/License-MIT-green.svg)

⭐ **Show Your Support By Clicking The Star!**
If SeekAndWatch has been helpful to you in any way, please consider giving this repository a star. Your gesture will greatly support our efforts and help others discover the project.

### 👋 What is SeekAndWatch?

Scrolling through a massive Plex library can feel like work. You spend more time looking for something to watch than actually watching it.

SeekAndWatch fixes that. It’s a self-hosted dashboard that connects your Plex library, your Tautulli stats, and your Overseerr requests into one clean, smart interface. 

It learns what you like, finds hidden gems you already own, helps you request new stuff, and now, in v1.1.0, helps you build basic, yet powerful Kometa config files without touching a line of code!

---

## ✨ Key Features

### 🧠 Smart Discovery
- We don't just guess what you might like. The app analyzes the last 5,000 items you've watched to build a custom taste profile specifically for you.
- Seed-Based Recommendations: We use your watch history as "Seeds" to find movies or shows you haven't seen yet.
- Streaming & Scores: instantly see Rotten Tomatoes scores and check if a movie is streaming on Netflix, Prime, or Disney+ right now.

### 🧩 Kometa Config Builder (New in v1.1!)
 No Code Required: You've heard it. Spend 10 minutes to learn YAML files. But it's not always that easy. Building YAML configuration files for Kometa can be a headache for some. We've included a **Visual Kometa Config Builder** that generates the basic code for you. More to come on this in future updates.
Click & Go: Select your libraries, choose your overlays (4K badges, ratings, audio codecs), and toggle collections (Decades, Studios, Genres) with simple checkboxes.

### 🛠️ Powerful Library Tools
- Background Alias Scanner: Hate seeing duplicate recommendations because a movie is named slightly differently on TMDB? Our new **background scanner** finds these "Aliases" automatically and ensures your library matches perfectly.
- Bulk Import: Found a great movie list on Reddit? Copy the text, paste it into the **Bulk Importer**, and instantly turn it into a Plex Collection or send it to Overseerr.
- Auto-Collections: Create dynamic rules (like *"80s Sci-Fi"* or *"Zombie Movies"*) that auto-update every week with our **Collection Builder**.

### 🎲 Fun & Easy
- **I'm Feeling Lucky**: Can't decide? One click serves up a highly-rated movie you haven't watched yet.
- **Spin the Wheel**: A fun visual way to pick a movie when your group can't make up their minds.
- **Instant Trailers**: Watch trailers right inside the dashboard without opening YouTube.

---

## 📋 Requirements

| Service | Status | Why we need it |
| :--- | :--- | :--- |
| **Plex** | **Required** | To scan your library and watch history. |
| **TMDB API Key** | **Required** | To get posters, plot summaries, and actor info. (Free at [themoviedb.org](https://www.themoviedb.org/settings/api)) |
| **Overseerr** | Recommended | To handle requests for new content. |
| **Tautulli** | Recommended | To display detailed server stats and user activity. |
| **OMDB API Key** | Optional | Adds Rotten Tomatoes/Critic scores to the UI. |

---

## 🐳 Installation

### Unraid (has not been submitted yet)
1.  Go to the **Apps** tab in Unraid.
2.  Search for `SeekAndWatch`.
3.  Click **Install**.

### Docker (Manual)
If you prefer to install manually, you can run the GitHub install command from the Command Line in Unraid (the `>_` in the header). Access via http://<YOUR_UNRAID_IP>:5000 after install has completed. Access via http://<YOUR_SERVER_IP>:5000

** Note:** Replace `/path/to/config` with the actual path where you want to store your database and settings.

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
1.1.0
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


1.0.2
- added Login | Register for login screen to make it more clear
- many small bugfixes
- fixed ignore users history for recommendations
- added api testing in settings


This product uses the TMDB API but is not endorsed or certified by TMDB.