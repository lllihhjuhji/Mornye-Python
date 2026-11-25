"""Mornye-Extension qobuz-web(qobuz-rest-api) 호환 어댑터 (/download-url/{id}?quality=...)."""

from __future__ import annotations

from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from ..normalize import as_list, clean, pick, to_duration_ms, to_int
from .base import SourceAdapter


class QobuzRestAdapter(SourceAdapter):
    name, kind = "qobuz_rest", "public"

    def _headers(self) -> dict[str, str]:
        return (
            {"X-API-Key": self.settings.qobuz_rest_api_key}
            if self.settings.qobuz_rest_api_key
            else {}
        )

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        data = await self.get_json(
            f"{self.settings.qobuz_rest_base}/search",
            params={"q": q, "limit": opts.limit},
            headers=self._headers(),
        )
        rows = (
            data
            if isinstance(data, list)
            else (data or {}).get("tracks")
            or (data or {}).get("items")
            or (data or {}).get("results")
            or []
        )
        out: list[Track] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            sid = clean(str(pick(r, "id", "track_id") or ""))
            title = clean(pick(r, "title", "name"))
            if not sid or not title:
                continue
            artists = as_list(pick(r, "artists", "artist", "performer"))
            out.append(
                Track(
                    id=f"qobuz_rest:{sid}",
                    source="qobuz_rest",
                    source_id=sid,
                    title=title,
                    artist=", ".join(artists) if artists else "Unknown Artist",
                    artists=artists,
                    album=clean(r.get("album")) or None,
                    duration_ms=to_duration_ms(r),
                    isrc=clean(r.get("isrc")) or None,
                    codec="flac",
                    container="flac",
                    sample_rate=to_int(pick(r, "sampleRate", "sample_rate")),
                    bit_depth=to_int(pick(r, "bitDepth", "bit_depth")),
                )
            )
        return out

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        q_map = {"STANDARD": "5", "LOSSLESS": "6", "HI_RES": "27"}
        data = await self.get_json(
            f"{self.settings.qobuz_rest_base}/download-url/{source_id}",
            params={"quality": q_map.get(quality, "27")},
            headers=self._headers(),
        )
        url = (data or {}).get("url") if isinstance(data, dict) else None
        if not url:
            raise SourceError("parse", "missing url in qobuz-rest-api response")
        return StreamInfo(
            url=str(url),
            headers=self._headers(),
            codec="flac",
            container="flac",
            manifest="none",
            sample_rate=to_int(pick(data, "sampleRate", "sample_rate")),
            bit_depth=to_int(pick(data, "bitDepth", "bit_depth")),
        )
