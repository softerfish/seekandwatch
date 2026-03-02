# Welcome to SeekAndWatch

Hey! Welcome to the SeekAndWatch wiki. Whether you're just getting started or you've been using it for a while, this is your go-to spot for everything SeekAndWatch.

## What is SeekAndWatch?

SeekAndWatch is a powerful tool that helps you discover, organize, and manage your Plex media library. Think of it as your personal media curator that works alongside Plex to make your library smarter and more organized.

### What Can It Do?

- **Smart Discovery** - Find movies and TV shows based on what you like; seeds, filters, and I'm Feeling Lucky
- **Radarr & Sonarr** - Add movies/shows from the app, view your libraries on the Media page, use them for "owned" filtering in Smart Discovery
- **SeekAndWatch Cloud** (beta) - Hosted option so friends and family can request from your Plex server without needing access to your apps; you approve or deny in the local app; requests sync to Radarr or Sonarr. Zero port forwarding.
- **Plex Collections** - Preset and custom collections, visibility (Home / Library / Friends), Library Browser, bulk import
- **Kometa Integration** - Visual builder for Kometa config files (no YAML editing required!)
- **Tautulli Integration** - See what's trending on your server
- **Blocklist Management** - Keep track of what you don't want to see
- **Background Scanning** - Plex and Radarr/Sonarr scanners so recommendations know what you already have

---

## Quick Start

### New to SeekAndWatch?

1. **Installation** - Get SeekAndWatch up and running on your system
   - See: [Installation & Updates Guide](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide)

2. **Initial Setup** - Configure your connections and API keys
   - Plex URL and Token (optional but recommended for ownership filtering)
   - TMDb API Key (required for Smart Discovery; free, takes 2 minutes)
   - Optional: Radarr/Sonarr URL + API key to request content from the app
   - Optional: OMDB, Tautulli for extra features

3. **First Discovery** - Try [Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery) to find something new to watch

4. **Optional** - Add [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) and [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr) in Settings to request movies/shows from the app and view your libraries on the Media page

5. **Build collections**: Use [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections) for presets and visibility, or the [Kometa Config Builder](https://github.com/softerfish/seekandwatch/wiki/Kometa-Config-Builder-Guide) for overlays and config files

---

## Documentation

### Getting Started
- **[Installation & Updates](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide)** - How to install, update, and troubleshoot SeekAndWatch
  - Installation process
  - One-click updater (manual installs)
  - Unraid App Store installation
  - Troubleshooting common issues

### Smart Discovery
- **[Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery)** - Find movies and TV shows based on what you like
  - Features, how it works, setup
  - What you need (TMDB key, seeds, optional Plex/Radarr/Sonarr)
  - How to use it, troubleshooting

### Radarr & Sonarr
- **[Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr)** - Add movies from the app, view your Radarr library, ownership for Smart Discovery
- **[Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr)** - Add TV shows from the app, view your Sonarr library, ownership for Smart Discovery

### Plex Collections
- **[Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections)** - Presets, visibility (Home / Library / Friends), Library Browser, custom builders, bulk import
  - What you get, what you need, how it works
  - How to run presets, change visibility, create from lists, troubleshoot

### SeekAndWatch Cloud
- **[SeekAndWatch Cloud](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud)** - Let friends request movies and TV shows without access to your apps
  - How it works, quick start, troubleshooting
  - **[Server Owners Guide](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud-Server-Owners-Guide)** - All settings (local app and web app), webhook setup, Plex sync, inviting friends
  - **[Friends Guide](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud-Friends-Guide)** - How to register, browse, request, and check status

### Kometa Config Builder
- **[Kometa Config Builder Guide](https://github.com/softerfish/seekandwatch/wiki/Kometa-Config-Builder-Guide)**: Complete guide to using the visual Kometa builder
  - Features overview, step-by-step usage, library templates
  - Import/export configs, performance indicators, troubleshooting
- **[Kometa YAML Spacing Reference](https://github.com/softerfish/seekandwatch/wiki/Kometa-YAML-Spacing-Reference)** - YAML spacing and formatting reference if you edit configs by hand

---

## Key Features

### Smart Discovery

Find your next favorite movie or show. Pick seeds (titles you like), set filters, and get personalized recommendations -or use I'm Feeling Lucky for random picks. Things you already have (Plex, Radarr, Sonarr) are filtered out. See [Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery).
- Genre, year, rating, Certified Fresh
- Future releases only, international & obscure
- Similar content and TMDB recommendations
- Load more without regenerating

### Media Page & Radarr/Sonarr

View and manage your requested and downloaded content. Connect Radarr and Sonarr in Settings to add movies/shows from Smart Discovery (or elsewhere), open titles in Radarr/Sonarr, toggle monitored, and run search/refresh. Enable the Radarr & Sonarr Scanner so those libraries are used for "owned" filtering in Smart Discovery. "Owned" means in Radarr/Sonarr **and** having at least one file (movie or episode files); titles that are in Radarr/Sonarr but have no file yet are not considered owned. See [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) and [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr).

### Plex Collections

- **Preset collections** - 140+ ready-made lists (decades, genres, studios, themes, international, awards). Collapsible categories so you can focus on what you use.
- **Visibility**: Home, Library recommended, and Friends checkboxes on every collection; changes apply to Plex right away (no need to run the collection again).
- **Library Browser** - Live view of all collections on your Plex server with the same visibility toggles. In Plex you can reorder and change options under Settings -> Manage -> Libraries -> Manage Recommendations.
- **Custom builders**: Create collections from filters (genre, year, rating, keywords) without YAML.
- **Bulk list import** - Paste a list of titles, match to Plex, and create one collection. Great for shared or “best of” lists.
- **Sync mode**: Append (grow only) or Sync (strict) per preset. Delete from the app and optionally from Plex.

See [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections) for the full guide.

### Kometa Config Builder

A visual tool that generates Kometa `config.yml` files without writing YAML:
- Point-and-click interface
- Library templates for quick setup
- Import existing configs
- Compare current vs saved configs
- Performance estimates
- Undo/redo support

### Dashboard

Your command center:
- Trending content on your server (Tautulli integration)
- Quick access to all features
- System status and updates
- Recent activity

---

## Common Use Cases

### "I want to find something new to watch"
-> Use **Smart Discovery** with your preferred filters

### "I want to organize my Plex library"
-> Use **Plex Collections** for preset and custom collections (visibility, Library Browser, import lists), or the **Kometa Config Builder** for overlays and config files

### "I want to see what's popular on my server"
-> Check the **Dashboard** for Tautulli trending content

### "I want to see my Radarr/Sonarr library in one place"
-> Open the **Media** page (and add Radarr/Sonarr in Settings if you haven't)

### "I want to import someone else's Kometa config"
-> Use the **Import Config** feature in the Kometa Builder

### "I want friends/family to request without access to my apps"
-> Use **SeekAndWatch Cloud** (beta): they request on the cloud site; you approve or deny in the local app; approved requests sync to Radarr or Sonarr. See [SeekAndWatch Cloud](https://github.com/softerfish/seekandwatch/wiki/SeekAndWatch-Cloud).

### "I want to block certain content from recommendations"
-> Use the **Blocklist** feature

### "I want to add movies or TV to Radarr/Sonarr from the app"
-> Configure **Radarr** and **Sonarr** in Settings, then use Request from Smart Discovery or the Media page. See [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr) and [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr).

---

## Getting Help

### Found a Bug?

If something isn't working as expected:
1. Check the [Installation & Updates](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide) troubleshooting section
2. Check [Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery), [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections), [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr), or [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr) if it's about those features
3. Check the [Kometa Builder](https://github.com/softerfish/seekandwatch/wiki/Kometa-Config-Builder-Guide) or [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections) troubleshooting sections
4. Review your settings and API keys
5. Check the application logs

### Need More Help?

- **GitHub Issues** - Report bugs or request features
- **Reddit** - Community discussions and support
- **Documentation** - Check the guides above first

---

## Tips & Best Practices

### For Best Results

1. **Keep API Keys Updated** - Expired keys will break features
2. **Save Your Work** - Especially in the Kometa Builder, save frequently
3. **Use Templates** - Save library configurations as templates for reuse
4. **Review Before Saving** - Always check the generated YAML before using it
5. **Backup Your Config** - Export your Kometa config before major changes

### Performance Tips

- Use background scanning during off-hours
- Limit the number of collections if performance is slow
- Check the performance indicator in the Kometa Builder
- Adjust cache settings if needed

---

## What's Next?

Ready to dive in? Here's a suggested path:

1. **Install SeekAndWatch** - [Installation & Updates](https://github.com/softerfish/seekandwatch/wiki/Installation-and-Update-Guide)
2. **Configure Settings** - TMDB key (required), Plex/Radarr/Sonarr and other keys as needed
3. **Try Smart Discovery** - [Smart Discovery](https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery)
4. **Optional: Radarr/Sonarr** - [Radarr](https://github.com/softerfish/seekandwatch/wiki/Radarr), [Sonarr](https://github.com/softerfish/seekandwatch/wiki/Sonarr)  - request content and view libraries on the Media page
5. **Build collections** - [Plex Collections](https://github.com/softerfish/seekandwatch/wiki/Plex-Collections) for presets and visibility; [Kometa Config Builder](https://github.com/softerfish/seekandwatch/wiki/Kometa-Config-Builder-Guide) for templates, imports, comparisons

---

## About This Wiki

This wiki is maintained by the SeekAndWatch community. If you find something that's unclear or outdated, feel free to suggest improvements or submit a pull request.

**Happy watching!**

---

### Making links work on the GitHub wiki

The links in this file use **full wiki URLs** (e.g. `https://github.com/softerfish/seekandwatch/wiki/Smart-Discovery`). They work when this content is on the GitHub wiki as long as the target wiki pages exist.

When you create a new wiki page on GitHub, the URL slug is the page title with spaces -> hyphens. So create pages with these exact titles and the links will work:

| Wiki slug | Create wiki page titled |
|-----------|-------------------------|
| **Welcome-to-SeekAndWatch** | Home / welcome page |
| **Installation-and-Update-Guide** | Installation & Update Guide |
| **SeekAndWatch-Cloud** | SeekAndWatch Cloud |
| **SeekAndWatch-Cloud-Server-Owners-Guide** | SeekAndWatch Cloud - Server Owners Guide |
| **SeekAndWatch-Cloud-Friends-Guide** | SeekAndWatch Cloud - Friends Guide |
| **Kometa-Config-Builder-Guide** | Kometa Config Builder Guide |
| Smart-Discovery | Smart Discovery |
| Radarr | Radarr |
| Sonarr | Sonarr |
| Plex-Collections | Plex Collections |
| Kometa-YAML-Spacing-Reference | Kometa YAML Spacing Reference |

Copy the content from the matching file in the repo `documentation/` folder into the wiki page with the matching title (e.g. Installation & Update Guide, Smart Discovery, Radarr).