{ pkgs ? import <nixpkgs> {} }:

# Dogebox Library pup.
#
# Unified search + one-click add across the existing Radarr + Sonarr +
# Prowlarr + Jellyfin stack. No new indexer, no new download pipeline, no
# new library model. Everything proxies to the existing apps via their
# REST APIs.
#
# Features by version (all included in v0.0.3):
#   - v0.0.1: Unified search (movies + shows), one-click add, starter packs,
#               live counts (movies / shows / quarantined / Jellyfin users)
#   - v0.0.2: IMDb/Trakt watchlist import (paste URL → bulk-add to Radarr/Sonarr)
#   - v0.0.3: "Tonight" panel: free-text mood query → ranked recs (no LLM;
#             keyword/genre/year extraction against Radarr/Sonarr lookups)
#
# All upstream APIs are configured via /storage/config/upstreams.json
# (written at first boot by the install; user can edit manually).
#
# Layout:
#   /storage/config/                       writable config + log dir
#   /storage/config/upstreams.json         Radarr/Sonarr/Prowlarr/Jellyfin URLs + keys
#   /storage/config/starter-packs.json     bundled starter pack definitions
#   /storage/config/library.log            request log
let
  python = pkgs.python3;

  # The Python script + the tiny JS file are bundled in as separate
  # writeText derivations. No more heredoc quoting nightmares.
  webScript = pkgs.writeText "library-web.py" (builtins.readFile ./library-web.py);
  liveJs = pkgs.writeText "live.js" (builtins.readFile ./live.js);

  starterPacks = pkgs.writeText "starter-packs.json" ''
    [
      {
        "name": "Public Domain Essentials",
        "description": "10 fully-legal public-domain films — Chaplin, Keaton, Murnau, more. All on archive.org via Prowlarr.",
        "theme": "movies",
        "titles": ["A Trip to the Moon", "The Great Train Robbery", "Nosferatu", "The General", "Metropolis", "The Passion of Joan of Arc", "Safety Last!", "Nosferatu the Vampyre", "The Kid", "Modern Times"]
      },
      {
        "name": "Documentary Hour",
        "description": "Short, acclaimed public-domain documentaries for a quiet evening.",
        "theme": "movies",
        "titles": ["The City of Honey", "San Francisco Earthquake", "The Life and Death of 9413: a Hollywood Extra", "Why Man Creates", "Power of the Press"]
      },
      {
        "name": "Classic Sci-Fi",
        "description": "Public-domain sci-fi films from the 50s/60s. Cult classics.",
        "theme": "movies",
        "titles": ["The Day the Earth Froze", "It Conquered the World", "The Amazing Colossal Man", "Teenagers from Outer Space", "The Hideous Sun Demon"]
      },
      {
        "name": "Animated Shorts",
        "description": "Pre-1950 public-domain animated shorts — perfect for a kid's movie night.",
        "theme": "movies",
        "titles": ["Steamboat Willie", "Flowers and Trees", "Three Little Pigs", "The Tortoise and the Hare", "Fantasia (excerpt)"]
      },
      {
        "name": "Classic TV Pilots",
        "description": "Public-domain classic television pilots — anthology series intros.",
        "theme": "shows",
        "titles": ["The Twilight Zone", "Alfred Hitchcock Presents", "The Outer Limits", "You Are There", "Tales of Tomorrow"]
      }
    ]
  '';

  runScript = pkgs.writeScriptBin "run.sh" ''
    #!${pkgs.stdenv.shell}
    set -e
    MKDIR=${pkgs.coreutils}/bin/mkdir
    CP=${pkgs.coreutils}/bin/cp
    ECHO=${pkgs.coreutils}/bin/echo
    CAT=${pkgs.coreutils}/bin/cat

    $MKDIR -p /storage/config

    # On first boot, write a placeholder upstreams.json with the canonical
    # LAN addresses but empty API keys. The user fills the keys via the
    # pup card on the Dogebox dashboard, or by editing the file directly.
    if [ ! -f /storage/config/upstreams.json ]; then
      $CAT > /storage/config/upstreams.json <<JSON
    {
      "radarr":   {"url": "http://10.0.0.98:10003", "key": ""},
      "sonarr":   {"url": "http://10.0.0.98:10004", "key": ""},
      "prowlarr": {"url": "http://10.0.0.98:10006", "key": ""},
      "jellyfin": {"url": "http://10.0.0.98:18081", "key": ""}
    }
JSON
      $ECHO "[library-pup] wrote placeholder upstreams.json — fill in API keys via the dashboard pup card"
    fi

    # Stage the bundled starter packs + JS into /storage/config/ so the
    # Python script can read them at runtime.
    $CP ${starterPacks} /storage/config/starter-packs.json
    $CP ${liveJs}        /storage/config/live.js

    # Stage the Python script too (it lives next to live.js so the
    # relative path resolution works).
    $CP ${webScript}    /storage/config/library-web.py

    # Start the Python web server. live.js is served as a static route.
    $ECHO "[library-pup] starting on :9100"
    exec ${python}/bin/python3 /storage/config/library-web.py 9100
  '';

in
{
  library = runScript;
}
