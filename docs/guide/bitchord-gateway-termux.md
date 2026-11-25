# BitChord Gateway on Termux (Android)

Runs [the gateway](bitchord-gateway.md) directly on a phone. Docker is not
available there, and some of Mornye's desktop dependencies do not build on
Android, so this setup installs only what the gateway needs.

> Written without a device to test on: the scripts are syntax-checked and the
> config is verified, but the first install on a real phone is the real test.
> If a step fails, the error and your Android/Termux versions are what to look at.

## Install

Use the Termux build from F-Droid or GitHub (the Play Store one is outdated).
Get the repository onto the phone (`pkg install git`, then `git clone`), then:

```bash
cd Mornye-Python
bash bitchord_gateway/termux/install.sh --with-mornye   # Mornye as the source
# or, to only relay other servers (Subsonic, Jellyfin, …):
bash bitchord_gateway/termux/install.sh
```

It installs Python (and, with `--with-mornye`, Node.js, ffmpeg and flac) from
`pkg`, creates `~/.bitchord/venv`, installs the requirements, and writes
`~/.bitchord/gateway.env` with a generated `SIGNING_SECRET`.

- **Mornye is installed without its GUI/TUI.** `pywebview`, `textual`,
  `python-mpv`, `numpy` and the other desktop-only packages are skipped; the
  gateway never imports them
  ([`termux/requirements-mornye.txt`](../../bitchord_gateway/termux/requirements-mornye.txt)).
- **`pydantic-core` may have to compile** (Rust) if `pkg` has no prebuilt one:
  expect several minutes and a warm phone. The script sets `ANDROID_API_LEVEL`
  for that build.
- The plain `uvicorn` is used, not `uvicorn[standard]`: `uvloop` and `httptools`
  do not work on Android, and the gateway runs fine without them.

## Configure

Edit `~/.bitchord/gateway.env`. The defaults for a phone:

| Setting | Default here | Why |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Only apps on the phone reach it. Use `0.0.0.0` to let other devices on your Wi-Fi connect |
| `MORNYE_BACKEND_CACHE_MAX_MB` | `1024` | Phone storage is small; old tracks are dropped first |
| `MORNYE_BACKEND_STREAM_TIMEOUT` | `300` | The first play waits for a download over mobile data |
| `READ_TIMEOUT` / `TOTAL_DEADLINE` | `12` / `25` | Mornye's search is slower than a plain proxy |

Mornye ships with no provider: install an extension in Mornye first
([Extensions](extensions.md)), and set `MORNYE_BACKEND_SERVICES` if you want a
specific one.

## Run

```bash
bash bitchord_gateway/termux/start.sh     # background; log: ~/.bitchord/gateway.log
bash bitchord_gateway/termux/status.sh    # sources and circuit-breaker state
bash bitchord_gateway/termux/stop.sh
```

Add `http://127.0.0.1:8000/manifest.json` (or
`/<ADDON_PATH_SECRET>/manifest.json` if you set one) as the addon in BitChord.
Whether the app accepts a plain-HTTP localhost address depends on the app; if it
insists on HTTPS, put a tunnel in front (Cloudflare Tunnel, Tailscale) and use
that address.

## Keeping it alive

Android stops background apps to save battery, which kills the gateway:

- `start.sh` takes Termux's wake lock (`termux-wake-lock`) so the CPU stays
  awake with the screen off; Termux shows a notification while it holds it.
- In Android settings, set Termux's battery use to **Unrestricted** (wording
  varies by maker), and keep Termux's notification.
- If it still dies, run `start.sh` again; it is safe to repeat (it will not
  start a second copy).
