"""BitChord 애드온 API 응답 스키마(pydantic)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ManifestOut(BaseModel):
    id: str
    name: str
    version: str
    description: str
    allowDownloads: int = 0
    capabilities: list[str]
    formats: list[str]


class TrackOut(BaseModel):
    id: str
    source: str
    source_id: str
    title: str
    artist: str
    artists: list[str] = []
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    codec: str = "flac"
    container: str = "flac"
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    cover_url: str | None = None
    stream_url: str | None = None
    extra: dict[str, Any] = {}


class AttemptOut(BaseModel):
    source: str
    outcome: Literal["ok", "empty", "error", "skipped"]
    items: int = 0
    latency_ms: int = 0
    retries: int = 0
    error_kind: str | None = None
    error_message: str | None = None
    http_status: int | None = None


class MetaOut(BaseModel):
    request_id: str
    mode: Literal["fallback", "merge"]
    chain: list[str]
    served_by: list[str]
    returned: int
    elapsed_ms: int


class SearchResponse(BaseModel):
    status: Literal["ok", "degraded", "empty", "failed"]
    query: dict[str, Any]
    tracks: list[TrackOut]
    items: list[TrackOut]
    meta: MetaOut
    attempts: list[AttemptOut] = Field(description="소스별 호출 결과(폴백 이력)")


class ResolveIsrcResponse(BaseModel):
    trackId: str | None
    track: TrackOut | None = None
    meta: MetaOut
    attempts: list[AttemptOut]


class StreamResponse(BaseModel):
    url: str
    codec: str = "flac"
    container: str = "flac"
    manifest: str = "none"
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    expires_at: int | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str
    request_id: str | None = None
