"""소스 어댑터 추상 기반: 검색, ISRC 매칭, 스트림 URL 해석을 정의한다."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..config import Settings
from ..errors import SourceError
from ..models import QueryOptions, StreamInfo, Track


class SourceAdapter(ABC):
    name: str = ""
    kind: str = "public"  # public | extra

    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings
        self.timeout = httpx.Timeout(
            settings.read_timeout, connect=settings.connect_timeout
        )

    @abstractmethod
    async def search(self, q: str, opts: QueryOptions) -> list[Track]: ...

    async def resolve_isrc(self, isrc: str, opts: QueryOptions) -> list[Track]:
        return []

    @abstractmethod
    async def resolve_stream(self, source_id: str, quality: str) -> StreamInfo: ...

    async def get_json(
        self, url: str, *, params: dict | None = None, headers: dict | None = None
    ) -> Any:
        try:
            r = await self.client.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except httpx.TimeoutException as e:
            raise SourceError("timeout", f"{type(e).__name__}", retryable=True) from e
        except httpx.TransportError as e:
            raise SourceError("network", f"{type(e).__name__}", retryable=True) from e

        if r.status_code == 429:
            raise SourceError("rate_limited", "upstream rate limit", http_status=429)
        if r.status_code >= 500:
            raise SourceError(
                "http_error",
                f"upstream {r.status_code}",
                http_status=r.status_code,
                retryable=True,
            )
        if r.status_code >= 400:
            raise SourceError(
                "http_error", f"upstream {r.status_code}", http_status=r.status_code
            )
        try:
            return r.json()
        except ValueError as e:
            raise SourceError(
                "parse", "invalid JSON from upstream", http_status=r.status_code
            ) from e
