# Smart Discovery

Smart Discovery uses movies or TV shows you like as "seeds" and finds similar stuff you don't already have. You pick a few titles, set some filters, and get a shuffled list of recommendations -different each time.

---

## What you get

- **Personalized recommendations**  - Based on TMDB's "similar" and "recommendations" data for the titles you pick.
- **Two modes**  - Standard (similar + recommendations) or **I'm Feeling Lucky** (random popular picks, no seeds needed).
- **Filters**  - Minimum year, minimum rating, genres, Certified Fresh (Rotten Tomatoes) cutoff, future releases only, international/obscure.
- **Owned items hidden**  - Things you already have in Plex, or in Radarr/Sonarr **with at least one file** (downloaded), are filtered out so you only see stuff you don't own. Items in Radarr/Sonarr that have no file yet (e.g. "Not Available") are not treated as owned and can still appear in results.
- **Randomized results**  - Each run gives you a different order so you're not always seeing the same top 10.
- **Load more**  - Results are paged; you can load more without regenerating.

---

## What you need

- **TMDB API key**  - Required for Smart Discovery (posters, metadata, recommendations). Add it in **Settings**.
- **OMDB API key** (optional)  - For Rotten Tomatoes scores and **Certified Fresh** filtering. Add it in **Settings** if you want critic ratings on results.
- **At least one "seed"**  - For standard mode, pick at least one movie or TV show on the dashboard. For I'm Feeling Lucky you don't need any.
- **Optional:** Plex, [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr), and/or [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr) connected (and optionally the Radarr/Sonarr scanner enabled) so "owned" items are excluded from results.

### How to get API keys

- **TMDB**  - Go to [themoviedb.org](https://www.themoviedb.org/settings/api), sign up or log in, request an API key (choose "Developer"), and copy the key. Free. Paste it in SeekAndWatch under **Settings -> API Keys -> TMDB**.
- **Plex**  - In SeekAndWatch go to **Settings -> Plex** and use "Sign in with Plex" (or the link there) to open Plex and get a token; the app can fill in the token for you. Alternatively, you can get a token manually from [plex.tv](https://www.plex.tv/) (account -> settings or developer tools) and paste the URL and token in Settings.
- **OMDB**  - Go to [omdbapi.com](https://www.omdbapi.com/apikey.aspx), sign up, and request an API key (free tier has a daily limit). Copy the key and paste it in SeekAndWatch under **Settings -> API Keys -> OMDB**. Used for Rotten Tomatoes and Certified Fresh on Smart Discovery results.

---

## How it works

1. **Dashboard**  - You choose Movies or TV, then pick one or more titles as seeds. You can set filters (year, rating, genres, Certified Fresh %, future releases only, international/obscure).
2. **Review**  - You see your seeds and keywords (if any). Hit **Generate Results**.
3. **Generation**  - The app asks TMDB for recommendations/similar titles for each seed, merges and deduplicates them, filters out what you already own (Plex/Radarr/Sonarr), applies your filters, shuffles the list, and shows the first batch.
4. **Results**  - You get a grid of titles. You can request more (Radarr or Sonarr), load more results, or go back and change seeds/filters and generate again.

**I'm Feeling Lucky** skips seeds: it pulls random popular movies (by genre) and shows you five you don't own. Good for quick discovery.

Caches (e.g. TMDB recommendation cache, results cache) are used so repeat runs with the same seeds are faster and to support "load more" without re-hitting TMDB for everything.

---

## How to use it

1. Open the **Dashboard** (home).
2. Select **Movies** or **TV**.
3. Search and select at least one title (or click **I'm Feeling Lucky** to skip this).
4. Optionally set:
   - Minimum year
   - Minimum rating
   - Genres to include
   - Certified Fresh % (Rotten Tomatoes)
   - Future releases only
   - International & obscure
5. Click **Generate Results** (or **I'm Feeling Lucky**).
6. On the **Review** page, confirm and click **Generate Results** again.
7. On the **Results** page, browse, request via Radarr or Sonarr, or **Load more** for more titles.

---

## Setup

- **TMDB API key**  - Settings -> API Keys -> TMDB. Required for Smart Discovery.
- **OMDB API key** (optional)  - Settings -> API Keys -> OMDB. For Rotten Tomatoes and Certified Fresh on results.
- **Plex** (optional)  - Settings -> Plex. If connected, Plex library is used to mark items as owned so they don't appear in results.
- **Radarr / Sonarr** (optional)  - Settings -> Radarr & Sonarr. If connected, you can request movies/shows from the results. Enabling the **Radarr & Sonarr Scanner** in settings also marks those items as owned so they’re excluded from recommendations. See [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) and [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr).

No extra setup is needed beyond adding your TMDB key and, if you want ownership filtering, connecting Plex and/or enabling the Radarr/Sonarr scanner. Add OMDB if you want critic scores and Certified Fresh.

For installation help, see [Installation & Updates](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide).

---

## Troubleshooting

**No results or "Please select at least one item"**  
- In standard mode you must select at least one movie or TV show as a seed. Use the search, click a title to add it, then Generate Results.

**Everything looks like stuff I already have**  
- Make sure Plex is connected and the Plex library has been scanned (Settings -> Plex, run library scan if needed).  
- If you use Radarr/Sonarr, enable the **Radarr & Sonarr Scanner** in Settings and run a refresh so the app knows what you have. Only titles that **have files** (downloaded) in Radarr/Sonarr count as owned; titles in Radarr/Sonarr with no file yet can still appear in results.

**Results are always the same order**  
- The app shuffles results each time you generate. If you're clicking "Load more" on the same results page, the order is fixed for that session. Generate again from the dashboard to get a new shuffled set.

**I'm Feeling Lucky gives "Could not find a lucky pick"**  
- Usually means the app couldn’t find enough unowned titles in the random set it tried. Try again (it picks different genres/pages) or add more ownership data (Plex scan, Radarr/Sonarr scanner) so it has a better idea of what you own.

**Slow first run**  
- First run for a set of seeds may be slower (TMDB calls, no cache). Later runs with the same seeds use the cache and are faster.

**Certified Fresh or filters not doing anything**  
- Certified Fresh uses Rotten Tomatoes data; an OMDB API key in Settings can improve this. Filters apply to the list after recommendations are fetched; if the seed list is narrow, you might get fewer results after filtering.

---

## Quick reference

| Thing | Where |
|-------|--------|
| Pick seeds & filters | Dashboard |
| Confirm & generate | Review page |
| See results, request, load more | Results page |
| TMDB key | Settings -> API Keys |
| OMDB key (optional) | Settings -> API Keys |
| Plex / [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) / [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr) | Settings (for ownership & requests) |
| Radarr & Sonarr scanner | Settings -> Radarr & Sonarr Scanner |
| [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections) | Build collections from your discoveries |