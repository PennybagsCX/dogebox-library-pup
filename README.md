# 📚 Dogebox Library

<p align="center"><img src="library/logo.png" width="110" alt="Library pup logo"></p>

**One URL for your Dogebox media stack.** Unified search across movies + shows, one-click add, curated starter packs, IMDb/Trakt watchlist import, and a free-text "Tonight" recommender — all on top of the existing Radarr + Sonarr + Prowlarr + Jellyfin apps you already have.

> **Latest:** v0.0.10 — metadata-only bump (manifest `upstreamVersions` corrected: Prowlarr 2.x, matching the packaged `pkgs.prowlarr`; Radarr 6.x / Sonarr 4.x / Jellyfin 10.x verified against the running box). No code changes since v0.0.9.
>> 
>> Previous: v0.0.9 — startup staging is overwrite-safe: read-only files left in `/storage/config` (e.g. by a backup restore) no longer crash-loop `library.service` (`rm -f` before copy). No new indexers, no new download pipeline, no new library model.

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
3. Click the pup card → set the API keys for Radarr/Sonarr/Prowlarr/Jellyfin (the same keys shown in each app's own WebUI under Settings → General → API Key), OR edit `/storage/config/upstreams.json` directly on the box.
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
              qBittorrent (direct exec since 0.0.6)
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
- `GET /random` — HTML random pick (with unwatched filter)
- `GET /api/search?q=...` — JSON `{movies: [...], series: [...]}`
- `GET /api/tonight?q=...` — JSON `{query, genres, decade, results: [...]}`
- `GET /api/random` — JSON random pick
- `GET /api/status` — JSON snapshot of all upstream counts
- `GET /api/users` — JSON Jellyfin user list
- `GET /static/live.js` — JS for the live search dropdown
- `GET /debug/test` — upstream connectivity self-test
- `GET /debug/qb` — qBittorrent reachability probe
- `POST /add/movie/` (id=tmdbId) — add a movie to Radarr
- `POST /add/series/` (id=tvdbId) — add a series to Sonarr
- `POST /pack` (pack=name) — bulk-add a starter pack
- `POST /import` (url=...) — bulk-import an IMDb list URL

## Verified on the box (2026-10-06, audit)

- Container `container@pup-9cbdf7251ae24274527510885f41b800.service` active; web UI reachable on the dogebox-mapped port
- `GET /api/status` → `{"movies_count": 15, "series_count": 0, "jf_users": 1, "prowlarr_indexers_total": 1, "prowlarr_indexers_enabled": 1}`
- `GET /api/tonight?q=funny 90s` → parsed `genres: ["comedy"]`, `decade: "90s"`, ranked results returned
- `GET /search?q=inception` → results page rendered (poster hits found)
- Starter packs live: Public Domain Essentials, Documentary Hour, Classic Sci-Fi, Animated Shorts, Classic TV Pilots
- Deployed `library-web.py` on the box is byte-identical (sha256) to this repo's `library/library-web.py`

Historical verification (2026-09-14, pre-audit): search `inception` → found `Inception (2010) tmdbId=27205`; search `breaking bad` → found `Breaking Bad (2008) tvdbId=81189`; POST `/add/movie/` + `/add/series/` landed in Radarr/Sonarr and re-adding was idempotent ("Already in your library"); cleanup restored 0 movies / 0 series.

## License

MIT for the packaging. ClamAV/Radarr/Sonarr/Prowlarr/Jellyfin are GPL/commercial — this pup only talks to them via REST.

## Host setup note: archive.org multi-format imports (2026-09-18)

Archive.org **item torrents** ship every derivative format of a title (`mp4`/`ogv`/`flv`/`mov`/`wmv`/`m4v` + `_meta.*` + previews). Jellyfin renders **one library entry per video file**, so wholesale-copying these folders into the media dir creates duplicate entries (and `*512kb*` derivatives become separate bogus titles).

The recommended host-side setup (see wow-20 ops manual §13): the `radarr-to-jellyfin` sync timer carries a **keep-one-video prune** (largest mainstream-container file per folder, AppleDouble-aware — the audit box runs this exact prune), and `qb-to-arrs` routes `SxxEyy`/`Season N` paths to Sonarr with everything else going to Radarr (also verified running on the audit box). Without that prune, every archive.org download will re-create duplicates in Jellyfin.
