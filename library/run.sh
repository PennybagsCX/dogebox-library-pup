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
