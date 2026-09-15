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
    req = urllib.request.Request(url, headers={"X-Api-Key": api_key} if api_key else {}, method="GET")
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
    h = {"X-Api-Key": api_key} if api_key else {}
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
        return {"ok": True, "already": True, "movie": existing}
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
        if genres:
            m_genres = [g["name"].lower() for g in m.get("genres",[])] if isinstance(m.get("genres"), list) else []
            if any(g in m_genres for g in genres): score += 50
            else: score -= 30
        if decade and m.get("year"):
            decade_num = "".join(c for c in decade if c.isdigit())[:4] or decade
            if decade_num[:2] == str(m["year"])[:2]: score += 20
        if m.get("runtime"):
            if any(k in q.lower() for k in ["short","under"]) and m["runtime"] < 30: score += 10
            if any(k in q.lower() for k in ["long","epic"]) and m["runtime"] > 120: score += 10
        if m.get("ratings",{}).get("imdb",{}).get("value",0) >= 7: score += 15
        results.append({
            "kind": "movie", "title": m.get("title"), "year": m.get("year"), "score": score,
            "summary": m.get("overview","")[:300],
            "runtime": m.get("runtime"), "tmdbId": m.get("tmdbId"),
            "poster": m.get("remotePoster"), "genres": m.get("genres",[]) if isinstance(m.get("genres"), list) else [],
        })
    for s in sonarr_hits[:12]:
        score = 90
        if genres:
            s_genres = [g.lower() for g in s.get("genres",[])] if isinstance(s.get("genres"), list) else []
            if any(g in s_genres for g in genres): score += 50
            else: score -= 30
        results.append({
            "kind": "series", "title": s.get("title"), "year": s.get("year"), "score": score,
            "summary": s.get("overview","")[:300] if isinstance(s.get("overview"),str) else "",
            "tvdbId": s.get("tvdbId"),
        })
    results.sort(key=lambda r: -r["score"])
    return {"query": original, "genres": genres, "decade": decade, "results": results[:12]}

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

CSS = """
body{font-family:system-ui,Segoe UI,sans-serif;margin:0;background:#0f0f17;color:#eee;line-height:1.45}
header{background:linear-gradient(90deg,#6d28d9,#8b5cf6);padding:1.5rem 2rem;box-shadow:0 4px 12px rgba(0,0,0,.4)}
header h1{margin:0;color:#fff;font-size:1.4rem}
header .badge{background:rgba(255,255,255,.18);padding:.25rem .6rem;border-radius:1rem;color:#fff;font-size:.85rem;margin-left:1rem}
main{max-width:1100px;margin:1.5rem auto;padding:0 1rem 4rem}
h2{color:#fbbf24;border-bottom:1px solid #333;padding-bottom:.4rem}
.search-bar{display:flex;gap:.5rem;margin-bottom:1rem}
.search-bar input{flex:1;background:#1a1a25;color:#eee;border:1px solid #444;padding:.7rem 1rem;border-radius:.4rem;font-size:1rem}
.search-bar button{background:#8b5cf6;color:#fff;border:none;padding:0 1.4rem;border-radius:.4rem;font-weight:600;cursor:pointer}
.search-bar button:hover{background:#a78bfa}
.results{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-bottom:2rem}
.card{background:#1a1a25;border:1px solid #2a2a35;border-radius:.6rem;padding:.8rem;display:flex;flex-direction:column;gap:.4rem}
.card h3{margin:0;font-size:1rem;color:#fbbf24}
.card .year{color:#999;font-size:.85rem}
.card .summary{font-size:.85rem;color:#bbb;flex:1}
.card form{margin-top:.5rem}
.card button{background:#22c55e;color:#fff;border:none;padding:.4rem .8rem;border-radius:.4rem;cursor:pointer;width:100%;font-weight:600}
.card button:hover{background:#16a34a}
.card .already{background:#555;color:#fff;border:none;padding:.4rem .8rem;border-radius:.4rem;width:100%;cursor:not-allowed;opacity:0.7}
.card img{width:100%;border-radius:.4rem}
.packs{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1rem}
.pack{background:#1a1a25;border:1px solid #6d28d9;border-radius:.6rem;padding:1rem}
.pack h3{margin:0 0 .4rem;color:#fbbf24}
.pack .desc{font-size:.85rem;color:#999;margin-bottom:.5rem}
.pack ul{padding-left:1.2rem;margin:.3rem 0;font-size:.85rem;color:#ccc;max-height:140px;overflow:auto}
.pack form button{background:#6d28d9;color:#fff;border:none;padding:.5rem 1rem;border-radius:.4rem;cursor:pointer;font-weight:600}
.pack form button:hover{background:#7c3aed}
.status{background:#1a1a25;border:1px solid #333;border-radius:.6rem;padding:1rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.5rem;margin-bottom:1.5rem}
.status div{text-align:center}
.status div strong{display:block;font-size:1.4rem;color:#fbbf24}
.tonight-result{display:flex;gap:.5rem;align-items:start;padding:.5rem 0;border-bottom:1px solid #2a2a35}
.tonight-result .score{background:#8b5cf6;color:#fff;padding:.2rem .6rem;border-radius:.4rem;font-weight:600;min-width:60px;text-align:center}
.toast{background:#22c55e;color:#fff;padding:1rem;border-radius:.4rem;margin:1rem 0}
.toast.error{background:#dc2626}
"""

def _html(body, title="Library"):
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head>
<body><header><h1>📚 Dogebox Library <span class="badge">v0.0.3</span></h1></header>
<main>{body}</main>
<script src="/static/live.js"></script>
</body></html>"""

def _card(item, kind):
    title = item.get("title") or "?"
    year = item.get("year") or "?"
    runtime = item.get("runtime")
    overview = item.get("overview") or item.get("summary") or ""
    poster = item.get("remotePoster") or ""
    tmdb = item.get("tmdbId")
    tvdb = item.get("tvdbId")
    already = item.get("__already") or False
    id_key = "tmdbId" if kind == "movie" else "tvdbId"
    id_val = tmdb if kind == "movie" else tvdb
    poster_html = f'<img src="{poster}" alt="" loading="lazy">' if poster else ""
    runtime_html = f'<span class="year">{runtime} min</span>' if runtime else ""
    ellipsis = "..." if len(overview) > 200 else ""
    action = f'<form method="POST" action="/add/{kind}"><input type="hidden" name="id" value="{id_val}"><button>Add to {kind.title()}</button></form>' if not already else f'<button class="already" disabled>Already in library</button>'
    return f'<div class="card">{poster_html}<h3>{title}</h3><span class="year">{year}</span> {runtime_html}<p class="summary">{overview[:200]}{ellipsis}</p>{action}</div>'

def _status_html(snap):
    items = [
        ("Movies", snap.get("movies_count","?")),
        ("Shows", snap.get("series_count","?")),
        ("JF users", snap.get("jf_users","?")),
        ("Prowlarr indexers", f"{snap.get('prowlarr_indexers_enabled','?')}/{snap.get('prowlarr_indexers_total','?')}"),
    ]
    cells = "".join(f'<div>{k}<strong>{v}</strong></div>' for k,v in items)
    return f'<div class="status">{cells}</div>'

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
        up = _load_upstreams()
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path == "/static/live.js":
            self._send(200, "application/javascript", LIVE_JS)
            return

        if u.path == "/api/search":
            term = (qs.get("q") or [""])[0].strip()
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
            return self._json({"movies": m, "series": s})

        if u.path == "/api/status":
            return self._json(_status_snapshot(up))

        if u.path == "/api/tonight":
            q = (qs.get("q") or [""])[0].strip()
            if not q: return self._json({"error":"missing q"}, 400)
            return self._json(_tonight(up, q))

        if u.path == "/" or u.path == "/index.html":
            snap = _status_snapshot(up)
            body = _status_html(snap)
            body += '<form class="search-bar" method="GET" action="/search"><input id="q" name="q" placeholder="Search movies or shows..." autocomplete="off" autofocus><datalist id="suggest"></datalist><button>Search</button></form>'
            try:
                with open("/storage/config/starter-packs.json") as f:
                    packs = json.load(f)
            except Exception:
                packs = []
            body += '<h2>Starter Packs</h2><div class="packs">'
            for p in packs:
                items_html = "".join(f"<li>{t}</li>" for t in p.get("titles",[])[:10])
                body += f'<form method="POST" action="/pack" class="pack"><h3>{p["name"]}</h3><p class="desc">{p.get("description","")}</p><ul>{items_html}</ul><input type="hidden" name="pack" value="{p["name"]}"><button>Add all to {p.get("theme","library")}</button></form>'
            body += "</div>"
            body += '<h2>Tonight</h2><form class="search-bar" method="GET" action="/tonight"><input name="q" placeholder="I want something funny from the 90s, not too long..."><button>Find</button></form>'
            return self._render(_html(body))

        if u.path == "/search":
            term = (qs.get("q") or [""])[0].strip()
            if not term: return self._render(_html("<p>empty search</p>"))
            m = _search_radarr(up, term)
            s = _search_sonarr(up, term)
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
            cards = "".join(_card(x, "movie") for x in m) + "".join(_card(x, "series") for x in s)
            body = f'<p style="color:#999">Results for <b>{term}</b> &middot; <a href="/">back</a></p><div class="results">{cards}</div>' if (m or s) else f'<p>No results for <b>{term}</b>. <a href="/">back</a></p>'
            return self._render(_html(body))

        if u.path == "/tonight":
            q = (qs.get("q") or [""])[0].strip()
            rec = _tonight(up, q) if q else {"results":[]}
            rows = ""
            for r in rec.get("results", []):
                kind = r["kind"]
                id_key = "tmdbId" if kind == "movie" else "tvdbId"
                title = r["title"]
                year = r.get("year","")
                summary = r.get("summary","")[:200]
                ellipsis = "..." if len(summary) >= 200 else ""
                rows += f'<form class="tonight-result" method="POST" action="/add/{kind}"><div class="score">{r["score"]}</div><div style="flex:1"><b>{title}</b> ({year})<br><span style="color:#aaa">{summary}{ellipsis}</span></div><input type="hidden" name="id" value="{r.get(id_key)}"><button style="background:#22c55e;color:#fff;border:none;padding:.4rem .8rem;border-radius:.4rem;cursor:pointer">Add</button></form>'
            body = f'<p style="color:#999">Tonight for: <b>{q}</b> &middot; <a href="/">back</a></p>' + (rows or "<p>No results</p>")
            return self._render(_html(body))

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
                self._render(_html('<div class="toast error">Movie lookup failed</div><a href="/">back</a>'))
                return
            item = json.loads(body)[0]
            r = _add_movie(up, item, _quality_id(up, "movie"))
            cls = "toast" if r.get("ok") else "toast error"
            if r.get("already"):
                msg = "Already in your library."
            elif r.get("ok"):
                msg = "Added! Radarr will search for it and qB will pick it up."
            else:
                msg = f"Radarr returned {r.get('code')}: {r.get('body')}"
            self._render(_html(f'<div class="{cls}">{msg}</div><a href="/">back to library</a>'))
            return

        if u.path.startswith("/add/series/"):
            tvdb_id = int(form.get("id", ["0"])[0])
            code, body = _api_get(up["sonarr"]["url"], up["sonarr"]["key"], "/api/v3/series/lookup", {"term": f"tvdb:{tvdb_id}"})
            if code != 200 or not json.loads(body):
                self._render(_html('<div class="toast error">Series lookup failed</div><a href="/">back</a>'))
                return
            item = json.loads(body)[0]
            r = _add_series(up, item, _quality_id(up, "series"))
            cls = "toast" if r.get("ok") else "toast error"
            if r.get("already"):
                msg = "Already in your library."
            elif r.get("ok"):
                msg = "Added! Sonarr will search for it."
            else:
                msg = f"Sonarr returned {r.get('code')}: {r.get('body')}"
            self._render(_html(f'<div class="{cls}">{msg}</div><a href="/">back to library</a>'))
            return

        if u.path == "/pack":
            pack_name = form.get("pack", [""])[0]
            try:
                with open("/storage/config/starter-packs.json") as f:
                    packs = json.load(f)
            except Exception as e:
                self._render(_html(f'<div class="toast error">Pack file unreadable: {e}</div><a href="/">back</a>'))
                return
            pack = next((p for p in packs if p.get("name") == pack_name), None)
            if not pack:
                self._render(_html('<div class="toast error">Pack not found</div><a href="/">back</a>'))
                return
            results = []
            for t in pack.get("titles", []):
                kind = pack.get("theme")
                if kind == "movies":
                    res = _search_radarr(up, t)
                    if res: results.append(("movie", res[0]))
                else:
                    res = _search_sonarr(up, t)
                    if res: results.append(("series", res[0]))
            added = []
            for kind, item in results:
                if kind == "movie":
                    r = _add_movie(up, item, _quality_id(up, "movie"))
                else:
                    r = _add_series(up, item, _quality_id(up, "series"))
                added.append((kind, item.get("title"), r.get("ok"), r.get("already")))
            rows = "".join(
                f'<li>{"OK" if ok else ("SKIP" if already else "NO")} <b>{t}</b> ({k})</li>'
                for k, t, ok, already in added
            )
            skipped = len(pack.get("titles",[])) - len(added)
            body = f'<div class="toast">Pack <b>{pack_name}</b>: {sum(1 for _,_,ok,_ in added if ok)} added, {sum(1 for _,_,_,al in added if al)} already present, {skipped} not found.</div><ul>{rows}</ul><a href="/">back</a>'
            self._render(_html(body))
            return

        if u.path == "/import":
            url = form.get("url", [""])[0].strip()
            if not url: self._render(_html('<div class="toast error">no url</div><a href="/">back</a>')); return
            req = urllib.request.Request(url, headers={"User-Agent": "dogebox-library/0.0.3"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    code = r.status
                    body = r.read().decode("utf-8", errors="replace")
            except Exception as e:
                code = 0; body = str(e)
            if code != 200:
                self._render(_html(f'<div class="toast error">Fetch failed: HTTP {code}</div><a href="/">back</a>')); return
            if "imdb.com" in url and (body.lower().startswith("position") or "\t" in body):
                res = _import_imdb_csv(up, body, _quality_id(up, "movie"))
                rows = "".join(f"<li>{'OK' if r['added'] else 'NO'} <b>{r['title'] or r['input']}</b> ({r['kind']})</li>" for r in res)
                body_html = f'<div class="toast">Imported {sum(1 for r in res if r["added"])}/{len(res)} from IMDb list.</div><ul>{rows}</ul><a href="/">back</a>'
            else:
                body_html = '<div class="toast error">URL not recognised as IMDb list export. Try: https://www.imdb.com/list/ls.../export</div><a href="/">back</a>'
            self._render(_html(body_html))
            return

        self._send(404, "text/plain", "not found")

PORT = int(sys.argv[1])
TS = getattr(http.server, "ThreadingHTTPServer", None) or http.server.ThreadingTCPServer
with TS(("0.0.0.0", PORT), Handler) as s:
    s.allow_reuse_address = True
    s.serve_forever()
