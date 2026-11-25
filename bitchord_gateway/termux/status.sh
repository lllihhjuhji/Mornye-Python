#!/usr/bin/env bash
set -eu
BASE="$HOME/.bitchord"
set -a
# shellcheck disable=SC1091
[ -f "$BASE/gateway.env" ] && . "$BASE/gateway.env"
set +a
"$BASE/venv/bin/python" - <<PY
import json, os, urllib.request
url = "http://127.0.0.1:%s/health" % os.environ.get("PORT", "8000")
try:
    h = json.load(urllib.request.urlopen(url, timeout=3))
    print("running; sources:", ", ".join(h["sources"]) or "(none)")
    print("circuits:", h["circuits"])
except Exception as e:
    print("not reachable:", type(e).__name__, e)
PY
