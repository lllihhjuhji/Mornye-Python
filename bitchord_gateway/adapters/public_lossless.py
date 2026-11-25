"""공개/커뮤니티 무손실 API 어댑터 (/search, /resolve-isrc, /stream/{id})."""

from __future__ import annotations

from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from ..normalize import from_public_lossless
from .base import SourceAdapter


class PublicLosslessAdapter(SourceAdapter):
    name, kind = "public_lossless", "public"

    @staticmethod
    def _rows(data) -> list[dict]:
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            rows = (
                data.get("tracks")
                or data.get("items")
                or data.get("results")
                or data.get("data")
                or []
            )
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
        raise SourceError("parse", "unexpected response shape from public_lossless")

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        data = await self.get_json(
            f"{self.settings.public_lossless_base}/search",
            params={"q": q, "limit": opts.limit, "quality": opts.quality},
        )
        return [t for t in (from_public_lossless(r) for r in self._rows(data)) if t]

    async def resolve_isrc(self, isrc: str, opts: QueryOptions) -> list[Track]:
        try:
            data = await self.get_json(
                f"{self.settings.public_lossless_base}/resolve-isrc",
                params={"isrc": isrc, "quality": opts.quality},
            )
        except SourceError as e:
            if e.http_status == 404:
                return []
            raise
        if isinstance(data, dict) and data.get("track"):
            t = from_public_lossless(data["track"])
            return [t] if t else []
        if isinstance(data, dict) and data.get("id"):
            t = from_public_lossless(data)
            return [t] if t else []
        return []

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        data = await self.get_json(
            f"{self.settings.public_lossless_base}/stream/{source_id}",
            params={"quality": quality},
        )
        if not isinstance(data, dict) or not data.get("url"):
            raise SourceError("parse", "missing stream url from public_lossless")
        return StreamInfo(
            url=str(data["url"]),
            codec=str(data.get("codec") or "flac").lower(),
            container=str(data.get("container") or "flac").lower(),
            manifest="none",
            sample_rate=data.get("sample_rate") or data.get("sampleRate"),
            bit_depth=data.get("bit_depth") or data.get("bitDepth"),
            bitrate=data.get("bitrate") or data.get("bitRate"),
            expires_at=data.get("expires_at") or data.get("expiresAt"),
        )
