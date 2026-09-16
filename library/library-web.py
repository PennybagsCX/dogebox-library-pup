#!/usr/bin/env python3
"""Dogebox Library pup — unified search + add + starter packs + Tonight recommender."""
import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Read the live.js content from a sibling file so heredoc quoting doesn't fight Python
LIVE_JS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live.js")
LIVE_JS = open(LIVE_JS_PATH).read() if os.path.exists(LIVE_JS_PATH) else ""

# ----- Config / upstream endpoints -----
UPSTREAMS_FILE = "/storage/config/upstreams.json"
def _load_upstreams():
    cfg = {}
    try:
        with open(UPSTREAMS_FILE) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = {
            "radarr":   {"url": os.environ.get("RADARR_URL",   "http://10.0.0.98:10003"), "key": os.environ.get("RADARR_KEY",   "")},
            "sonarr":   {"url": os.environ.get("SONARR_URL",   "http://10.0.0.98:10004"), "key": os.environ.get("SONARR_KEY",   "")},
            "prowlarr": {"url": os.environ.get("PROWLARR_URL", "http://10.0.0.98:10006"), "key": os.environ.get("PROWLARR_KEY", "")},
            "jellyfin": {"url": os.environ.get("JELLYFIN_URL", "http://10.0.0.98:18081"), "key": os.environ.get("JELLYFIN_KEY", "")},
        }
    return cfg

def _api_get(base_url, api_key, path, params=None, timeout=8):
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    # Jellyfin uses X-Emby-Token; *arr apps use X-Api-Key. The same key
    # value works for both header names — we send both.
    h = {}
    if api_key:
        h["X-Api-Key"] = api_key
        h["X-Emby-Token"] = api_key
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return 0, str(e)

def _api_post(base_url, api_key, path, body, headers=None, timeout=8):
    url = base_url.rstrip("/") + path
    body_bytes = json.dumps(body).encode("utf-8") if not isinstance(body, (bytes, str)) else (body.encode("utf-8") if isinstance(body, str) else body)
    h = {}
    if api_key:
        h["X-Api-Key"] = api_key
        h["X-Emby-Token"] = api_key
    if headers: h.update(headers)
    h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body_bytes, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return 0, str(e)

def _search_radarr(up, term):
    code, body = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie/lookup", {"term": term, "limit": 24})
    if code != 200: return []
    try: return json.loads(body)
    except Exception: return []

def _search_sonarr(up, term):
    code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series/lookup", {"term": term, "limit": 24})
    if code != 200: return []
    try: return json.loads(body)
    except Exception: return []

def _quality_id(up, kind):
    url_key = "radarr" if kind == "movie" else "sonarr"
    code, body = _api_get(up[url_key]["url"], up[url_key]["key"], "/api/v3/qualityprofile")
    if code != 200: return 1
    try:
        profiles = json.loads(body)
        for p in profiles:
            if "HD" in p.get("name","") and "720" in p["name"] and "1080" in p["name"]:
                return p["id"]
        return profiles[0]["id"] if profiles else 1
    except Exception: return 1

def _root_folder(up, kind):
    url_key = "radarr" if kind == "movie" else "sonarr"
    code, body = _api_get(up[url_key]["url"], up[url_key]["key"], "/api/v3/rootfolder")
    if code != 200: return None
    try:
        arr = json.loads(body)
        return arr[0]["path"] if arr else None
    except Exception: return None

def _already_in_radarr(up, tmdb_id):
    code, body = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie")
    if code != 200: return None
    try:
        for m in json.loads(body):
            if m.get("tmdbId") == tmdb_id: return m
        return None
    except Exception: return None

def _already_in_sonarr(up, tvdb_id):
    code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series")
    if code != 200: return None
    try:
        for s in json.loads(body):
            if s.get("tvdbId") == tvdb_id: return s
        return None
    except Exception: return None

def _add_movie(up, item, default_quality):
    if not item.get("tmdbId"):
        return {"ok": False, "error": "no tmdbId"}
    existing = _already_in_radarr(up, item["tmdbId"])
    if existing:
        # Movie already in Radarr — check if it has a file.
        # If not, Prowlarr was blocked during the initial add.
        # Try archive.org directly using the tmdbId to disambiguate the title.
        if not existing.get("hasFile"):
            title = existing.get("title", item.get("title", ""))
            year = existing.get("year", item.get("year"))
            hits = _search_archive_org(title, year, limit=5)
            if hits:
                top = hits[0]
                ok, err = _add_to_qbittorrent(top["identifier"])
                return {
                    "ok": True, "already": True, "hasFile": False,
                    "archive": True,
                    "identifier": top["identifier"],
                    "archive_downloads": top.get("downloads", 0),
                    "qb_ok": ok, "qb_err": err,
                    "movie": existing,
                }
            # archive.org also drew a blank — return the existing record
            return {"ok": True, "already": True, "hasFile": False, "archive": False, "movie": existing}
        return {"ok": True, "already": True, "hasFile": True, "movie": existing}
    root = _root_folder(up, "movie") or "/storage/media/movies"
    body = {
        "title": item.get("title"),
        "tmdbId": item["tmdbId"],
        "year": item.get("year"),
        "qualityProfileId": default_quality,
        "rootFolderPath": root,
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": True},
    }
    code, resp = _api_post(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie", body)
    return {"ok": code in (200, 201), "code": code, "body": resp[:500]}

def _add_series(up, item, default_quality):
    if not item.get("tvdbId"):
        return {"ok": False, "error": "no tvdbId"}
    existing = _already_in_sonarr(up, item["tvdbId"])
    if existing:
        return {"ok": True, "already": True, "series": existing}
    root = _root_folder(up, "series") or "/storage/media/tv"
    body = {
        "title": item.get("title"),
        "tvdbId": item["tvdbId"],
        "year": item.get("year"),
        "qualityProfileId": default_quality,
        "rootFolderPath": root,
        "monitored": True,
        "addOptions": {"searchForMissingEpisodes": True},
    }
    code, resp = _api_post(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series", body)
    return {"ok": code in (200, 201), "code": code, "body": resp[:500]}

def _import_imdb_csv(up, csv_text, quality):
    lines = csv_text.splitlines()
    header = lines[0].lower() if lines else ""
    start = 1 if "title" in header else 0
    results = []
    for line in lines[start:]:
        parts = line.split("\t") if "\t" in line else line.split(",")
        if len(parts) < 2: continue
        title = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        year = parts[2].strip() if len(parts) > 2 else ""
        if not title: continue
        search = f"{title} {year}".strip()
        radarr_res = _search_radarr(up, search)
        if radarr_res:
            m = radarr_res[0]
            if m.get("year") and (not year or str(m["year"]) == year):
                r = _add_movie(up, m, quality)
                results.append({"input": search, "kind": "movie", "added": r.get("ok"), "title": m.get("title")})
                continue
        sonarr_res = _search_sonarr(up, search)
        if sonarr_res:
            s = sonarr_res[0]
            if s.get("year") and (not year or str(s["year"]) == year):
                r = _add_series(up, s, quality)
                results.append({"input": search, "kind": "series", "added": r.get("ok"), "title": s.get("title")})
                continue
        results.append({"input": search, "kind": "unknown", "added": False})
    return results

GENRE_HINTS = {
    "funny": ["comedy"], "comedy": ["comedy"], "laughing": ["comedy"],
    "scary": ["horror", "thriller"], "horror": ["horror"], "thriller": ["thriller"],
    "romantic": ["romance"], "love": ["romance"], "romance": ["romance"],
    "action": ["action"], "fight": ["action"], "explosion": ["action"],
    "space": ["science fiction"], "sci-fi": ["science fiction"], "alien": ["science fiction"],
    "drama": ["drama"], "sad": ["drama"], "emotional": ["drama"],
    "doc": ["documentary"], "documentary": ["documentary"], "true story": ["documentary"],
    "kid": ["family", "animation"], "kids": ["family", "animation"], "animated": ["animation"], "animation": ["animation"], "cartoon": ["animation"],
    "anime": ["animation"], "fantasy": ["fantasy"], "magic": ["fantasy"],
    "crime": ["crime"], "noir": ["crime"], "detective": ["crime"],
}
DECADE_RE = [r"\b(19[5-9]\d|20[0-2]\d)s?\b", r"\b(70s|80s|90s|2000s|2010s|2020s)\b"]

def _parse_query(q):
    import re
    ql = q.lower()
    genres = []
    for k, v in GENRE_HINTS.items():
        if k in ql:
            for g in v:
                if g not in genres: genres.append(g)
    decade = None
    for pat in DECADE_RE:
        m = re.search(pat, ql)
        if m: decade = m.group(0); break
    return genres, decade, q

def _tonight(up, q):
    genres, decade, original = _parse_query(q)
    import re
    skip = {"the","a","an","i","want","some","movie","movies","show","shows","series","to","watch","tonight","about"}
    base = " ".join([w for w in original.split() if w.lower() not in skip][:3]) or original
    radarr_hits = _search_radarr(up, base)
    sonarr_hits = _search_sonarr(up, base)
    results = []
    for m in radarr_hits[:12]:
        score = 100
        m_genres = _genres(m)
        if genres:
            if any(g in m_genres for g in genres): score += 50
            else: score -= 30
        if decade and m.get("year"):
            decade_num = "".join(c for c in decade if c.isdigit())[:4] or decade
            if decade_num[:2] == str(m["year"])[:2]: score += 20
        if m.get("runtime"):
            if any(k in q.lower() for k in ["short","under"]) and m["runtime"] < 30: score += 10
            if any(k in q.lower() for k in ["long","epic"]) and m["runtime"] > 120: score += 10
        if _imdb_rating(m) >= 7: score += 15
        results.append({
            "kind": "movie", "title": m.get("title"), "year": m.get("year"), "score": score,
            "summary": m.get("overview","")[:300],
            "runtime": m.get("runtime"), "tmdbId": m.get("tmdbId"),
            "poster": m.get("remotePoster"), "genres": m_genres,
        })
    for s in sonarr_hits[:12]:
        score = 90
        s_genres = _genres(s)
        if genres:
            if any(g in s_genres for g in genres): score += 50
            else: score -= 30
        results.append({
            "kind": "series", "title": s.get("title"), "year": s.get("year"), "score": score,
            "summary": s.get("overview","")[:300] if isinstance(s.get("overview"),str) else "",
            "tvdbId": s.get("tvdbId"),
            "genres": s_genres,
        })
    results.sort(key=lambda r: -r["score"])
    return {"query": original, "genres": genres, "decade": decade, "results": results[:12]}

def _genres(item):
    """Radarr/Sonarr lookup can return genres as a list of dicts
    [{id,name}] OR as a comma-separated string OR as None. Normalise to a
    lowercase list of names."""
    g = item.get("genres")
    if not g: return []
    if isinstance(g, list):
        out = []
        for x in g:
            if isinstance(x, dict) and "name" in x: out.append(x["name"].lower())
            elif isinstance(x, str): out.append(x.lower())
        return out
    if isinstance(g, str):
        return [s.strip().lower() for s in g.split(",") if s.strip()]
    return []

def _imdb_rating(item):
    """Pull IMDB rating defensively — some lookups return ratings as a
    nested dict, others as a flat float, others missing entirely."""
    r = item.get("ratings")
    if not r or not isinstance(r, dict): return 0
    imdb = r.get("imdb")
    if not isinstance(imdb, dict): return 0
    try: return float(imdb.get("value") or 0)
    except (TypeError, ValueError): return 0

def _status_snapshot(up):
    import datetime
    snap = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")}
    try:
        code, body = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie")
        snap["movies_count"] = len(json.loads(body)) if code == 200 else "?"
    except Exception: snap["movies_count"] = "?"
    try:
        code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series")
        snap["series_count"] = len(json.loads(body)) if code == 200 else "?"
    except Exception: snap["series_count"] = "?"
    try:
        code, body = _api_get(up["jellyfin"]["url"], up["jellyfin"]["key"], "/Users")
        snap["jf_users"] = len(json.loads(body)) if code == 200 else "?"
    except Exception: snap["jf_users"] = "?"
    try:
        code, body = _api_get(up["prowlarr"]["url"], up["prowlarr"]["key"], "/api/v1/indexer")
        if code == 200:
            arr = json.loads(body)
            snap["prowlarr_indexers_total"] = len(arr)
            snap["prowlarr_indexers_enabled"] = sum(1 for i in arr if i.get("enable"))
    except Exception: pass
    try:
        with open("/storage/config/quarantine.log") as f:
            lines = f.readlines()[-5:]
            snap["recent_quarantine"] = [l.strip() for l in lines]
    except Exception: pass
    return snap

# ----- archive.org fallback (bypasses Prowlarr when blocked) -----
ARCHIVE_TORRENT_URL = "https://archive.org/download/{identifier}/{identifier}_archive.torrent"

# Hardcoded identifier map for classic public-domain films whose titles are too
# ambiguous for archive.org's search engine (returns game-content / noise).
# Maps pack title -> archive.org identifier with a verified working torrent.
ARCHIVE_ID_OVERRIDE = {
    # --- Public Domain Essentials (all verified working torrents) ---
    "A Trip to the Moon":          "ATripToTheMoon1902",
    "The Great Train Robbery":     "TheGreatTrainRobbery_555",
    "Nosferatu":                   "Nosferatu1922",
    "The General":                 "The_General_Buster_Keaton",
    "Metropolis":                  "Metropolis1927EnglishVersion",
    "The Passion of Joan of Arc":  "the-passion-of-joan-of-arc-1928",
    "Safety Last!":                "SafetyLastHaroldLloyd1923.FullMovieexcellentQuality.",
    "Nosferatu the Vampyre":       "nosferatu-the-vampyre-aka-nosferatu-phantom-der-nacht-1979",
    "The Kid":                     "la35ca-Cinema_35_-_The_Kid_1921",
    "Modern Times":                "modern-times-1936-sub-vhs",
    # --- Documentary Hour (verified) ---
    "Why Man Creates":             "why-man-creates-saul-bass-1968",
    "The Life and Death of 9413: a Hollywood Extra": "the-life-and-death-of-9413-a-hollywood-extra_1928",
    # --- Classic Sci-Fi (verified) ---
    "Teenagers from Outer Space":  "TeenagersFromOuterSpace1959",
    "The Hideous Sun Demon":       "the.-hideous.-sun.-demon.-1958",
    # --- Animated Shorts (verified) ---
    "Steamboat Willie":            "SteamboatWillie",
    "Flowers and Trees":           "flowers-and-trees-1932-restored",
    "The Tortoise and the Hare":  "the-tortoise-and-the-hare-1935-restored",
    # --- Classic TV Pilots ---
    "The Twilight Zone":           "TheTwilightZone_",
    "Alfred Hitchcock Presents":     "AlfredHitchcockPresents1955",
    "The Outer Limits":           "TheOuterLimits_",
    "You Are There":              "YouAreThere1953",
    "Tales of Tomorrow":           "TalesOfTomorrow1951",
}

def _search_archive_org(title, year=None, limit=5):
    """Search archive.org public API for a movie by title.
    Returns list of dicts: {identifier, title, downloads}
    First checks ARCHIVE_ID_OVERRIDE for known pack titles with verified identifiers.
    """
    import urllib.parse
    # Fast path: check hardcoded override for exact title match
    override_id = ARCHIVE_ID_OVERRIDE.get(title)
    if override_id:
        return [{"identifier": override_id, "title": title, "downloads": 0}]
    query = title
    if year:
        query = f"{title} {year}"
    q = urllib.parse.quote_plus(query)
    url = (
        f"https://archive.org/advancedsearch.php"
        f"?q={q}+AND+mediatype%3Amovies"
        f"&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=downloads"
        f"&sort%5B%5D=downloads+desc&rows={limit}&output=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dogebox-library/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return []
            data = json.loads(r.read().decode("utf-8", errors="replace"))
        return [
            {"identifier": d.get("identifier", ""), "title": d.get("title", ""),
             "downloads": d.get("downloads", 0)}
            for d in data.get("response", {}).get("docs", [])
            if d.get("identifier")
        ]
    except Exception:
        return []

def _add_to_qbittorrent(identifier, save_path=None, category=None):
    """Download a torrent from archive.org and push it directly to qBittorrent.
    Returns ("ok", None) on success or ("fail", error_message) on failure.
    qBittorrent runs on the host at port 10005; from inside the pup container
    it is reached at the host's bridge IP (discovered from GATEWAY env var).
    Uses Python's urllib to avoid Nix sandbox restrictions on subprocess curl.
    Retries up to 3 times on 401/429 from archive.org with exponential backoff.
    """
    import tempfile, urllib.request, urllib.parse, time
    # qBittorrent runs on the host at 10.0.0.98:10005 — reach it via the LAN bridge
    qb_host = os.environ.get("GATEWAY", "10.0.0.98")
    qb_url  = f"http://{qb_host}:10005"
    torrent_url = ARCHIVE_TORRENT_URL.format(identifier=identifier)

    # Download torrent with retry on 401/429 (archive.org throttling)
    torrent_data = None
    last_err = None
    for attempt in range(4):
        try:
            # Use browser-like UA to avoid archive.org treating us as a bot
            req = urllib.request.Request(torrent_url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                torrent_data = resp.read()
            if len(torrent_data) >= 100:
                break  # success
            last_err = f"torrent file too small ({len(torrent_data)} bytes)"
            torrent_data = None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429) and attempt < 3:
                # Exponential backoff: 2, 4, 8 seconds
                time.sleep(2 ** (attempt + 1))
                continue
            last_err = f"HTTP {e.code}: {e.reason}"
            torrent_data = None
        except Exception as e:
            last_err = f"torrent download failed: {e}"
            torrent_data = None

    if torrent_data is None:
        return "fail", last_err or "torrent download failed"

    # Upload to qBittorrent using urllib with multipart form data
    try:
        boundary = b"boundary123"
        body_parts = []
        body_parts.append(b"--" + boundary + b"\r\n")
        body_parts.append(b'Content-Disposition: form-data; name="torrents"; filename="' + identifier.encode() + b'.torrent"\r\n')
        body_parts.append(b"Content-Type: application/x-bittorrent\r\n\r\n")
        body_parts.append(torrent_data)
        body_parts.append(b"\r\n--" + boundary + b"--\r\n")
        body = b"".join(body_parts)

        upload_req = urllib.request.Request(
            f"{qb_url}/api/v2/torrents/add",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary=boundary123",
                "User-Agent": "dogebox-library/1.0",
            },
            method="POST"
        )
        with urllib.request.urlopen(upload_req, timeout=20) as resp:
            result = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as e:
        result = e.read().decode("utf-8", errors="replace").strip()
    except Exception as e:
        return "fail", f"qB POST failed: {e}"

    # "Ok." = success, "Fails." = duplicate torrent (already in qB), empty = also ok
    if result.lower() == "ok." or result.lower() == "fails." or not result:
        return "ok", None
    else:
        return "fail", f"qB: {result}"

# ----- v0.0.5: per-user profiles -----
# Jellyfin's /Users/<id>/Items returns everything the user has in their library
# (across all libraries). For the "watched/unwatched" filter, we use
# /Users/<id>/Items?Filters=IsUnplayed to exclude items the user has already
# played. Either way, this is the user's *library* — items already added
# to Radarr/Sonarr or directly to Jellyfin.
def _jellyfin_users(up):
    code, body = _api_get(up["jellyfin"]["url"], up["jellyfin"]["key"], "/Users")
    if code != 200: return []
    try: return json.loads(body)
    except Exception: return []

def _jellyfin_user_library(up, user_id, exclude_played=False):
    """Returns set of TMDB IDs (movies) and TVDB IDs (series) in the user's library.
    exclude_played=True: skip items the user has fully watched (so the search
    shows NEW content, not their entire library)."""
    if not user_id: return set()
    extra = "&Filters=IsUnplayed" if exclude_played else ""
    # We pull both movies and series separately; Jellyfin's generic /Items
    # would include all types and mix ProviderIds.
    have = set()
    for itype in ("Movie", "Series"):
        path = f"/Users/{user_id}/Items?IncludeItemTypes={itype}{extra}&Recursive=true&Limit=500"
        code, body = _api_get(up["jellyfin"]["url"], up["jellyfin"]["key"], path, params=None, timeout=15)
        if code != 200: continue
        try:
            arr = json.loads(body).get("Items", [])
        except Exception:
            continue
        for it in arr:
            prov = it.get("ProviderIds", {}) or {}
            if itype == "Movie" and prov.get("Tmdb"):
                have.add(int(prov["Tmdb"]))
            elif itype == "Series" and prov.get("Tvdb"):
                have.add(int(prov["Tvdb"]))
    return have

def _apply_user_filter(movies, series, have_set):
    if not have_set: return movies, series
    movies = [m for m in movies if int(m.get("tmdbId") or 0) not in have_set]
    series  = [s for s in series  if int(s.get("tvdbId") or 0) not in have_set]
    for m in movies: m["__already"] = True   # mark as already-in-library for UI
    for s in series:  s["__already"] = True
    return movies, series

CSS = """
:root {
  --color-bg-base: #0d0d14;
  --color-bg-surface: #16161f;
  --color-bg-elevated: #1e1e2a;
  --color-bg-overlay: #252535;
  --color-border: #2a2a3a;
  --color-border-strong: #3d3d52;
  --color-text-primary: #f0f0f5;
  --color-text-secondary: #9090a8;
  --color-text-muted: #5a5a70;
  --color-accent: #f59e0b;
  --color-accent-hover: #fbbf24;
  --color-accent-subtle: #78350f;
  --color-success: #22c55e;
  --color-success-subtle: #14532d;
  --color-error: #ef4444;
  --color-error-subtle: #7f1d1d;
  --color-purple: #8b5cf6;
  --color-purple-subtle: #4c1d95;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-8: 3rem;
  --radius-sm: 0.375rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;
  --radius-full: 9999px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.5);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.6);
  --transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-normal: 250ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 350ms cubic-bezier(0.4, 0, 0.2, 1);
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
  margin: 0;
  background: var(--color-bg-base);
  color: var(--color-text-primary);
  line-height: 1.5;
  font-size: 0.9rem;
  -webkit-font-smoothing: antialiased;
}

/* Skip link */
.skip { position: absolute; top: -40px; left: 0; background: var(--color-purple); color: #fff; padding: var(--space-2) var(--space-4); z-index: 200; border-radius: 0 0 var(--radius-md) 0; }
.skip:focus { top: 0; }

/* Topbar */
.topbar {
  background: linear-gradient(135deg, var(--color-bg-base) 0%, color-mix(in srgb, var(--color-purple) 8%, var(--color-bg-base)) 100%);
  border-bottom: 1px solid var(--color-border);
  padding: var(--space-3) var(--space-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 50;
  box-shadow: var(--shadow-md);
}
.topbar-mark {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-decoration: none;
  color: var(--color-text-primary);
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.topbar-mark-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: var(--color-accent);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

/* User pill */
.user-pill {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  padding: var(--space-1) var(--space-3) var(--space-1) var(--space-1);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}
.user-pill:hover { border-color: var(--color-border-strong); }
.user-avatar {
  width: 28px;
  height: 28px;
  background: var(--color-purple);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.user-pill .label {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}
.user-pill select {
  background: transparent;
  border: none;
  color: var(--color-text-secondary);
  font-size: 0.8rem;
  cursor: pointer;
  outline: none;
  padding-right: var(--space-2);
}
.user-pill select option { background: var(--color-bg-elevated); }

/* Status dot */
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: var(--color-success);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--color-success);
}
.status-dot.degraded {
  background: var(--color-accent);
  box-shadow: 0 0 6px var(--color-accent);
}
.status-strip {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 0.75rem;
  color: var(--color-text-muted);
}

/* Container */
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-5) var(--space-4) var(--space-8);
}

/* Section */
.section { margin-bottom: var(--space-6); }
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.section-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0;
  letter-spacing: -0.01em;
}
.section-aside {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.section-aside a {
  color: var(--color-purple);
  text-decoration: none;
}
.section-aside a:hover { text-decoration: underline; }
.section-aside .sep { color: var(--color-text-muted); margin: 0 0.25em; }

/* Search bar */
.search-bar {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.search-wrap {
  flex: 1;
  position: relative;
}
.search-bar input {
  width: 100%;
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  border: 2px solid var(--color-border);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-full);
  font-size: 1rem;
  outline: none;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  height: 52px;
}
.search-bar input::placeholder { color: var(--color-text-muted); }
.search-bar input:focus {
  border-color: var(--color-purple);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.2);
}
.search-bar button {
  background: var(--color-purple);
  color: #fff;
  border: none;
  padding: 0 var(--space-6);
  border-radius: var(--radius-full);
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  transition: background var(--transition-fast), transform var(--transition-fast);
  white-space: nowrap;
}
.search-bar button:hover { background: #7c3aed; transform: translateY(-1px); }
.search-bar button:active { transform: translateY(0); }

/* Autocomplete dropdown */
.suggestions {
  position: absolute;
  top: calc(100% + var(--space-2));
  left: 0;
  right: 0;
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  z-index: 100;
  max-height: 420px;
  overflow-y: auto;
  display: none;
}
.suggestions.open { display: block; }
.suggestion {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  cursor: pointer;
  transition: background var(--transition-fast);
  border-bottom: 1px solid var(--color-border);
}
.suggestion:last-child { border-bottom: none; }
.suggestion:hover, .suggestion[aria-selected="true"] { background: var(--color-bg-overlay); }
.suggestion .poster {
  width: 32px;
  height: 48px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  background: var(--color-border);
  flex-shrink: 0;
}
.suggestion .kind {
  background: var(--color-purple-subtle);
  color: var(--color-text-primary);
  padding: 0.1rem 0.5rem;
  border-radius: var(--radius-full);
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}
.suggestion .year {
  color: var(--color-text-muted);
  font-size: 0.75rem;
  flex-shrink: 0;
}
.suggestion span:not(.kind):not(.year) {
  color: var(--color-text-primary);
  font-size: 0.85rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Actions toolbar */
.actions-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  align-items: flex-end;
  margin-bottom: var(--space-6);
}
.tonight-form {
  flex: 1;
  min-width: 280px;
}
.tonight-form-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: var(--space-2);
}
.tonight-form-row {
  display: flex;
  gap: var(--space-2);
}
.tonight-form input {
  flex: 1;
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: 0.9rem;
  outline: none;
  transition: border-color var(--transition-fast);
  height: 40px;
}
.tonight-form input:focus { border-color: var(--color-purple); }
.tonight-form button, .random-pick-btn {
  background: var(--color-bg-elevated);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border-strong);
  padding: 0 var(--space-4);
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  height: 40px;
}
.tonight-form button:hover, .random-pick-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}
.random-pick-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.random-pick-btn .glyph {
  font-size: 1rem;
}
@keyframes spin { to { transform: rotate(360deg); } }
.random-pick-btn.loading .glyph::after {
  content: '';
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: var(--color-text-primary);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

/* Status strip */
.status-strip-grid {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}
.status-tile { text-align: center; }
.status-tile strong {
  display: block;
  font-size: 1.8rem;
  font-weight: 700;
  color: var(--color-accent);
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.status-tile span {
  font-size: 0.7rem;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* Results grid */
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}
@media (min-width: 480px) { .results-grid { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 768px) { .results-grid { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 1024px) { .results-grid { grid-template-columns: repeat(4, 1fr); } }

/* Media card */
.card {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform var(--transition-normal), box-shadow var(--transition-normal), border-color var(--transition-normal);
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
  border-color: var(--color-border-strong);
}
.card-poster {
  position: relative;
  aspect-ratio: 2/3;
  background: var(--color-bg-elevated);
  overflow: hidden;
}
.card-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform var(--transition-normal);
}
.card:hover .card-poster img { transform: scale(1.03); }
.card-poster-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--color-text-muted);
  background: linear-gradient(135deg, var(--color-bg-elevated), var(--color-bg-overlay));
  letter-spacing: -0.05em;
}
.genre-pills {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-1);
}
.genre-pill {
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  padding: 0.1rem 0.4rem;
  border-radius: var(--radius-full);
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.card-body {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex: 1;
}
.card-title {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.card-meta {
  font-size: 0.75rem;
  color: var(--color-text-muted);
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.card-meta .dot { opacity: 0.4; }
.card-overview {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  margin: 0;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
}
.card-action { margin-top: auto; padding-top: var(--space-2); }
.card-action button {
  width: 100%;
  background: var(--color-success);
  color: #fff;
  border: none;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background var(--transition-fast), transform var(--transition-fast);
}
.card-action button:hover { background: #16a34a; transform: scale(1.02); }
.card-action button:active { transform: scale(0.98); }
.card-action button.already {
  background: var(--color-bg-elevated);
  color: var(--color-text-muted);
  cursor: not-allowed;
  opacity: 0.7;
}

/* Tonight results */
.tonight-list { margin-bottom: var(--space-6); }
.tonight-result {
  display: flex;
  gap: var(--space-4);
  align-items: flex-start;
  padding: var(--space-4) 0;
  border-bottom: 1px solid var(--color-border);
  transition: background var(--transition-fast);
}
.tonight-result:last-child { border-bottom: none; }
.tonight-result:hover { background: rgba(255,255,255,0.02); margin: 0 calc(-1 * var(--space-2)); padding-left: var(--space-2); padding-right: var(--space-2); border-radius: var(--radius-md); }
.tonight-result .score-badge {
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  border: 1px solid var(--color-accent);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-weight: 700;
  font-size: 0.85rem;
  text-align: center;
  flex-shrink: 0;
  min-width: 52px;
}
.tonight-result .score-label {
  display: block;
  font-size: 0.55rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  opacity: 0.7;
  margin-top: 2px;
}
.tonight-result .info { flex: 1; min-width: 0; }
.tonight-result .title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0 0 var(--space-1);
}
.tonight-result .title span { font-weight: 400; color: var(--color-text-muted); }
.tonight-result .summary {
  font-size: 0.82rem;
  color: var(--color-text-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tonight-result form { flex-shrink: 0; }
.tonight-result button {
  background: var(--color-success);
  color: #fff;
  border: none;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background var(--transition-fast);
}
.tonight-result button:hover { background: #16a34a; }

/* Starter packs */
.packs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}
.pack {
  background: var(--color-bg-surface);
  border: 1px solid var(--color-border);
  border-left: 2px solid color-mix(in srgb, var(--color-purple) 40%, transparent);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}
.pack:hover { border-left-color: var(--color-accent); box-shadow: var(--shadow-md); }
.pack[data-theme="movies"] { border-left-color: var(--color-purple); }
.pack[data-theme="shows"] { border-left-color: #3b82f6; }
.pack[data-theme="mixed"] { border-left-color: var(--color-accent); }
.pack-title {
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text-primary);
  margin: 0 0 var(--space-2);
}
.pack-desc {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  margin: 0 0 var(--space-3);
  line-height: 1.5;
}
.pack-count {
  display: inline-block;
  background: var(--color-purple-subtle);
  color: var(--color-purple);
  padding: 0.1rem 0.5rem;
  border-radius: var(--radius-full);
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-3);
}
.pack-titles {
  list-style: none;
  margin: 0 0 var(--space-3);
  padding: 0;
  max-height: 130px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.pack-titles li {
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--color-border);
}
.pack-titles li:last-child { border-bottom: none; }
.pack-titles li em { color: var(--color-text-muted); font-size: 0.75rem; }
.pack button {
  background: var(--color-purple);
  color: #fff;
  border: none;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-weight: 600;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background var(--transition-fast), transform var(--transition-fast);
  width: 100%;
}
.pack button:hover { background: #7c3aed; transform: translateY(-1px); }

/* Toast inline */
.toast-inline {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-success);
  border-left: 2px solid color-mix(in srgb, var(--color-success) 60%, transparent);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  box-shadow: var(--shadow-md);
  font-size: 0.875rem;
  margin: var(--space-4) 0;
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.toast-inline::before {
  content: '';
  display: inline-block;
  width: 18px;
  height: 18px;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2322c55e' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/%3E%3Cpolyline points='22 4 12 14.01 9 11.01'/%3E%3C/svg%3E") center/contain no-repeat;
  flex-shrink: 0;
  margin-top: 2px;
}
.toast-inline.error {
  border-left-color: var(--color-error);
  border-color: var(--color-error-subtle);
}
.toast-inline.error::before {
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ef4444' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='15' y1='9' x2='9' y2='15'/%3E%3Cline x1='9' y1='9' x2='15' y2='15'/%3E%3C/svg%3E") center/contain no-repeat;
}
.toast-inline strong { display: block; font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-1); }
.toast-inline p { margin: 0; color: var(--color-text-secondary); }
.toast-inline ul { margin: var(--space-2) 0 0; padding-left: var(--space-5); color: var(--color-text-secondary); }
.toast-inline li { margin-bottom: var(--space-1); }

/* Toast region (for JS-driven toasts) */
.toast-region { position: fixed; top: var(--space-4); left: 50%; transform: translateX(-50%); z-index: 1000; pointer-events: none; }
.toast {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  box-shadow: var(--shadow-lg);
  margin-bottom: var(--space-2);
  min-width: 300px;
  max-width: 440px;
  pointer-events: auto;
  animation: toast-in var(--transition-slow) forwards;
}
.toast.success { border-left: 2px solid color-mix(in srgb, var(--color-success) 60%, transparent); }
.toast.error { border-left: 2px solid color-mix(in srgb, var(--color-error) 60%, transparent); }
.toast.info { border-left: 2px solid color-mix(in srgb, var(--color-purple) 60%, transparent); }
@keyframes toast-in {
  from { opacity: 0; transform: translateY(-12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes toast-out {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(-8px); }
}
.toast.fade-out { animation: toast-out var(--transition-normal) forwards; }

/* Empty state */
.empty {
  text-align: center;
  padding: var(--space-8) var(--space-4);
  color: var(--color-text-muted);
}
.empty strong { display: block; font-size: 1.1rem; color: var(--color-text-secondary); margin-bottom: var(--space-2); }
.empty p { margin: 0; font-size: 0.875rem; }
.empty svg { width: 64px; height: 64px; margin-bottom: var(--space-4); opacity: 0.3; }

/* Mobile */
@media (max-width: 600px) {
  .topbar { padding: var(--space-3); }
  .topbar .label { display: none; }
  .search-bar input { font-size: 0.9rem; height: 46px; }
  .actions-toolbar { flex-direction: column; align-items: stretch; }
  .tonight-form { min-width: unset; }
  .tonight-result { flex-wrap: wrap; }
  .tonight-result .score-badge { order: -1; }
  .tonight-result form { width: 100%; }
  .tonight-result button { width: 100%; margin-top: var(--space-2); }
  .section-head { flex-direction: column; gap: var(--space-1); }
}
"""

def _initials(name):
    parts = [p for p in (name or "").strip().split() if p]
    if not parts: return "?"
    if len(parts) == 1: return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()

def _render_topbar(up, user_id, status_reachable):
    users = _jellyfin_users(up)
    pill = ""
    if users:
        opts = []
        sel = ""
        for u in users:
            name = u["Name"]
            admin = u.get("IsAdministrator", False)
            opts.append(f'<option value="{u["Id"]}" {"selected" if str(u["Id"])==user_id else ""}>{name}{" (admin)" if admin else ""}</option>')
            if str(u["Id"]) == user_id: sel = name
        current_label = sel if sel else "(all users)"
        pill = (
            f'<label class="user-pill" title="Filter by Jellyfin user">'
            f'<span class="user-avatar">{_initials(current_label)}</span>'
            f'<span class="label">{_initials(current_label)}</span>'
            f'<form method="GET" action="/" style="margin:0;display:inline">'
            f'<select name="user" onchange="this.form.submit()" aria-label="Profile">'
            f'<option value="">(all users)</option>' + "".join(opts) +
            f'</select></form></label>'
        )
    dot = '<span class="status-dot" title="All upstreams reachable"></span>' if status_reachable else '<span class="status-dot degraded" title="One or more upstreams unreachable"></span>'
    svg_icon = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
        '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>'
        '</svg>'
    )
    return (
        f'<a class="topbar-mark" href="/"><span class="topbar-mark-glyph" aria-hidden="true">{svg_icon}</span><span>Library</span></a>'
        f'<div class="topbar-right">{pill}<span class="status-strip" aria-label="Upstream status">{dot}<span class="label">upstreams</span></span></div>'
    )

def _render_search_bar(user_id):
    hidden = f'<input type="hidden" name="user" value="{user_id}">' if user_id else ""
    return (
        f'<form class="search-bar" method="GET" action="/search">'
        f'{hidden}'
        f'<div class="search-wrap">'
        f'<input id="q" name="q" placeholder="Search movies or shows..." autocomplete="off" autofocus spellcheck="false" aria-label="Search">'
        f'<div class="suggestions" id="suggest" role="listbox" aria-label="Search suggestions"></div>'
        f'</div>'
        f'<button type="submit">Search</button>'
        f'</form>'
    )

def _render_actions_toolbar(user_id):
    hidden = f'<input type="hidden" name="user" value="{user_id}">' if user_id else ""
    rand_query = f'<input type="hidden" name="user" value="{user_id}">' if user_id else ""
    return (
        f'<div class="actions-toolbar">'
        f'<form class="tonight-form" method="GET" action="/tonight">'
        f'{hidden}'
        f'<label class="tonight-form-label" for="tonight-q">Tonight</label>'
        f'<div class="tonight-form-row">'
        f'<input id="tonight-q" name="q" aria-label="Tonight mood input" placeholder="Mood, genre, year - \\"funny 90s not too long\\"" autocomplete="off" spellcheck="false">'
        f'<button type="submit">Find</button>'
        f'</div></form>'
        f'<form method="GET" action="/random">'
        f'{rand_query}'
        f'<button type="submit" class="random-pick-btn" id="random-pick-btn" title="Surprise me">'
        f'<span class="glyph" aria-hidden="true"></span><span>Surprise me</span>'
        f'</button></form>'
        f'</div>'
    )

def _render_card(item, kind):
    title = item.get("title") or "?"
    year = item.get("year") or "?"
    runtime = item.get("runtime")
    overview = (item.get("overview") or item.get("summary") or "").replace("<","&lt;")
    poster = item.get("remotePoster") or ""
    already = item.get("__already") or False
    genres = (_genres(item) or [])[:2]
    id_key = "tmdbId" if kind == "movie" else "tvdbId"
    id_val = item.get(id_key) or ""
    poster_html = f'<img src="{poster}" alt="" loading="lazy" decoding="async">' if poster else f'<div class="card-poster-placeholder">{title[:2]}</div>'
    runtime_html = f' - {runtime} min' if runtime else ''
    ellipsis = "..." if len(overview) > 200 else ""
    genre_html = ""
    if genres:
        pills = "".join(f'<span class="genre-pill">{g}</span>' for g in genres)
        genre_html = f'<div class="genre-pills">{pills}</div>'
    if already:
        action = f'<div class="card-action"><button class="already" type="button" disabled>Already in library</button></div>'
    else:
        action = f'<form class="card-action" method="POST" action="/add/{kind}"><input type="hidden" name="id" value="{id_val}"><button type="submit">Add to {kind.capitalize()}</button></form>'
    return (
        f'<article class="card">'
        f'<div class="card-poster">{poster_html}</div>'
        f'<div class="card-body">'
        f'<h3 class="card-title" title="{title}">{title}</h3>'
        f'<div class="card-meta"><span class="card-meta-year">{year}</span>{runtime_html}</div>'
        f'{genre_html}'
        f'<p class="card-overview">{overview[:200]}{ellipsis}</p>'
        f'</div>'
        f'{action}'
        f'</article>'
    )

def _render_pack(p):
    name = p.get("name","?")
    name_esc = name.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")
    desc = p.get("description","").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    titles = p.get("titles",[])[:8]
    more = len(p.get("titles",[])) - len(titles)
    items_html = "".join(f"<li>{t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}</li>" for t in titles)
    if more > 0: items_html += f"<li><em>+{more} more...</em></li>"
    theme = p.get("theme","library")
    count = len(p.get("titles",[]))
    return (
        f'<article class="pack" data-theme="{theme}">'
        f'<h3 class="pack-title">{name_esc}</h3>'
        f'<p class="pack-desc">{desc}</p>'
        f'<span class="pack-count">{count} titles</span>'
        f'<ul class="pack-titles">{items_html}</ul>'
        f'<form method="POST" action="/pack"><input type="hidden" name="pack" value="{name_esc}"><button type="submit">Add all to {theme}</button></form>'
        f'</article>'
    )

def _render_status_strip(snap):
    mc = snap.get("movies_count", "?")
    sc = snap.get("series_count", "?")
    jf = snap.get("jf_users", "?")
    pi = snap.get("prowlarr_indexers_enabled", "?")
    return (
        f'<div class="status-strip-grid">'
        f'<div class="status-tile"><strong class="status-tile__num">{mc}</strong><span class="status-tile__label">Movies</span></div>'
        f'<div class="status-tile"><strong class="status-tile__num">{sc}</strong><span class="status-tile__label">Shows</span></div>'
        f'<div class="status-tile"><strong class="status-tile__num">{jf}</strong><span class="status-tile__label">JF Users</span></div>'
        f'<div class="status-tile"><strong class="status-tile__num">{pi}</strong><span class="status-tile__label">Indexers</span></div>'
        f'</div>'
    )

def _render_empty(title, hint):
    return f'<div class="empty"><strong>{title}</strong>{hint}</div>'

def _render_results(movies, series):
    if not (movies or series):
        return _render_empty("No results yet", "Try a different term, or pick a starter pack below.")
    cards = "".join(_render_card(x, "movie") for x in movies) + "".join(_render_card(x, "series") for x in series)
    return f'<div class="results-grid">{cards}</div>'

def _render_tonight_results(results):
    if not results:
        return _render_empty("No matches", "Tell me your mood - e.g. \"dark sci-fi under 2h\" or \"funny 90s\".")
    rows = []
    for r in results:
        kind = r["kind"]; id_key = "tmdbId" if kind == "movie" else "tvdbId"
        title = r["title"]; year = r.get("year","")
        summary = (r.get("summary","") or "").replace("<","&lt;")
        ellipsis = "..." if len(summary) >= 200 else ""
        genres = (_genres(r) or [])[:3]
        genre_html = ""
        if genres:
            pills = "".join(f'<span class="genre-pill">{g}</span>' for g in genres)
            genre_html = f'<div class="tonight-result__genres">{pills}</div>'
        rows.append(
            f'<article class="tonight-result">'
            f'<div class="tonight-result__score">'
            f'<div class="score-badge">{r["score"]}</div>'
            f'</div>'
            f'<div class="tonight-result__info">'
            f'<h4 class="tonight-result__title">{title} <span>({year})</span></h4>'
            f'{genre_html}'
            f'<p class="tonight-result__summary">{summary}{ellipsis}</p>'
            f'</div>'
            f'<div class="tonight-result__action">'
            f'<form method="POST" action="/add/{kind}"><input type="hidden" name="id" value="{r.get(id_key)}"><button type="submit">Add</button></form>'
            f'</div>'
            f'</article>'
        )
    return f'<div class="tonight-list">{"".join(rows)}</div>'

def _render_packs(packs):
    if not packs:
        return _render_empty("No starter packs", "Starter packs live at <code>/storage/config/starter-packs.json</code> on the box.")
    return f'<div class="packs-grid">{"".join(_render_pack(p) for p in packs)}</div>'

def _html(body, title="Library", up=None, user_id="", status_reachable=True):
    if up is None: up = _load_upstreams()
    head = (
        f'<!doctype html>'
        f'<html lang="en">'
        f'<head>'
        f'<meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f'<meta name="color-scheme" content="dark">'
        f'<meta name="theme-color" content="#0d0d14">'
        f'<title>{title}</title>'
        f'<link rel="icon" href="data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' viewBox=\'0 0 24 24\' fill=\'%23f59e0b\'><path d=\'M4 4v16l8-5 8 5V4z\'/></svg>">'
        f'<style>{CSS}</style>'
        f'</head>'
        f'<body>'
        f'<a class="skip" href="#main">Skip to content</a>'
        f'<header class="topbar" role="banner">{_render_topbar(up, user_id, status_reachable)}</header>'
        f'<main id="main" class="container" role="main">{body}</main>'
        f'<div class="toast-region" role="region" aria-live="polite" id="toast-region"></div>'
        f'<script src="/static/live.js" defer></script>'
        f'</body></html>'
    )
    return head

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs): pass

    def _send(self, code, ctype, body):
        body = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _render(self, html):
        self._send(200, "text/html; charset=utf-8", html)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        user_id = (qs.get("user") or [""])[0].strip()
        up = _load_upstreams()

        # Inline test: simulate the exact _add_to_qbittorrent logic
        if u.path == "/debug/test":
            import tempfile, subprocess, datetime
            ident = "ATripToTheMoon1902"
            torrent_url = f"https://archive.org/download/{ident}/{ident}_archive.torrent"
            qb_host = os.environ.get("GATEWAY", "10.0.0.98")
            qb_url = f"http://{qb_host}:10005"
            lines = [f"qb_url={qb_url}", f"GATEWAY={os.environ.get('GATEWAY','(unset)')}"]
            try:
                with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tf:
                    tmp = tf.name
                r1 = subprocess.run(["curl", "-L", "-s", "-o", tmp, torrent_url, "--max-time", "20", "--user-agent", "dogebox-library/1.0"], capture_output=True, timeout=25)
                size = os.path.getsize(tmp)
                lines.append(f"dl: rc={r1.returncode} size={size}")
                r2 = subprocess.run(["curl", "-s", "-X", "POST", f"{qb_url}/api/v2/torrents/add", "-F", "torrents=@" + tmp], capture_output=True, timeout=20)
                result = (r2.stdout or b"").decode("utf-8", errors="replace").strip()
                lines.append(f"qB: {result!r}")
                os.unlink(tmp)
                # Same logic as _add_to_qbittorrent
                if result.lower() == "ok." or result.lower() == "fails." or not result:
                    lines.append("WOULD RETURN: ok")
                else:
                    lines.append(f"WOULD RETURN: fail ({result})")
            except Exception as e:
                lines.append(f"EXCEPTION: {e}")
            self._send(200, "text/plain", "\n".join(lines))
            return

        if u.path == "/static/live.js":
            self._send(200, "application/javascript", LIVE_JS)
            return

        # Debug: test qBittorrent response for a known duplicate torrent
        if u.path == "/debug/qb":
            import tempfile, subprocess, datetime
            ident = "ATripToTheMoon1902"
            torrent_url = f"https://archive.org/download/{ident}/{ident}_archive.torrent"
            qb_host = os.environ.get("GATEWAY", "10.0.0.98")
            qb_url = f"http://{qb_host}:10005"
            lines = ["DEBUG qB test", f"timestamp: {datetime.datetime.now().isoformat()}", f"qb_url: {qb_url}", f"GATEWAY env: {os.environ.get('GATEWAY', '(not set)')}"]
            try:
                with tempfile.NamedTemporaryFile(suffix=".torrent", delete=False) as tf:
                    tmp = tf.name
                proc = subprocess.run(["curl", "-L", "-s", "-o", tmp, torrent_url,
                    "--max-time", "20", "--user-agent", "dogebox-library/1.0"],
                    capture_output=True, timeout=25)
                size = os.path.getsize(tmp)
                lines.append(f"torrent_download: returncode={proc.returncode} size={size}")
                proc2 = subprocess.run(["curl", "-s", "-X", "POST",
                    f"{qb_url}/api/v2/torrents/add", "-F", "torrents=@" + tmp],
                    capture_output=True, timeout=20)
                result = (proc2.stdout or b"").decode("utf-8", errors="replace").strip()
                lines.append(f"qB response: {result!r}")
                os.unlink(tmp)
            except Exception as e:
                lines.append(f"exception: {e}")
            self._send(200, "text/plain", "\n".join(lines))
            return

        if u.path == "/api/users":
            users = _jellyfin_users(up)
            return self._json([{"id": u["Id"], "name": u["Name"], "admin": u.get("IsAdministrator", False)} for u in users])

        if u.path == "/api/search":
            term = (qs.get("q") or [""])[0].strip()
            user_id = (qs.get("user") or [""])[0].strip()
            if not term: return self._json({"movies":[],"series":[]})
            m = _search_radarr(up, term)[:8]
            s = _search_sonarr(up, term)[:8]
            radarr_existing = {}
            code, body = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie")
            if code == 200:
                for x in json.loads(body): radarr_existing[x.get("tmdbId")] = x
            sonarr_existing = {}
            code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series")
            if code == 200:
                for x in json.loads(body): sonarr_existing[x.get("tvdbId")] = x
            for x in m: x["__already"] = x.get("tmdbId") in radarr_existing
            for x in s: x["__already"] = x.get("tvdbId") in sonarr_existing
            if user_id:
                have = _jellyfin_user_library(up, user_id, exclude_played=False)
                m, s = _apply_user_filter(m, s, have)
            return self._json({"movies": m, "series": s})

        if u.path == "/api/status":
            return self._json(_status_snapshot(up))

        if u.path == "/api/tonight":
            q = (qs.get("q") or [""])[0].strip()
            user_id = (qs.get("user") or [""])[0].strip()
            if not q: return self._json({"error":"missing q"}, 400)
            rec = _tonight(up, q)
            if user_id:
                have = _jellyfin_user_library(up, user_id, exclude_played=True)
                rec["movies"] = [m for m in rec.get("movies", []) if int(m.get("tmdbId") or 0) not in have]
                rec["series"] = [s for s in rec.get("series", []) if int(s.get("tvdbId") or 0) not in have]
            return self._json(rec)

        if u.path == "/api/random":
            user_id = (qs.get("user") or [""])[0].strip()
            # No mood text: just pull the trending set from Prowlarr/Radarr/Sonarr
            # and pick a high-scoring one randomly. We do this by searching
            # Radarr+Sonarr for a broad term ("a") and filtering for runtime
            # <180min + votes > 6.5, then random.sample from top 12.
            import random
            radarr_hits = _search_radarr(up, "the")[:20]
            sonarr_hits = _search_sonarr(up, "the")[:20]
            pool = []
            for m in radarr_hits:
                rating = (m.get("ratings", {}) or {}).get("imdb", {}).get("value", 0) or 0
                if rating and rating >= 6.5 and (m.get("runtime") or 999) <= 180:
                    pool.append({"kind":"movie","title":m.get("title"),"year":m.get("year"),"score":rating*10,"tmdbId":m.get("tmdbId"),"summary":m.get("overview","")[:200]})
            for s in sonarr_hits:
                rating = (s.get("ratings", {}) or {}).get("imdb", {}).get("value", 0) or 0
                if rating and rating >= 6.5:
                    pool.append({"kind":"series","title":s.get("title"),"year":s.get("year"),"score":rating*10,"tvdbId":s.get("tvdbId"),"summary":(s.get("overview","")[:200] if isinstance(s.get("overview"),str) else "")})
            if user_id:
                have = _jellyfin_user_library(up, user_id, exclude_played=True)
                pool = [x for x in pool if int(x.get("tmdbId") or x.get("tvdbId") or 0) not in have]
            if not pool: return self._json({"error":"no candidates"}, 404)
            pick = random.choice(pool)
            return self._json({"pick": pick})

        if u.path == "/" or u.path == "/index.html":
            user_id = (qs.get("user") or [""])[0].strip()
            snap = _status_snapshot(up)
            # Use upstreams-reachability for the status dot
            reachable = (
                isinstance(snap.get("movies_count"), int)
                and isinstance(snap.get("series_count"), int)
                and isinstance(snap.get("jf_users"), int)
            )
            try:
                with open("/storage/config/starter-packs.json") as f:
                    packs = json.load(f)
            except Exception:
                packs = []
            body = ""
            body += _render_search_bar(user_id)
            body += _render_status_strip(snap)
            body += _render_actions_toolbar(user_id)
            body += '<div class="section"><div class="section-head"><h2 class="section-title">Starter packs</h2>'
            n_titles = sum(len(p.get("titles",[])) for p in packs)
            body += f'<span class="section-aside">{len(packs)} packs - {n_titles} titles</span></div>'
            body += _render_packs(packs) + '</div>'
            return self._render(_html(body, up=up, user_id=user_id, status_reachable=reachable))

        if u.path == "/search":
            term = (qs.get("q") or [""])[0].strip()
            user_id = (qs.get("user") or [""])[0].strip()
            if not term:
                return self._render(_html('<div class="empty"><strong>Empty search</strong>Type something above and try again.</div>', up=up, user_id=user_id, title="Search - Dogebox Library"))
            m = _search_radarr(up, term)
            s = _search_sonarr(up, term)
            radarr_existing = {}
            code, body_resp = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie")
            if code == 200:
                for x in json.loads(body_resp): radarr_existing[x.get("tmdbId")] = x
            sonarr_existing = {}
            code, body_resp = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series")
            if code == 200:
                for x in json.loads(body_resp): sonarr_existing[x.get("tvdbId")] = x
            for x in m: x["__already"] = x.get("tmdbId") in radarr_existing
            for x in s: x["__already"] = x.get("tvdbId") in sonarr_existing
            if user_id:
                have = _jellyfin_user_library(up, user_id, exclude_played=False)
                m, s = _apply_user_filter(m, s, have)
            user_param = f"&user={user_id}" if user_id else ""
            _back_href = f'/?user={user_id}' if user_id else '/'
            heading = f'<div class="section"><div class="section-head"><h2 class="section-title">Results for {chr(34)}{term.replace(chr(60),"&lt;")}{chr(34)}</h2><span class="section-aside"><a href="{_back_href}">back</a></span></div>'
            grid = _render_results(m, s)
            return self._render(_html(heading + grid, up=up, user_id=user_id, title=f"Search: {term} - Library"))

        if u.path == "/tonight":
            q = (qs.get("q") or [""])[0].strip()
            user_id = (qs.get("user") or [""])[0].strip()
            rec = _tonight(up, q) if q else {"results":[]}
            user_param = f"&user={user_id}" if user_id else ""
            _tonight_back = f'/?user={user_id}' if user_id else '/'
            head = (
                f'<div class="section"><div class="section-head">'
                f'<h2 class="section-title">Tonight for {chr(34)}{(q or "").replace(chr(60),"&lt;")}{chr(34)}</h2>'
                f'<span class="section-aside"><a href="/tonight?q=&user={user_id}">reroll</a> <span class="sep">|</span> <a href="{_tonight_back}">back</a></span>'
                f'</div>'
            )
            return self._render(_html(head + _render_tonight_results(rec.get("results", [])), up=up, user_id=user_id, title="Tonight - Library"))

        if u.path == "/random":
            _tonight_back = f'/?user={user_id}' if user_id else '/'
            import random as _r
            seed = _r.choice(["the", "a", "new", "best", "top", "story", "man", "woman", "love", "night", "day"])
            rec = _tonight(up, seed)
            if user_id:
                have = _jellyfin_user_library(up, user_id, exclude_played=True)
                rec["movies"] = [m for m in rec.get("movies", []) if int(m.get("tmdbId") or 0) not in have]
                rec["series"] = [s for s in rec.get("series", []) if int(s.get("tvdbId") or 0) not in have]
            pool = rec.get("movies", []) + rec.get("series", [])
            if not pool:
                return self._render(_html(_render_empty("No candidates yet", "Add a few titles first, or check your Prowlarr indexers."), up=up, user_id=user_id, title="Random - Library"))
            pick = _r.choice(pool)
            kind = pick["kind"]
            id_key = "tmdbId" if kind == "movie" else "tvdbId"
            title = pick["title"]; year = pick.get("year",""); score = pick["score"]
            summary = (pick.get("summary","") or "").replace(chr(60),"&lt;")
            ellipsis = "..." if len(summary) >= 200 else ""
            rand_link = f'/random{("?user="+user_id) if user_id else ""}'
            head = (
                f'<div class="section"><div class="section-head">'
                f'<h2 class="section-title">Surprise pick</h2>'
                f'<span class="section-aside"><a href="{rand_link}">reroll</a> <span class="sep">|</span> <a href="{_tonight_back}">back</a></span>'
                f'</div>'
            )
            body = head + _render_tonight_results([pick])
            return self._render(_html(body, up=up, user_id=user_id, title="Random - Library"))

        if u.path == "/import":
            page_body = (
                '<div class="section"><div class="section-head">'
                '<h2 class="section-title">Import from IMDb</h2>'
                '<span class="section-aside"><a href="/">back</a></span>'
                '</div>'
                '<div class="import-form-wrap">'
                '<p style="color:var(--color-text-secondary);margin:0 0 1rem;font-size:0.9rem;">Paste an IMDb list export link to bulk-add titles. Go to an IMDb list, click Export, and copy the link.</p>'
                '<form method="POST" action="/import" class="import-form">'
                '<div class="import-form-row">'
                '<input name="url" type="url" placeholder="https://www.imdb.com/list/ls.../export" autocomplete="off" spellcheck="false" aria-label="IMDb list export URL" style="flex:1;background:var(--color-bg-surface);color:var(--color-text-primary);border:1px solid var(--color-border);padding:0.5rem 1rem;border-radius:0.5rem;font-size:0.9rem;outline:none;">'
                '<button type="submit" style="background:var(--color-purple);color:#fff;border:none;padding:0.5rem 1.5rem;border-radius:0.5rem;font-weight:600;font-size:0.9rem;cursor:pointer;white-space:nowrap;">Import</button>'
                '</div></form></div>'
            )
            return self._render(_html(page_body, up=up, user_id=user_id, title="Import - Library"))


        self._send(404, "text/plain", "not found")

    def do_POST(self):
        up = _load_upstreams()
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = parse_qs(raw)

        if u.path.startswith("/add/movie/"):
            tmdb_id = int(form.get("id", ["0"])[0])
            code, body = _api_get(up["radarr"]["url"], up["radarr"]["key"], "/api/v3/movie/lookup", {"term": f"tmdb:{tmdb_id}"})
            if code != 200 or not json.loads(body):
                self._render(_html('<div class="toast-inline error"><strong>Movie lookup failed.</strong>Try a different item.</div><a href="/">back</a>'))
                return
            item = json.loads(body)[0]
            r = _add_movie(up, item, _quality_id(up, "movie"))
            cls = "toast-inline" if r.get("ok") else "toast-inline error"
            if r.get("already"):
                msg = "Already in your library."
            elif r.get("ok"):
                msg = "Added! Radarr will search for it and qB will pick it up."
            else:
                msg = f"Radarr returned {r.get('code')}: {r.get('body')}"
            self._render(_html(f'<div class="{cls}"><strong>{("Done" if r.get("ok") else "Failed")}.</strong> {msg}</div><a href="/">back to library</a>'))
            return

        if u.path.startswith("/add/series/"):
            tvdb_id = int(form.get("id", ["0"])[0])
            code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series/lookup", {"term": f"tvdb:{tvdb_id}"})
            if code != 200 or not json.loads(body):
                self._render(_html('<div class="toast-inline error"><strong>Series lookup failed.</strong>Try a different item.</div><a href="/">back</a>'))
                return
            item = json.loads(body)[0]
            r = _add_series(up, item, _quality_id(up, "series"))
            cls = "toast-inline" if r.get("ok") else "toast-inline error"
            if r.get("already"):
                msg = "Already in your library."
            elif r.get("ok"):
                msg = "Added! Sonarr will search for it."
            else:
                msg = f"Sonarr returned {r.get('code')}: {r.get('body')}"
            self._render(_html(f'<div class="{cls}"><strong>{("Done" if r.get("ok") else "Failed")}.</strong> {msg}</div><a href="/">back to library</a>'))
            return

        if u.path == "/pack":
            pack_name = form.get("pack", [""])[0]
            try:
                with open("/storage/config/starter-packs.json") as f:
                    packs = json.load(f)
            except Exception as e:
                self._render(_html(f'<div class="toast-inline error"><strong>Pack file unreadable:</strong> {e}</div><a href="/">back</a>'))
                return
            pack = next((p for p in packs if p.get("name") == pack_name), None)
            if not pack:
                self._render(_html('<div class="toast-inline error"><strong>Pack not found.</strong> Check the pack name.</div><a href="/">back</a>'))
                return
            results = []
            for t in pack.get("titles", []):
                kind = pack.get("theme")
                if kind == "movies":
                    res = _search_radarr(up, t)
                    if res:
                        # _add_movie handles the hasFile check and archive.org fallback internally
                        r = _add_movie(up, res[0], _quality_id(up, "movie"))
                        if r.get("archive"):
                            # Movie in Radarr without a file — archive.org fallback fired
                            results.append(("movie-archive", {
                                "title": t,
                                "identifier": r.get("identifier", ""),
                                "archive_downloads": r.get("archive_downloads", 0),
                                "qb_ok": r.get("qb_ok"),
                                "qb_err": r.get("qb_err"),
                            }))
                        else:
                            results.append(("movie", res[0]))
                    else:
                        # Radarr found nothing — Prowlarr might be blocked.
                        # Try archive.org directly.
                        year = None
                        hits = _search_archive_org(t, year, limit=5)
                        if hits:
                            top = hits[0]
                            ok, err = _add_to_qbittorrent(top["identifier"])
                            results.append(("movie-archive", {"title": t, "identifier": top["identifier"], "archive_downloads": top.get("downloads", 0), "qb_ok": ok, "qb_err": err}))
                else:
                    res = _search_sonarr(up, t)
                    if res: results.append(("series", res[0]))
            added = []
            for kind, item in results:
                if kind == "movie":
                    r = _add_movie(up, item, _quality_id(up, "movie"))
                    added.append((kind, item.get("title"), r.get("ok"), r.get("already")))
                elif kind == "movie-archive":
                    added.append((kind, item.get("title"), item.get("qb_ok") == "ok", False))
                else:
                    r = _add_series(up, item, _quality_id(up, "series"))
                    added.append((kind, item.get("title"), r.get("ok"), r.get("already")))
            rows = "".join(
                f'<li>{"OK" if ok else ("SKIP" if already else ("FAIL" if k == "movie-archive" else "NO"))} <b>{t}</b> {k if k != "movie" else ""}{f" [qb_ok={item.get("qb_ok")}, qb_err={item.get("qb_err")}]" if k == "movie-archive" else ""}</li>'
                for k, t, ok, already in added
            )
            skipped = len(pack.get("titles",[])) - len(added)
            body = f'<div class="toast-inline"><strong>Pack "{pack_name}":</strong> {sum(1 for _,_,ok,_ in added if ok)} added, {sum(1 for _,_,_,al in added if al)} already present, {sum(1 for k,_,ok,_ in added if k == "movie-archive" and not ok)} failed (archive.org), {skipped} not found.</div><ul>{rows}</ul><a href="/">back</a>'
            self._render(_html(body))
            return

        if u.path == "/import":
            url = form.get("url", [""])[0].strip()
            if not url: self._render(_html('<div class="toast-inline error"><strong>Missing URL.</strong> Paste an IMDb list export link.</div><a href="/">back</a>')); return
            req = urllib.request.Request(url, headers={"User-Agent": "dogebox-library/0.0.3"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    code = r.status
                    body = r.read().decode("utf-8", errors="replace")
            except Exception as e:
                code = 0; body = str(e)
            if code != 200:
                self._render(_html(f'<div class="toast-inline error"><strong>Fetch failed:</strong> HTTP {code}</div><a href="/">back</a>')); return
            if "imdb.com" in url and (body.lower().startswith("position") or "\t" in body):
                res = _import_imdb_csv(up, body, _quality_id(up, "movie"))
                rows = "".join(f"<li>{'OK' if r['added'] else 'NO'} <b>{r['title'] or r['input']}</b> ({r['kind']})</li>" for r in res)
                body_html = f'<div class="toast-inline"><strong>Imported {sum(1 for r in res if r["added"])}/{len(res)} from IMDb list.</strong></div><ul>{rows}</ul><a href="/">back</a>'
            else:
                body_html = '<div class="toast-inline error"><strong>URL not recognised.</strong> Use an IMDb list export link - e.g. https://www.imdb.com/list/ls.../export</div><a href="/">back</a>'
            self._render(_html(body_html))
            return

        self._send(404, "text/plain", "not found")

PORT = int(sys.argv[1])
TS = getattr(http.server, "ThreadingHTTPServer", None) or http.server.ThreadingTCPServer
with TS(("0.0.0.0", PORT), Handler) as s:
    s.allow_reuse_address = True
    s.serve_forever()
