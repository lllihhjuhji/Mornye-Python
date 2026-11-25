#!/usr/bin/env bash
# Start the gateway in the background; logs go to ~/.bitchord/gateway.log.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BASE="$HOME/.bitchord"
PIDFILE="$BASE/gateway.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Already running (pid $(cat "$PIDFILE"))."
  exit 0
fi
[ -f "$BASE/gateway.env" ] || { echo "Run termux/install.sh first." >&2; exit 1; }

# Keep the CPU awake while the screen is off (harmless if the command is absent).
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

set -a
# shellcheck disable=SC1091
. "$BASE/gateway.env"
set +a

cd "$REPO"
nohup "$BASE/venv/bin/python" -m bitchord_gateway >> "$BASE/gateway.log" 2>&1 &
echo $! > "$PIDFILE"
sleep 2
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Started (pid $(cat "$PIDFILE")) on http://${HOST:-127.0.0.1}:${PORT:-8000}"
  echo "Log: $BASE/gateway.log"
else
  echo "Failed to start; last log lines:" >&2
  tail -n 20 "$BASE/gateway.log" >&2
  rm -f "$PIDFILE"
  exit 1
fi
