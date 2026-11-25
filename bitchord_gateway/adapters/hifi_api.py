"""Mornye-Extension tidal-web(hifi-api) 호환 어댑터 (/track/?id=...&quality=...)."""

from __future__ import annotations

from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from ..normalize import as_list, clean, pick, to_duration_ms, to_int
from .base import SourceAdapter


class HifiApiAdapter(SourceAdapter):
    name, kind = "hifi_api", "public"

    def _headers(self) -> dict[str, str]:
        return (
            {"X-API-Key": self.settings.hifi_api_key}
            if self.settings.hifi_api_key
            else {}
        )

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        data = await self.get_json(
            f"{self.settings.hifi_api_base}/search/",
            params={"s": q, "limit": opts.limit},
            headers=self._headers(),
        )
        rows = (
            data
            if isinstance(data, list)
            else (data or {}).get("data", {}).get("items")
            or (data or {}).get("items")
            or (data or {}).get("tracks")
            or []
        )
        out: list[Track] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            sid = clean(str(pick(r, "id", "trackId") or ""))
            title = clean(pick(r, "title", "name"))
            if not sid or not title:
                continue
            artist_val = pick(r, "artists", "artist")
            if isinstance(artist_val, dict):
                artist_val = artist_val.get("name", "")
            artists = as_list(artist_val)
            album_val = r.get("album")
            album_name = (
                album_val.get("title")
                if isinstance(album_val, dict)
                else clean(album_val)
            )
            out.append(
                Track(
                    id=f"hifi_api:{sid}",
                    source="hifi_api",
                    source_id=sid,
                    title=title,
                    artist=", ".join(artists) if artists else "Unknown Artist",
                    artists=artists,
                    album=clean(album_name) or None,
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
        q_map = {"STANDARD": "LOW", "LOSSLESS": "LOSSLESS", "HI_RES": "HI_RES_LOSSLESS"}
        data = await self.get_json(
            f"{self.settings.hifi_api_base}/track/",
            params={"id": source_id, "quality": q_map.get(quality, "LOSSLESS")},
            headers=self._headers(),
        )
        payload = (
            (data or {}).get("data")
            if isinstance(data, dict) and isinstance(data.get("data"), dict)
            else data
        )
        if not isinstance(payload, dict):
            raise SourceError("parse", "unexpected hifi-api track response")
        url = pick(payload, "OriginalTrackUrl", "url", "streamUrl")
        if not url and isinstance(payload.get("urls"), list) and payload["urls"]:
            url = payload["urls"][0]
        if not url:
            raise SourceError("parse", "missing stream url in hifi-api response")
        return StreamInfo(
            url=str(url),
            headers=self._headers(),
            codec=clean(pick(payload, "codec", "audioQuality") or "flac").lower(),
            container="flac",
            manifest="none",
            sample_rate=to_int(pick(payload, "sampleRate", "sample_rate")),
            bit_depth=to_int(pick(payload, "bitDepth", "bit_depth")),
        )
