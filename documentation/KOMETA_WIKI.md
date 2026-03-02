# Kometa Config Builder Guide

So you want to set up Kometa but the thought of writing YAML makes your head spin? You're in the right place. This builder takes all that complexity and turns it into a simple point-and-click interface. No more guessing at indentation or wondering if you put that comma in the right spot.

## What is This Thing?

The Kometa Config Builder is a visual tool that generates a clean `config.yml` file for Kometa without you having to touch a single line of YAML (unless you want to, of course). It's basically a fancy form that asks you what you want, then spits out the config file ready to use.

Think of it as training wheels for Kometa. You can always graduate to editing YAML directly later, but this gets you up and running fast.

---

## Getting Started

### First Things First

Before you dive in, you'll need:

1. **Plex URL and Token** - Your Plex server details. These will copy over from your settings here
2. **TMDb API Key** - Free to get, takes about 2 minutes
3. **A Kometa installation** - Obviously, but worth mentioning

### The Three Tabs

The builder is split into three main sections:

**Tab 1: Core Config** - The boring but necessary stuff. Plex connection, TMDb key, all that jazz.

**Tab 2: Global Settings** - How Kometa behaves overall. Caching, sync modes, that kind of thing.

**Tab 3: Libraries** - The fun part. Pick your libraries and choose what collections and overlays you want.

---

## Features Overview

### The Basics

**Save Progress** - Your work is automatically saved to the database, but clicking this button ensures everything is synced. Do it often, especially before closing the page.

**Live YAML Preview** - Watch your config file build in real-time on the right side as you make changes. It's pretty satisfying, honestly.

**Sample Overlay Preview** - Below the config, a sample poster shows how your selected overlays will look. For Movies you see one poster; for TV you see separate Season and Episode previews, each the same size as the movie poster, so you can judge badge placement and readability before copying the config.

### The Cool Stuff

#### 📚 Library Templates

Ever set up a perfect library configuration and thought "man, I wish I could just copy this to my other libraries"? Well, now you can.

**How it works:**
1. Configure a library exactly how you want it (collections, overlays, all the settings)
2. Click the **Templates** button in the header
3. Give it a name like "Movies - Full Setup" or "TV Shows - Minimal"
4. Click Save Template

Now when you're setting up another library, just open Templates, find your saved template, and click Apply. Boom, all your settings are copied over. You can still tweak things after applying if needed.

Templates are stored in your SeekAndWatch database.

#### ↶↷ Undo/Redo

Made a mistake? Changed your mind? No worries. The builder tracks your last 50 changes, so you can undo or redo to your heart's content.

Just click the Undo or Redo buttons in the header. They'll be grayed out when there's nothing to undo/redo, which is pretty intuitive.

**Pro tip:** The history saves automatically when you add/remove libraries or change variables. So feel free to experiment as you can always go back.

#### 🔍 Comparison Mode

Want to see what changed between your current config and what you saved? Click the **Compare** button.

It shows both configs side-by-side so you can spot the differences. Super handy when you're tweaking things and want to make sure you didn't break anything.

#### Performance Indicators

This one's pretty neat. As you select collections and overlays, a blue box appears at the top showing:

- **Estimated Collections** - How many collections Kometa will actually create (some options create multiple collections)
- **Estimated Runtime** - Rough guess at how long Kometa will take to run

The estimates aren't perfect, but they give you a good idea. If you see "Estimated Collections: 500" and you only wanted 20, you might want to dial it back a bit.

You can dismiss the indicator if it's in your way - just click the ×.

**How the Estimates are Calculated:**

The build time estimation uses a two-step process:

1. **Collection Multipliers**: Each collection type creates multiple actual collections based on your library content. The multipliers used are:
   - Genre: 20 collections
   - Franchise: 15 collections
   - Universe: 10 collections
   - Actor: 50 collections
   - Director: 30 collections
   - Streaming Services: 20 collections
   - Studio: 25 collections
   - Release Year: 30 collections
   - Decade: 10 collections
   - Content Rating (US): 6 collections
   - Other types: 1 collection (default)

2. **Build Time Formula**: The estimated runtime is calculated as:
   ```
   Estimated Seconds = (Estimated Collections × 3) + (Total Overlays × 1.5)
   ```
   - Each estimated collection takes approximately **3 seconds** to process
   - Each overlay takes approximately **1.5 seconds** to process

**Example:** If you select Genre (20 collections) and Actor (50 collections) with 2 overlays:
- Estimated Collections: 20 + 50 = 70
- Estimated Runtime: (70 × 3) + (2 × 1.5) = 213 seconds = **3m 33s**

Note: These multipliers are rough estimates based on typical library sizes. Your actual results may vary depending on your specific library content.

#### 📥 Import from URL

Found an awesome config on GitHub? Want to use someone else's setup as a starting point? The Import from URL feature has you covered.

**How to use it:**
1. Find a `config.yml` file online (GitHub raw links work great)
2. Click **Import from URL** in the header
3. Paste the URL
4. Click Import

The builder will parse the YAML and extract the libraries, collections, and overlays. Then you can customize it however you want.

**Note:** The parser is pretty basic, so complex configs might not import perfectly. But it handles most standard setups just fine.

---

## Walkthrough: Building your first config

### Connect your services

Head to **Tab 1: Core Config** and fill in:

**Plex URL**
- Usually something like `http://192.168.1.50:32400`
- Can be local IP or domain name
- Don't forget the `http://` or `https://` part

**Plex Token**
- This is the tricky one. Easiest way: Open any movie/show in Plex web, right-click -> Inspect -> Network tab -> Look for any request -> Check headers for `X-Plex-Token`
- Or use [plex.tv/api](https://www.plex.tv/api) while logged in
- It's a long string of letters and numbers

**TMDb API Key**
- Go to [themoviedb.org](https://www.themoviedb.org/settings/api)
- Sign up (free) if you haven't
- Request an API key (also free)
- Copy and paste it here

### Set global preferences

Switch to **Tab 2: Global Settings**. Here's what matters:

**Cache Enabled** - Leave this on True. It makes Kometa way faster on subsequent runs.

**Sync Mode** - This is important:
- **Append** - Only adds items to collections, never removes them. Safer, but collections can grow forever.
- **Sync** - Adds AND removes items based on rules. Keeps collections clean, but might remove things you want to keep.

**Minimum Items** - Don't create a collection unless it has at least this many items. Prevents empty or tiny collections.

The other settings are pretty self-explanatory. Defaults work fine for most people.

### Add your libraries

Now the fun part. Go to **Tab 3: Libraries**.

1. Click the refresh button (🔄) next to "Library" to load your Plex libraries
2. Select a library from the dropdown
3. Pick the type (Movies, TV Shows, or Anime)
4. Check the boxes for collections and overlays you want

**Start small!** I know it's tempting to check everything, but that can create hundreds of collections. Pick a few things you actually care about first.

### Customize (the important part)

See that gear icon next to each option? Click it. This is where the magic happens.

**Quick Settings** - The common stuff:
- **Limit** - Max items in the collection (e.g., "Top 50" instead of everything)
- **Sort By** - How to order items (newest, most popular, etc.)
- **Include/Exclude** - Filter to specific items (this is huge!)

**The Include/Exclude trick:**
Say you enable "Streaming Services" but don't want collections for every service under the sun. Click the gear, and in the **Include** field, type: `Netflix, Disney+, Hulu`

Now Kometa will only create collections for those three services instead of 50+. Same works for genres, studios, actors - anything that creates multiple collections.

**Advanced Variables** - For the power users. If you know Kometa variables, you can add them here. Check the [Kometa Wiki](https://kometa.wiki) for what's available.

### Save and export

1. Click **💾 Save Progress** (do this often!)
2. Copy the YAML from the right side
3. Save it as `config.yml` in your Kometa config folder
4. Run Kometa and watch the magic happen

---

## Using Your Config with Kometa

### Where to Put the File

Your Kometa config folder depends on how you installed it:

**Docker:**
- Usually something like `/config/kometa/config.yml`
- Or wherever you mapped your Kometa config volume

**Native Install:**
- Typically `~/.config/kometa/config.yml` on Linux
- Or `%APPDATA%\kometa\config.yml` on Windows

**Unraid:**
- Usually in your appdata folder, like `/mnt/user/appdata/kometa/config.yml`

### Running Kometa

However you normally run Kometa. It should pick up the config automatically.

### First Run Tips

- **Be patient** - The first run can take a while, especially if you selected a lot of collections
- **Check the logs** - Kometa will tell you if something's wrong
- **Start small** - Test with one library and a few collections first, then expand

---

## Common Issues and Fixes

### "No libraries found" when clicking refresh

**Problem:** The library dropdown stays on "Loading libraries..."

**Fix:**
- Double-check your Plex URL and token in Tab 1
- Make sure the URL is accessible from where SeekAndWatch is running
- Try the token in a browser: `http://YOUR_PLEX_URL/library/sections?X-Plex-Token=YOUR_TOKEN`

### Config generates but Kometa errors

**Problem:** You copied the config, but Kometa throws errors when running.

**Common causes:**
- **Missing required fields** - Make sure Plex URL, token, and TMDb key are filled in (not "INSERT_HERE")
- **Invalid YAML** - The builder should prevent this, but check for weird characters
- **Library name mismatch** - The library name in the config must match exactly what Kometa sees

**Fix:**
- Check Kometa's error message - it usually tells you what's wrong
- Compare your config to a working example
- Make sure all your libraries are spelled correctly

### Too many collections created

**Problem:** You enabled "Genres" and now have 50+ genre collections you don't want.

**Fix:**
- Use the Include field! Click the gear next to Genres, and in Include, list only the genres you care about: `Action, Comedy, Horror, Sci-Fi`
- Or use Exclude to blacklist genres you hate
- Set a higher Minimum Items so small collections don't get created

### Collections not updating

**Problem:** Kometa runs, but collections stay the same.

**Fix:**
- Check your Sync Mode - if it's set to "Append" globally, collections only grow, never shrink
- Make sure Kometa has permission to modify your Plex libraries
- Check that your Plex token has admin/library edit permissions

### Import from URL not working

**Problem:** You paste a URL but nothing happens, or it errors.

**Fix:**
- Make sure it's a direct link to the raw YAML file (GitHub raw links work: `https://raw.githubusercontent.com/...`)
- The file needs to be publicly accessible (no authentication required)
- Check your browser console for errors (F12 -> Console tab)
- The parser is basic - complex configs with custom variables might not import perfectly

### Undo/Redo not working

**Problem:** You click Undo but nothing happens.

**Fix:**
- Undo only works for changes made in the current session
- It tracks: adding/removing libraries, changing variables
- It doesn't track: typing in text fields, changing dropdowns (those update immediately)
- If you closed the page and came back, history is reset

### Performance estimate seems wrong

**Problem:** The estimate says 500 collections but you only see 50.

**Fix:**
- The estimate uses multipliers (e.g., "Genres" = ~20 collections, "Actors" = ~50)
- These are rough guesses based on typical libraries
- Your actual library might have fewer genres/actors, so fewer collections
- It's just an estimate - the real number depends on your library content

**Understanding the Calculation:**
- Collection multipliers are fixed values (Genre=20, Actor=50, etc.) regardless of your library size
- Build time = (Estimated Collections × 3 seconds) + (Overlays × 1.5 seconds)
- If your library has fewer unique items (e.g., only 5 genres instead of 20), Kometa will create fewer collections than estimated
- The estimate is intentionally conservative to help you avoid selecting too many options at once

### Template not applying correctly

**Problem:** You apply a template but settings don't match.

**Fix:**
- Templates save collections, overlays, and template variables
- They don't save the library name or type (you pick those when applying)
- Make sure you're applying to the right library type (movie template to movie library)
- Some variables might need adjustment if your new library is different

---

## Pro Tips

### Start Small, Expand Later

I can't stress this enough. Pick 3-5 collection types you actually care about, get those working, then add more. It's way easier to debug when you're not dealing with 200 collections at once.

### Use Include/Exclude Liberally

This is the secret sauce. Don't want collections for every streaming service? Include only the ones you use. Don't want every genre? Include your favorites. This keeps your library organized and Kometa runs faster.

### Save Progress Often

The auto-save is nice, but clicking "Save Progress" manually ensures everything is synced. Especially do this before:
- Closing the page
- Making big changes
- Testing your config

### Test with One Library First

Set up one library perfectly, test it with Kometa, make sure it works. Then use Templates to apply that setup to other libraries. Much faster than configuring each one from scratch.

### Check the Performance Indicator

If that blue box says "Estimated Collections: 1000", you might want to reconsider your choices. Unless you really want 1000 collections, in which case, go for it. But at least you know what you're getting into.

### Read Kometa's Docs

The builder covers the basics, but Kometa can do way more. Check the [official Kometa wiki](https://kometa.wiki) for advanced features, custom variables, and all the cool stuff you can do.

### Backup Your Config

Before making big changes, copy your current config. Or use the Comparison feature to see what changed. Better safe than sorry.

---

## What the Builder Doesn't Do

Just to set expectations, the builder focuses on the most common use cases. It doesn't cover:

- **Custom collection files** - If you write your own collection builders, you'll need to add those manually
- **Operations** - Things like deleting items, moving files, etc. (those go in a separate file anyway)
- **Metadata** - Metadata operations are separate from collections
- **Every possible variable** - There are hundreds of Kometa variables. The builder covers the common ones, but you can always add more in the Advanced Variables section

For those advanced features, you'll need to edit the YAML directly or check the Kometa wiki.

---

## Getting Help

If you run into issues:

1. **Check this guide first** - Most common problems are covered above
2. **Check Kometa's logs** - They usually tell you exactly what's wrong
3. **Use Comparison mode** - See what changed between working and broken configs
4. **Start fresh** - Sometimes it's faster to rebuild than debug
5. **Ask the community** - Reddit, Discord, GitHub - people are usually happy to help

---

## Final Thoughts

The builder is meant to make Kometa accessible. You don't need to be a YAML expert to get great collections and overlays. Start simple, experiment, use the features (templates, undo/redo, comparison), and you'll have a killer Plex setup in no time.

And remember: you can always export your config, tweak it manually, and re-import it. The builder isn't a prison - it's a starting point.

Happy collecting!