#!/usr/bin/env bash
set -eu
PIDFILE="$HOME/.bitchord/gateway.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  kill "$(cat "$PIDFILE")"
  rm -f "$PIDFILE"
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
  echo "Stopped."
else
  rm -f "$PIDFILE"
  echo "Not running."
fi
