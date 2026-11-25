"""자체/유료 FLAC API 예시 어댑터. 엔드포인트와 인증 헤더는 환경변수에서 주입된다."""

from __future__ import annotations

from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from ..normalize import from_custom
from .base import SourceAdapter


class CustomFlacAdapter(SourceAdapter):
    name, kind = "custom", "extra"

    def _headers(self) -> dict[str, str]:
        return (
            {self.settings.custom_key_header: self.settings.custom_key}
            if self.settings.custom_key
            else {}
        )

    @staticmethod
    def _rows(data) -> list[dict]:
        rows = (
            data
            if isinstance(data, list)
            else (data or {}).get("results")
            or (data or {}).get("tracks")
            or (data or {}).get("data")
        )
        if rows is None or not isinstance(rows, list):
            raise SourceError("parse", "unexpected response shape (no list)")
        return [r for r in rows if isinstance(r, dict)]

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        data = await self.get_json(
            f"{self.settings.custom_base}/search",
            params={"q": q, "limit": opts.limit, "quality": opts.quality},
            headers=self._headers(),
        )
        return [t for t in (from_custom(r) for r in self._rows(data)) if t]

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        data = await self.get_json(
            f"{self.settings.custom_base}/stream/{source_id}",
            params={"quality": quality},
            headers=self._headers(),
        )
        if not isinstance(data, dict) or not data.get("url"):
            raise SourceError("parse", "missing stream url from custom")
        return StreamInfo(
            url=str(data["url"]),
            headers=self._headers(),
            codec=str(data.get("codec") or "flac").lower(),
            container=str(data.get("container") or "flac").lower(),
            manifest="none",
            sample_rate=data.get("sample_rate") or data.get("sampleRate"),
            bit_depth=data.get("bit_depth") or data.get("bitDepth"),
            bitrate=data.get("bitrate") or data.get("bitRate"),
            expires_at=data.get("expires_at") or data.get("expiresAt"),
        )
