"""Mornye-Python as a gateway source.

Mornye is a downloader, not a streaming API: its extensions write a finished
file rather than hand back a URL. This adapter bridges the two:

* search / ISRC lookup go through Mornye's metadata client;
* a stream request downloads the track once through whichever extensions the
  operator installed in Mornye, converts it to FLAC (the only format the
  BitChord addon contract advertises), keeps it in a size-capped cache and
  hands the file to ``/audio/{token}``, which serves it with Range support.

Nothing here chooses a provider: ``MORNYE_BACKEND_SERVICES`` and the registries
configured in Mornye decide that, exactly as they do for Mornye itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..config import ConfigError, Settings
from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from .base import SourceAdapter

log = logging.getLogger("gateway.mornye")

_ID_OK = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_QUALITY = {"STANDARD": "LOSSLESS", "LOSSLESS": "LOSSLESS", "HI_RES": "HI_RES_LOSSLESS"}
# A file touched this recently may still be streaming to a player.
_EVICT_GRACE_S = 600


class Backend(Protocol):
    """What the adapter needs from Mornye; tests substitute a fake."""

    async def search(self, query: str, limit: int) -> list[Any]: ...

    async def download(self, track_id: str) -> str: ...

    async def aclose(self) -> None: ...


def _by_id(metadata, **_ctx) -> str:
    """Name the file after the catalogue id, so the cache can find it again."""
    return str(metadata.id)


class MornyeBackend:
    """The real thing: one long-lived AsyncMornye per quality tier."""

    def __init__(self, settings: Settings, quality: str, sync_extensions: bool):
        self._settings, self._quality = settings, quality
        self._sync = sync_extensions
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _get(self) -> Any:
        async with self._lock:
            if self._client is None:
                from mornye import AsyncMornye

                client = AsyncMornye(
                    output_dir=str(
                        Path(self._settings.mornye_cache_dir) / self._quality
                    ),
                    services=list(self._settings.mornye_services) or None,
                    filename_format=_by_id,
                    quality=self._quality,
                    allow_fallback=True,
                    embed_lyrics=False,
                    enrich_metadata=False,
                    transcode_to="flac",
                    transcode_keep_original=False,
                    sync_extensions=self._sync,
                )
                await client.__aenter__()
                self._client = client
            return self._client

    async def search(self, query: str, limit: int) -> list[Any]:
        client = await self._get()
        results = await client.search(query, limit=limit)
        return list(results.get("tracks") or [])

    async def download(self, track_id: str) -> str:
        from mornye import DownloadRequest

        client = await self._get()
        report = await client.download_request(
            DownloadRequest(
                sources=[f"https://open.spotify.com/track/{track_id}"],
                config=client.application_config(),
            )
        )
        for ok in report.succeeded:
            if ok.file_path:
                return ok.file_path
        for skipped in report.skipped:
            if skipped.file_path:
                return skipped.file_path
        reason = report.failed[0].reason if report.failed else "no provider matched"
        raise SourceError("download_failed", str(reason)[:200])

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class MornyeAdapter(SourceAdapter):
    name, kind = "mornye", "public"

    def __init__(self, client: httpx.AsyncClient, settings: Settings, backends=None):
        super().__init__(client, settings)
        if backends is None and importlib.util.find_spec("mornye") is None:
            raise ConfigError(
                "MORNYE_BACKEND_ENABLED=true needs the mornye package "
                "(pip install mornye, or pip install . from the repository)"
            )
        # Downloads can take far longer than a search; the orchestrator reads
        # this instead of its short per-attempt budget.
        self.stream_timeout = settings.mornye_stream_timeout
        self.cache_dir = Path(settings.mornye_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._backends: dict[str, Backend] = dict(backends or {})
        self._backends_given = backends is not None
        self._inflight: dict[str, asyncio.Task] = {}
        self._first = True

    # -- plumbing -----------------------------------------------------------

    def _backend(self, mornye_quality: str) -> Backend:
        be = self._backends.get(mornye_quality)
        if be is None:
            if self._backends_given:
                be = next(iter(self._backends.values()))
            else:
                be = MornyeBackend(self.settings, mornye_quality, self._first)
                self._first = False  # extensions are synced once, by the first
            self._backends[mornye_quality] = be
        return be

    async def aclose(self) -> None:
        for task in self._inflight.values():
            task.cancel()
        for be in set(self._backends.values()):
            with contextlib.suppress(Exception):
                await be.aclose()

    @staticmethod
    def _track(t: Any) -> Track | None:
        sid = str(getattr(t, "id", "") or "")
        title = str(getattr(t, "title", "") or "").strip()
        if not _ID_OK.match(sid) or not title:
            return None
        names = list(getattr(t, "artist_names", None) or [])
        joined = str(getattr(t, "artists", "") or "")
        if not names:
            names = [a.strip() for a in joined.split(",") if a.strip()]
        return Track(
            id=f"mornye:{sid}",
            source="mornye",
            source_id=sid,
            title=title,
            artist=", ".join(names) or "Unknown Artist",
            artists=names,
            album=str(getattr(t, "album", "") or "") or None,
            duration_ms=int(getattr(t, "duration_ms", 0) or 0) or None,
            isrc=str(getattr(t, "isrc", "") or "").upper() or None,
            codec="flac",
            container="flac",
            cover_url=str(getattr(t, "cover_url", "") or "") or None,
        )

    async def _call(self, coro):
        try:
            return await coro
        except SourceError:
            raise
        except (asyncio.CancelledError, TimeoutError):
            raise
        except Exception as e:
            raise SourceError(
                "upstream", f"{type(e).__name__}: {e}"[:200], retryable=False
            ) from e

    # -- BitChord operations ------------------------------------------------

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        rows = await self._call(self._backend("LOSSLESS").search(q, opts.limit))
        out = (self._track(t) for t in rows[: opts.limit])
        return [t for t in out if t]

    async def resolve_isrc(self, isrc: str, opts: QueryOptions) -> list[Track]:
        want = isrc.strip().upper()
        rows = await self._call(self._backend("LOSSLESS").search(f"isrc:{want}", 5))
        # Only an exact ISRC match counts: a near hit would play the wrong
        # recording under the right ID.
        hits = [
            t for t in rows if str(getattr(t, "isrc", "") or "").strip().upper() == want
        ]
        out = (self._track(t) for t in hits[:1])
        return [t for t in out if t]

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        if not _ID_OK.match(source_id):
            raise SourceError("bad_request", "invalid track id")
        mq = _QUALITY.get(quality, "LOSSLESS")
        path = self._cached(mq, source_id)
        if path is None:
            key = f"{mq}:{source_id}"
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._fetch(mq, source_id))
                self._inflight[key] = task
                task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))
            # shield: the orchestrator cancels a waiter that runs out of time,
            # but the download should finish for the player's retry.
            path = await self._call(asyncio.shield(task))
        suffix = os.path.splitext(path)[1].lstrip(".").lower() or "flac"
        return StreamInfo(
            url="",
            local_path=path,
            codec=suffix,
            container=suffix,
            manifest="none",
        )

    # -- cache --------------------------------------------------------------

    def _cached(self, mq: str, source_id: str) -> str | None:
        folder = self.cache_dir / mq
        for p in sorted(folder.glob(f"{source_id}.*")):
            if p.suffix.lower() in (".part", ".tmp") or not p.is_file():
                continue
            if p.stat().st_size > 0:
                with contextlib.suppress(OSError):
                    os.utime(p)
                return str(p)
        return None

    async def _fetch(self, mq: str, source_id: str) -> str:
        t0 = time.monotonic()
        path = await self._backend(mq).download(source_id)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise SourceError("download_failed", "provider returned no audio file")
        log.info(
            "mornye fetched %s (%s) in %.1fs", source_id, mq, time.monotonic() - t0
        )
        await asyncio.get_running_loop().run_in_executor(None, self._evict, path)
        return path

    def _evict(self, keep: str) -> None:
        """Drop the least recently used files once the cache is over its cap."""
        cap = self.settings.mornye_cache_max_mb * 1024 * 1024
        files = []
        for p in self.cache_dir.rglob("*"):
            if p.is_file():
                with contextlib.suppress(OSError):
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))
        total = sum(size for _, size, _ in files)
        now = time.time()
        for mtime, size, p in sorted(files):
            if total <= cap:
                break
            if str(p) == keep or now - mtime < _EVICT_GRACE_S:
                continue
            with contextlib.suppress(OSError):
                p.unlink()
                total -= size
