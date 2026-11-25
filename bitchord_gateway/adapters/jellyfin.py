"""Jellyfin 셀프호스팅 음악 라이브러리 어댑터 (원본 FLAC 스트림)."""

from __future__ import annotations

from ..models import QueryOptions, StreamInfo, Track
from ..normalize import clean
from .base import SourceAdapter


class JellyfinAdapter(SourceAdapter):
    name, kind = "jellyfin", "public"

    def _headers(self) -> dict[str, str]:
        return {"X-Emby-Token": self.settings.jellyfin_api_key}

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        url = f"{self.settings.jellyfin_base}/Users/{self.settings.jellyfin_user_id}/Items"
        data = await self.get_json(
            url,
            params={
                "searchTerm": q,
                "IncludeItemTypes": "Audio",
                "Recursive": "true",
                "Limit": opts.limit,
                "Fields": "MediaSources,RunTimeTicks,Artists,Album",
            },
            headers=self._headers(),
        )
        items = (data or {}).get("Items") or []
        out: list[Track] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = clean(str(it.get("Id") or ""))
            title = clean(it.get("Name"))
            if not sid or not title:
                continue
            artists = [clean(a) for a in (it.get("Artists") or []) if clean(a)]
            ticks = it.get("RunTimeTicks") or 0
            dur_ms = int(ticks // 10000) if ticks else None
            out.append(
                Track(
                    id=f"jellyfin:{sid}",
                    source="jellyfin",
                    source_id=sid,
                    title=title,
                    artist=", ".join(artists) if artists else "Unknown Artist",
                    artists=artists,
                    album=clean(it.get("Album")) or None,
                    duration_ms=dur_ms,
                    codec="flac",
                    container="flac",
                )
            )
        return out

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        return StreamInfo(
            url=f"{self.settings.jellyfin_base}/Audio/{source_id}/stream?static=true",
            headers=self._headers(),
            codec="flac",
            container="flac",
            manifest="none",
        )
