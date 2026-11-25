"""응답 정규화 계층: 다양한 FLAC/음악 소스의 필드를 Track 단일 스키마로 변환한다."""

from __future__ import annotations

import re
from typing import Any

from .models import Track


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else ""


def as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        parts = re.split(r"[;,/&]|\bfeat\.?\b", v, flags=re.IGNORECASE)
    elif isinstance(v, (list, tuple)):
        parts = [x.get("name", "") if isinstance(x, dict) else x for x in v]
    else:
        return []
    return [clean(p) for p in parts if clean(p)]


def pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, "", [], {}):
            return d[k]
    return None


def to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def to_duration_ms(raw: dict) -> int | None:
    ms = to_int(pick(raw, "duration_ms", "durationMs", "length_ms"))
    if ms is not None and ms > 0:
        return ms
    sec = to_int(pick(raw, "duration", "duration_sec", "length"))
    return sec * 1000 if sec is not None and sec > 0 else None


def _make(source: str, sid: Any, title: Any, artist_val: Any, **kw) -> Track | None:
    sid_str = clean(str(sid)) if sid is not None else ""
    title_str = clean(title)
    artists = as_list(artist_val)
    artist_str = ", ".join(artists) if artists else clean(str(artist_val or ""))
    if not sid_str or not title_str:
        return None
    return Track(
        id=f"{source}:{sid_str}",
        source=source,
        source_id=sid_str,
        title=title_str,
        artist=artist_str or "Unknown Artist",
        artists=artists or ([artist_str] if artist_str else []),
        **kw,
    )


def from_public_lossless(raw: dict) -> Track | None:
    """일반 공개/커뮤니티 무손실 API 응답 정규화."""
    sid = pick(raw, "id", "trackId", "track_id", "uid")
    title = pick(raw, "title", "name", "track")
    artist = pick(raw, "artists", "artist", "artistName")
    if isinstance(artist, dict):
        artist = artist.get("name", "")
    album = raw.get("album")
    album_title = (
        album.get("title") or album.get("name")
        if isinstance(album, dict)
        else clean(album)
    )
    return _make(
        "public_lossless",
        sid,
        title,
        artist,
        album=clean(album_title) or None,
        duration_ms=to_duration_ms(raw),
        isrc=clean(pick(raw, "isrc", "ISRC")) or None,
        codec=clean(pick(raw, "codec", "format") or "flac").lower(),
        container=clean(pick(raw, "container", "format") or "flac").lower(),
        sample_rate=to_int(pick(raw, "sample_rate", "sampleRate")),
        bit_depth=to_int(pick(raw, "bit_depth", "bitDepth")),
        bitrate=to_int(pick(raw, "bitrate", "bitRate")),
        cover_url=pick(raw, "cover_url", "coverUrl", "artwork", "cover"),
    )


def from_subsonic(song: dict, cover_url: str | None = None) -> Track | None:
    """Subsonic / Navidrome song 객체 정규화."""
    return _make(
        "subsonic",
        song.get("id"),
        song.get("title"),
        song.get("artist"),
        album=clean(song.get("album")) or None,
        duration_ms=to_duration_ms(song),
        isrc=clean(song.get("isrc")) or None,
        codec=clean(song.get("suffix") or "flac").lower(),
        container=clean(song.get("suffix") or "flac").lower(),
        sample_rate=to_int(song.get("samplingRate")),
        bit_depth=to_int(song.get("bitDepth")),
        bitrate=to_int(song.get("bitRate")),
        cover_url=cover_url,
    )


def from_custom(raw: dict) -> Track | None:
    """필드명이 제각각인 자체/유료 FLAC API 정규화."""
    return _make(
        "custom",
        pick(raw, "id", "uid", "track_id", "key"),
        pick(raw, "title", "name", "song"),
        pick(raw, "artists", "artist", "writers"),
        album=clean(pick(raw, "album", "record")) or None,
        duration_ms=to_duration_ms(raw),
        isrc=clean(pick(raw, "isrc")) or None,
        codec=clean(pick(raw, "codec", "format") or "flac").lower(),
        container=clean(pick(raw, "container", "format") or "flac").lower(),
        sample_rate=to_int(pick(raw, "sample_rate", "sampleRate")),
        bit_depth=to_int(pick(raw, "bit_depth", "bitDepth")),
        bitrate=to_int(pick(raw, "bitrate", "bitRate")),
        cover_url=pick(raw, "cover", "cover_url", "image", "thumbnail"),
        extra={k: v for k, v in raw.items() if k in ("label", "year", "bpm")},
    )


def _dedupe_key(t: Track) -> str:
    if t.isrc:
        return "isrc:" + t.isrc.upper().replace("-", "")
    norm_title = re.sub(r"\W+", "", t.title.lower())
    norm_artist = re.sub(r"\W+", "", (t.artists[0] if t.artists else t.artist).lower())
    return f"ta:{norm_title}|{norm_artist}"


def dedupe(tracks: list[Track]) -> list[Track]:
    """merge 모드용. 앞선(우선순위 높은) 소스의 트랙을 남긴다."""
    seen: set[str] = set()
    out: list[Track] = []
    for t in tracks:
        k = _dedupe_key(t)
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out
