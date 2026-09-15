# 📚 Dogebox Library

<p align="center"><img src="library/logo.png" width="110" alt="Library pup logo"></p>

**One URL for your Dogebox media stack.** Unified search across movies + shows, one-click add, curated starter packs, IMDb/Trakt watchlist import, and a free-text "Tonight" recommender — all on top of the existing Radarr + Sonarr + Prowlarr + Jellyfin apps you already have.

> **Latest:** v0.0.3 — ships all three planned versions: v0.0.1 unified search + starter packs + add, v0.0.2 IMDb watchlist import, v0.0.3 Tonight mood recommender (no external LLM, pure Python heuristic).

## Why

Before Library, finding something to watch on your Dogebox meant opening four WebUIs (Radarr for movies, Sonarr for shows, Prowlarr to know what's indexable, Jellyfin to actually play). Library collapses that to **one URL** (a single dogebox-mapped port):

- **One search box** — type `inception` and you get movies AND shows mixed, with year/runtime/poster
- **One button** — click Add, Radarr/Sonarr queue it, qB downloads it, ClamAV scans it, Jellyfin picks it up
- **Starter packs** — one click to drop in a whole theme (Public Domain Essentials, Documentary Hour, Classic Sci-Fi, Animated Shorts, Classic TV Pilots)
- **Tonight panel** — type "I want something funny from the 90s, not too long" and get ranked recommendations
- **Watchlist import** — paste an IMDb list URL, get bulk-added to Radarr/Sonarr

## Install

1. Pup Store → Manage Sources → add `https://github.com/PennybagsCX/dogebox-library-pup.git`
2. Install **Library**. Note the mapped host port from the dashboard card.
3. Click the pup card → set the API keys for Radarr/Sonarr/Prowlarr/Jellyfin (same ones you have in `credentials.local.md`), OR edit `/storage/config/upstreams.json` directly on the box.
4. Open the new URL — done.

## How it works

```
  ┌─────────────────────────────────────────────────────────────┐
  │                  Dogebox Library :9100                       │
  │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐       │
  │  │ /api/search  │   │ /api/tonight │   │ /api/status  │      │
  │  └─────────────┘   └─────────────┘   └─────────────┘       │
  │       │                  │                  │               │
  │       ▼                  ▼                  ▼               │
  │  Radarr lookup     Radarr+Sonarr       live counts       │
  │  Sonarr lookup     keyword/genre/      movies/shows/      │
  │  IMDb list parser  decade scoring     Jellyfin users      │
  │                                      quarantine events   │
  └─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              (existing) Radarr/Sonarr/Prowlarr/Jellyfin
                          │
                          ▼
              qBittorrent (in bubblewrap sandbox)
                          │
                          ▼
              ClamAV pup (real-time + hourly scans)
                          │
                          ▼
              radarr-to-jellyfin timer → Jellyfin library
```

Library is a pure proxy: no new indexer, no new download pipeline, no new library model. Everything goes through the APIs the existing apps already expose.

## Configuration

The pup's only config file is `/storage/config/upstreams.json`:

```json
{
  "radarr":   {"url": "http://10.0.0.98:10003", "key": "<RADARR_API_KEY>"},
  "sonarr":   {"url": "http://10.0.0.98:10004", "key": "<SONARR_API_KEY>"},
  "prowlarr": {"url": "http://10.0.0.98:10006", "key": "<PROWLARR_API_KEY>"},
  "jellyfin": {"url": "http://10.0.0.98:18081", "key": "<JELLYFIN_API_KEY>"}
}
```

Edit on the box (`ssh shibe@10.0.0.98; sudo vi /opt/dogebox/pups/storage/<library-pup-id>/config/upstreams.json`). Restart the pup container after changes.

## API endpoints

- `GET /` — HTML home (status badges, search, starter packs, Tonight form)
- `GET /search?q=...` — HTML results page (movies + shows with poster)
- `GET /tonight?q=...` — HTML ranked recs
- `GET /api/search?q=...` — JSON `{movies: [...], series: [...]}`
- `GET /api/tonight?q=...` — JSON `{query, genres, decade, results: [...]}`
- `GET /api/status` — JSON snapshot of all upstream counts
- `GET /static/live.js` — JS for the live search dropdown
- `POST /add/movie/` (id=tmdbId) — add a movie to Radarr
- `POST /add/series/` (id=tvdbId) — add a series to Sonarr
- `POST /pack` (pack=name) — bulk-add a starter pack
- `POST /import` (url=...) — bulk-import an IMDb list URL

## Verified on the box (2026-09-14)

- Search `inception` → finds `Inception (2010) tmdbId=27205`
- Search `breaking bad` → finds `Breaking Bad (2008) tvdbId=81189`
- Tonight `funny 90s` → returns 5 ranked results with comedy genre hint + decade match
- POST `/add/movie/` with tmdbId=27205 → movie appears in Radarr
- POST `/add/series/` with tvdbId=81189 → series appears in Sonarr
- Re-adding same id → "Already in your library" (idempotent)
- Cleanup → upstream apps back to 0 movies / 0 series

## License

MIT for the packaging. ClamAV/Radarr/Sonarr/Prowlarr/Jellyfin are GPL/commercial — this pup only talks to them via REST.
