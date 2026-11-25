"""내부 도메인 모델(순수 dataclass)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Track:
    """모든 오디오 소스의 트랙이 이 형태로 정규화된다."""

    id: str  # 서명 전 "<source>:<source_id>" 또는 서명된 불투명 ID
    source: str
    source_id: str
    title: str
    artist: str
    artists: list[str] = field(default_factory=list)
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
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamInfo:
    """어댑터가 해석한 업스트림 스트림 정보. headers는 게이트웨이 내부 프록시 전용."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    # Set when the audio is a file on this server (Mornye backend): the
    # /audio proxy serves it with Range support instead of fetching `url`.
    local_path: str | None = None
    codec: str = "flac"
    container: str = "flac"
    manifest: str = "none"
    sample_rate: int | None = None
    bit_depth: int | None = None
    bitrate: int | None = None
    expires_at: int | None = None


@dataclass
class Attempt:
    source: str
    outcome: str  # ok | empty | error | skipped
    items: int = 0
    latency_ms: int = 0
    retries: int = 0
    error_kind: str | None = None
    error_message: str | None = None
    http_status: int | None = None


@dataclass
class Result:
    status: str  # ok | degraded | empty | failed
    mode: str  # fallback | merge
    items: list[Track]
    attempts: list[Attempt]
    served_by: list[str]
    chain: list[str]
    elapsed_ms: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QueryOptions:
    limit: int = 10
    quality: str = "LOSSLESS"  # STANDARD | LOSSLESS | HI_RES
