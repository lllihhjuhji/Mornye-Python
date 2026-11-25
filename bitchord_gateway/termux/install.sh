#!/usr/bin/env bash
# Install the BitChord gateway on Termux.
#   bash bitchord_gateway/termux/install.sh [--with-mornye]
# --with-mornye also installs Mornye (the library, without its GUI/TUI) so the
# gateway can use it as a source.
set -eu

WITH_MORNYE=0
[ "${1:-}" = "--with-mornye" ] && WITH_MORNYE=1

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BASE="$HOME/.bitchord"
VENV="$BASE/venv"

if ! command -v pkg >/dev/null 2>&1; then
  echo "This script is for Termux (pkg not found)." >&2
  exit 1
fi

mkdir -p "$BASE" "$BASE/cache"

echo "==> Termux packages"
pkg update -y
pkg install -y python curl
if [ "$WITH_MORNYE" = 1 ]; then
  # Node.js runs Mornye's JavaScript extensions; ffmpeg/flac convert to FLAC.
  pkg install -y nodejs ffmpeg flac
fi
# Prebuilt wheels from Termux's own repo when they exist (no Rust/C compile).
# Each one is optional: a missing package only means pip builds it instead.
for p in python-cryptography python-pillow python-pydantic; do
  pkg install -y "$p" 2>/dev/null || echo "   ($p not available from pkg, pip will handle it)"
done

echo "==> Python environment ($VENV)"
# --system-site-packages so the pkg-installed wheels above are visible.
python -m venv --system-site-packages "$VENV"
PY="$VENV/bin/python"
"$PY" -m pip install --upgrade pip

if ! "$PY" -c "import pydantic_core" 2>/dev/null; then
  echo "==> pydantic-core has to be built (Rust). This takes several minutes."
  pkg install -y rust binutils clang make
  ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
  export ANDROID_API_LEVEL
fi
"$PY" -m pip install -r "$REPO/bitchord_gateway/requirements-termux.txt"

if [ "$WITH_MORNYE" = 1 ]; then
  echo "==> Mornye (library only)"
  "$PY" -m pip install -r "$HERE/requirements-mornye.txt"
  "$PY" -m pip install --no-deps "$REPO"
fi

if [ ! -f "$BASE/gateway.env" ]; then
  SECRET="$($PY -c 'import secrets;print(secrets.token_hex(32))')"
  sed "s/__GENERATED_BY_INSTALL__/$SECRET/" "$HERE/gateway.env.example" > "$BASE/gateway.env"
  chmod 600 "$BASE/gateway.env"
  [ "$WITH_MORNYE" = 1 ] || sed -i 's/^MORNYE_BACKEND_ENABLED=.*/MORNYE_BACKEND_ENABLED=false/; s/^DEFAULT_CHAIN=.*/DEFAULT_CHAIN=subsonic/' "$BASE/gateway.env"
  echo "==> Wrote $BASE/gateway.env — edit it to choose your sources."
fi

cat <<MSG

Done.
  start : bash $HERE/start.sh
  status: bash $HERE/status.sh
  stop  : bash $HERE/stop.sh
Android may stop background apps: see docs/guide/bitchord-gateway-termux.md
(battery optimisation and the Termux wake lock).
MSG
