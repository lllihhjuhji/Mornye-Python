"""Subsonic / Navidrome / Gonic 셀프호스팅 라이브러리 어댑터 (원본 FLAC 스트림)."""

from __future__ import annotations

import hashlib
import secrets
from urllib.parse import urlencode

from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track
from ..normalize import from_subsonic
from .base import SourceAdapter


class SubsonicAdapter(SourceAdapter):
    name, kind = "subsonic", "public"

    def _auth_params(self) -> dict[str, str]:
        salt = secrets.token_hex(6)
        token = hashlib.md5(
            f"{self.settings.subsonic_password}{salt}".encode()
        ).hexdigest()
        return {
            "u": self.settings.subsonic_user,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "bitchord-gateway",
            "f": "json",
        }

    async def search(self, q: str, opts: QueryOptions) -> list[Track]:
        params = {
            **self._auth_params(),
            "query": q,
            "songCount": opts.limit,
            "albumCount": 0,
            "artistCount": 0,
        }
        data = await self.get_json(
            f"{self.settings.subsonic_base}/rest/search3.view", params=params
        )
        resp = (data or {}).get("subsonic-response") or {}
        if resp.get("status") != "ok":
            err = resp.get("error") or {}
            raise SourceError("http_error", err.get("message", "subsonic error"))
        songs = ((resp.get("searchResult3") or {}).get("song")) or []
        out: list[Track] = []
        for s in songs:
            if not isinstance(s, dict):
                continue
            t = from_subsonic(s)
            if t:
                out.append(t)
        return out

    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo:
        # format=raw 는 트랜스코딩 없이 원본 FLAC을 그대로 스트리밍한다.
        q = urlencode({**self._auth_params(), "id": source_id, "format": "raw"})
        return StreamInfo(
            url=f"{self.settings.subsonic_base}/rest/stream.view?{q}",
            codec="flac",
            container="flac",
            manifest="none",
        )
