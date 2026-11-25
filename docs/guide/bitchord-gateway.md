# BitChord Gateway

`bitchord_gateway/` is a small, separate FastAPI service that implements the
BitChord addon contract (`/manifest.json`, `/search`, `/resolve-isrc`,
`/stream/{id}`, and an `/audio/{token}` HTTP 206 range proxy). It relays
searches and streams from sources **you** configure and tries them in order,
with timeouts, retries and a circuit breaker per source.

It is not installed by `pip install mornye` and shares no state with the Mornye
web app; it reads its own environment variables (listed in
[`bitchord_gateway/.env.example`](../../bitchord_gateway/.env.example)). Like
the rest of the project, it ships with no source configured. Besides relaying
other servers, it can use **Mornye itself as the source** — see
[Using Mornye as the source](#using-mornye-as-the-source).

## Run

```bash
pip install -r bitchord_gateway/requirements.txt   # fastapi, uvicorn, httpx, pydantic (relay-only)
cp bitchord_gateway/.env.example .env && set -a && source .env && set +a
python -m bitchord_gateway          # HOST (0.0.0.0), PORT (8000), WEB_CONCURRENCY (1)
```

or with Docker, from the repository root:

```bash
docker build -f Dockerfile.gateway -t bitchord-gateway .
docker run --env-file .env -p 8000:8000 bitchord-gateway
```

Set `SIGNING_SECRET` to a long random string (`APP_ENV=prod` refuses to start
without one, and the `.env.example` placeholder is not a secret), and put the service behind an HTTPS reverse proxy with
`proxy_buffering off`.

On an Android phone, see [BitChord Gateway on Termux](bitchord-gateway-termux.md).

## Sources

`DEFAULT_CHAIN` lists the sources tried in order:

| Source | Configured by |
| --- | --- |
| `public_lossless` | `PUBLIC_LOSSLESS_BASE_URL` |
| `subsonic` | `SUBSONIC_BASE_URL`, `SUBSONIC_USER`, `SUBSONIC_PASSWORD` |
| `jellyfin` | `JELLYFIN_BASE_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_USER_ID` |
| `hifi_api` | `HIFI_API_BASE_URL`, `HIFI_API_KEY` |
| `qobuz_rest` | `QOBUZ_REST_BASE_URL`, `QOBUZ_REST_API_KEY` |
| `mornye` | `MORNYE_BACKEND_ENABLED=true` (see below) |
| `custom` | `CUSTOM_BASE_URL`, `CUSTOM_API_KEY`, `CUSTOM_KEY_HEADER` |

`custom` only runs when requested with `?include=custom` or listed in
`AUTO_EXTRA_SOURCES`.

## Using Mornye as the source

BitChord expects a URL it can stream, while Mornye's extensions download a
finished file. The `mornye` source bridges the two:

1. **Search and ISRC lookup** use Mornye's own metadata client. `/resolve-isrc`
   accepts only an exact ISRC match, so a near hit never plays under the wrong ID.
2. **A stream request** downloads the track once through the extensions you
   installed in Mornye, converts it to **FLAC** (the only format the addon
   contract advertises, whatever the extension delivered), and stores it in a
   cache. Concurrent requests for one track share a single download.
3. **`/audio/{token}`** then serves the cached file with HTTP `206` range
   support, so seeking works as it does for relayed sources.

```bash
pip install .                       # from the repository root: installs mornye
export MORNYE_BACKEND_ENABLED=true
export DEFAULT_CHAIN=mornye         # or mornye,subsonic to fall back to a server
python -m bitchord_gateway
```

Mornye ships with no provider, so install and configure at least one
extension first ([Extensions](extensions.md)); `MORNYE_BACKEND_SERVICES`
(e.g. `ext:tidal-web`) picks which. The first `/stream` of a track waits for
its download (up to `MORNYE_BACKEND_STREAM_TIMEOUT`, 180 s); if BitChord gives
up sooner the download still finishes, and the retry is served from the cache.
The cache is capped by `MORNYE_BACKEND_CACHE_MAX_MB`; the least recently used
files go first. Searches have to fit `READ_TIMEOUT`/`TOTAL_DEADLINE`: raise them
if Mornye's search is slower than the defaults.

`Dockerfile.gateway` installs Mornye (with Node.js, ffmpeg and flac) for this.
Providers that need a browser solver are not supported by that image; use the
full Mornye image's setup if you depend on one.

## Register in BitChord

With `ADDON_PATH_SECRET` set, add `https://your-domain/<secret>/manifest.json`
under **Settings → Sources → Add addon**; without it,
`https://your-domain/manifest.json`.

## Tests

```bash
pytest tests/test_bitchord_gateway_core.py tests/test_bitchord_gateway_api.py
```

Add `tests/test_bitchord_gateway_mornye.py` for the Mornye source (it uses a
fake backend, so Mornye and its extensions are not needed). All use mock
transports; nothing reaches the network.
