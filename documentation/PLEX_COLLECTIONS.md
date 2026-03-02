# Plex Collections

SeekAndWatch lets you build and manage Plex collections without editing YAML. You get preset collections (decades, genres, studios, themes), custom builders, bulk list import, and control over where each collection shows up in Plex (Home, Library recommended, Friends). Everything lives in one place and stays in sync with your Plex server.

---

## What you get

- **Preset collections** - 140+ ready-made collections - regional trending, international (K-Dramas, Bollywood, Nordic Noir, French cinema, etc.), decades (1940s through 2020s, plus TV decades), themes (time travel, heists, sports, zombies, vampires, superhero, holiday, noir, biopics, anthologies, and more), awards (Oscar winners, Sundance, critics’ choice), studios (A24, Pixar, Ghibli, Marvel, Disney, HBO, Netflix, BBC, DC, Universal, and more), genres for movies and TV, and content ratings. Pick a preset, choose auto-update (off/daily/weekly), and run it once or on a schedule.
- **Custom builders** - Create collections from filters (genre, year, rating, keywords) without writing config files. Great for “my favorite decade + genre” style lists.
- **Bulk list import** - Paste a list of titles (from IMDb, Letterboxd, Reddit, or anywhere), pick your Plex library, match titles, and create a single collection from the matches. Handy for “best of” lists or shared watchlists.
- **Visibility controls** - Each collection has three checkboxes - **Home**, **Library recommended**, and **Friends**. They map to Plex’s “Manage Recommendations” toggles (Home, Library Recommended, Friends’ Home). Changes apply right away - you don’t have to run the collection again. Tickboxes work both on the preset cards and in the Library Browser.
- **Library Browser** - A live view of all collections on your Plex server. You see posters, counts, and the same Home / Library / Friends checkboxes. Toggle any of them and Plex updates immediately. You can also open each collection in Plex from there.
- **Collapsible sections** - Preset categories (Regional Trending, International & World, Decades, etc.) start minimized. Click a category header to expand or collapse it so you can focus on what you care about.
- **Sync mode** - For non-trending presets you can choose **Append (Grow)** (only add new items, never remove) or **Sync (Strict)** (add new and remove items that are no longer on the list). Trending presets always use strict sync so the list stays current.
- **Delete** - Remove a collection from the app and optionally from Plex in one go.

---

## What you need

- **Plex** - URL and token in Settings. Required for creating collections and for the Library Browser.
- **TMDB API key** - Required for preset and custom collections (metadata, discovery). Add it in Settings.
- **Plex Pass** (optional but recommended) - Needed for collection visibility in “Manage Recommendations” (Home, Library recommended, Friends). Server 1.22.3+ is recommended for that feature.

For installation help, see [Installation & Updates](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide).

---

## How it works

### Auto-Manager tab

1. **Your Custom Collections** - If you’ve created custom builders or imported lists, they appear at the top. Each card has auto-update, sync mode, visibility checkboxes, and Run Now / Delete.
2. **Preset categories** - Below that, categories (Regional Trending, International & World, Decades, Themes & Vibes, Awards & Acclaim, Studios & Networks, Genre (Movies), Genre (TV), Content Ratings) are collapsed by default. Click a category header (e.g. “Themes & Vibes”) to expand it and see the presets inside.
3. **Per preset** - Set **Auto-Update** (Off, Daily, Weekly), **Sync Mode** (Append or Sync for non-trending), **Sort By** (for preview order), and **Where it appears in Plex** (Home, Library recommended, Friends). Then click **Run Now** to create or update the collection in Plex. The hint under the checkboxes tells you that in Plex you can go to **Settings -> Manage -> Libraries**, then **Manage Recommendations**, to reorder collections and change options there too.
4. **Visibility** - When you change any of the three checkboxes (Home, Library recommended, Friends), the app saves your choice and pushes it to Plex right away. You don’t need to click Run Now again for visibility to update.

### Library Browser tab

1. Click the **Library Browser** tab to load a live list of all collections on your Plex server (Movies and TV libraries).
2. Each collection shows a poster, item count, library name, and the same three checkboxes (Home, Library recommended, Friends). The checkboxes reflect what Plex currently has; changing them updates Plex immediately.
3. Click a collection card (outside the checkboxes) to open that collection in Plex in a new tab. Use **Refresh list** if you added or removed collections in Plex and want the list to update.

### Manage Recommendations in Plex

In Plex go to **Settings -> Manage -> Libraries**, then open **Manage Recommendations** for a library (e.g. Movies). There you can reorder collections and change which ones appear on Home, Library, or Friends. SeekAndWatch’s checkboxes set the same options via the API so you can do it from the app or in Plex, whichever you prefer.

---

## How to use it

### Run a preset collection

1. Open **Plex Collections** in the sidebar.
2. Expand a category (e.g. Decades) by clicking its header.
3. Find a preset (e.g. The 1980s), set Auto-Update and Sync Mode if you want, and check at least one visibility option (Home, Library recommended, Friends).
4. Click **Run Now**. The app creates the collection in Plex (or updates it if it already exists) and applies visibility. Refresh **Manage Recommendations** in Plex to see it there and reorder if you like.

### Change where a collection appears (visibility)

- **On a preset card** - Change the Home / Library recommended / Friends checkboxes. The app saves and pushes to Plex immediately.
- **In the Library Browser** - Same thing - toggle the checkboxes on any collection; Plex updates right away.

No need to run the collection again just to change visibility.

### Create a collection from a pasted list

1. Click **Import List** on the Plex Collections page.
2. Paste your list of titles (one per line or comma-separated), choose the Plex library (Movies or TV), and click **Analyze**.
3. Review the matches, fix any that are wrong or missing, then create the collection. The new collection appears under Your Custom Collections.

### Custom builder collection

1. Click **Custom Builder** (or the builder button on the Plex Collections page).
2. Set your filters (genre, year, rating, keywords, etc.), pick the library and collection name, then build. The collection is created in Plex and listed under Your Custom Collections with the same visibility and sync options as presets.

### Delete a collection

On the preset or custom card, click **Delete**. You can remove it from the app only or from both the app and Plex. If you only use the app, you can delete the collection in Plex separately.

---

## Tips

- **Trending presets** (e.g. Trending USA, UK, Canada) always use strict sync so the list matches what’s popular right now. Other presets let you choose Append vs Sync.
- **Collapsed sections** - If you only use a few categories, leave the rest collapsed so the page is easier to scan.
- **Library Browser** - Use it to fix visibility for collections you created outside the app (e.g. in Plex or another tool). The checkboxes there update Plex the same way as on the preset cards.
- **First run** - The first time you run a preset, the collection is created in Plex. After that, Run Now updates the items (and visibility if you changed it). Visibility changes you make with the checkboxes don’t require Run Now.

---

## List-based vs discover-based collections

Tools that pull from **curated public lists** (Trakt, TMDB, Letterboxd, MDBList, etc.), not from raw “discover” API filters. A list is a fixed set of titles chosen by a person or community, so quality is high. Discover (genre + keyword filters) is noisier, especially for TV where TMDB has no “Horror” genre and keyword-based results can mix in kids/family content.

SeekAndWatch supports both -

- **Discover-based presets** - The built-in presets (decades, genres, themes, etc.) use TMDB’s discover API with genre/keyword/date filters. Great for broad categories; for some niches (e.g. Horror TV) results can include unwanted titles. We tighten those with exclusions (e.g. no Animation/Kids/Family) and quality bars (vote count, rating).
- **List-based presets** - You can use a **TMDB list ID** so a collection is built from a single curated list instead of discover. Same idea as “add a public list” - the list author defines the exact titles, so you get their curation. To do this you add a preset that has `tmdb_list_id` set (and no `tmdb_params`). Custom builders and the app’s preset system support this; the sync logic fetches from `https://api.themoviedb.org/3/list/{list_id}` and uses those items. If a discover preset (e.g. Horror TV) gives you too many wrong titles, find or create a good “Horror TV” list on TMDB, copy its list ID from the list URL, and use a list-based preset with that ID for better results.

---

## Troubleshooting

- **Collection doesn’t show in Manage Recommendations** - Make sure you have Plex Pass and a recent server (1.22.3+). In Plex go to **Settings -> Manage -> Libraries**, then **Manage Recommendations** for that library. You can reorder and change options there. Our checkboxes try to set the same thing via the API; if your server doesn’t accept it, use Plex’s UI once and the collection will appear.
- **Visibility checkboxes don’t seem to change Plex** - Refresh the Manage Recommendations page in Plex (reopen it or reload). The app sends the update; Plex sometimes needs a refresh to show it.
- **Duplicate or wrong collection** - If a preset has the same name as an existing Plex collection, the app updates that one. If the existing one is a “smart” (filter-based) collection, the app creates a new regular collection with “ (SeekAndWatch)” added to the name so it doesn’t overwrite the smart one.
- **Run Now fails** - Check Settings - Plex URL and token, TMDB API key. Check the app logs (Settings -> Logs) for errors. If you use a custom builder, make sure the filters return at least some titles.

---

## Quick reference

| Thing | Where |
|-------|--------|
| Preset collections | Plex Collections -> expand a category -> pick a preset -> Run Now |
| Visibility (Home / Library / Friends) | Checkboxes on each preset card or in Library Browser; saves and applies to Plex immediately |
| Reorder / change options in Plex | Plex -> Settings -> Manage -> Libraries -> Manage Recommendations |
| Live view of Plex collections | Plex Collections -> Library Browser tab |
| Import a list of titles | Plex Collections -> Import List |
| Custom filters (genre, year, etc.) | Custom Builder (sidebar or button on Plex Collections) |
| Delete a collection | Delete on the preset or custom card (from app and/or Plex) |

---

## Related

- [Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery) - Find movies and TV shows to add to your collections
- [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) / [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr) - Request content and manage your library
- [Kometa Config Builder](https://github.com/softerfish/seekandwatch/wiki/Kometa-Config-Builder-Guide) - Build Kometa config files with overlays