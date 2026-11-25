"""BitChord 애드온 라우터: /health, /manifest.json, /search, /resolve-isrc, /stream/{id}, /audio/{token}."""

from __future__ import annotations

import os
import time
from typing import Literal

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .errors import SourceError
from .localfile import RangeNotSatisfiable, content_type, iter_file, parse_range
from .models import QueryOptions
from .planner import build_chain
from .schemas import (
    ErrorResponse,
    ManifestOut,
    ResolveIsrcResponse,
    SearchResponse,
    StreamResponse,
)
from .security import (
    decode_play_token,
    decode_track_id,
    encode_play_token,
    encode_track_id,
)

router = APIRouter()
_ERRORS = {
    400: {"model": ErrorResponse},
    502: {"model": SearchResponse, "description": "모든 소스 실패"},
}
_FWD_REQ_HEADERS = ("range", "if-range")
_FWD_RESP_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
)


def _quality(q: str) -> str:
    norm = q.strip().upper()
    if norm in ("LOW", "STANDARD"):
        return "STANDARD"
    if norm in ("HIGH", "HI_RES", "HIRES"):
        return "HI_RES"
    return "LOSSLESS"


def _prefix(request: Request) -> str:
    sec = request.app.state.settings.addon_path_secret
    return f"/{sec}" if sec else ""


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + _prefix(request)


def _sign_tracks(request: Request, tracks) -> list[dict]:
    s = request.app.state.settings
    base = _base_url(request)
    out = []
    for t in tracks:
        signed = encode_track_id(s.signing_secret, t.source, t.source_id)
        d = {
            "id": signed,
            "source": t.source,
            "source_id": t.source_id,
            "title": t.title,
            "artist": t.artist,
            "artists": t.artists,
            "album": t.album,
            "duration_ms": t.duration_ms,
            "isrc": t.isrc,
            "codec": t.codec,
            "container": t.container,
            "sample_rate": t.sample_rate,
            "bit_depth": t.bit_depth,
            "bitrate": t.bitrate,
            "cover_url": t.cover_url,
            "stream_url": f"{base}/stream/{signed}",
            "extra": t.extra,
        }
        out.append(d)
    return out


@router.get("/health", tags=["ops"])
async def health(request: Request):
    st = request.app.state
    return {
        "status": "ok",
        "uptime_s": int(time.time() - st.started_at),
        "sources": sorted(st.registry),
        "circuits": st.orchestrator.circuit_states(),
        "config": st.settings.safe_summary(),
    }


@router.get("/manifest.json", response_model=ManifestOut, tags=["bitchord"])
async def manifest(request: Request):
    s = request.app.state.settings
    return ManifestOut(
        id=s.addon_id,
        name=s.addon_name,
        version="1.0.0",
        description="Hybrid FLAC streaming addon gateway with fallback & range proxy",
        allowDownloads=0,
        capabilities=["search", "stream", "isrc"],
        formats=["flac"],
    )


@router.get(
    "/search", response_model=SearchResponse, responses=_ERRORS, tags=["bitchord"]
)
async def search(
    request: Request,
    response: Response,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int | None = Query(None, ge=1),
    quality: str = Query("LOSSLESS"),
    sources: str | None = Query(None),
    include: str | None = Query(None),
    mode: Literal["fallback", "merge"] = "fallback",
):
    st = request.app.state
    chain = build_chain(st.settings, set(st.registry), sources, include)
    opts = QueryOptions(
        limit=min(limit or st.settings.default_limit, st.settings.max_limit),
        quality=_quality(quality),
    )
    result = await st.orchestrator.run(
        chain, lambda a: a.search(q, opts), mode=mode, limit=opts.limit
    )
    if result.status == "failed":
        response.status_code = 502
    tracks = _sign_tracks(request, result.items)
    d = result.to_dict()
    return SearchResponse(
        status=d["status"],
        query={
            "q": q,
            "limit": opts.limit,
            "quality": opts.quality,
            "sources": sources,
            "include": include,
        },
        tracks=tracks,
        items=tracks,
        attempts=d["attempts"],
        meta={
            "request_id": request.state.request_id,
            "mode": d["mode"],
            "chain": d["chain"],
            "served_by": d["served_by"],
            "returned": len(tracks),
            "elapsed_ms": d["elapsed_ms"],
        },
    )


@router.get("/resolve-isrc", response_model=ResolveIsrcResponse, tags=["bitchord"])
async def resolve_isrc(
    request: Request,
    response: Response,
    isrc: str = Query(..., min_length=10, max_length=20),
    quality: str = Query("LOSSLESS"),
    sources: str | None = None,
    include: str | None = None,
):
    st = request.app.state
    chain = build_chain(st.settings, set(st.registry), sources, include)
    opts = QueryOptions(limit=1, quality=_quality(quality))
    result = await st.orchestrator.run(
        chain, lambda a: a.resolve_isrc(isrc, opts), mode="fallback", limit=1
    )
    tracks = _sign_tracks(request, result.items)
    d = result.to_dict()
    if not tracks:
        response.status_code = 404 if result.status != "failed" else 502
    return ResolveIsrcResponse(
        trackId=tracks[0]["id"] if tracks else None,
        track=tracks[0] if tracks else None,
        attempts=d["attempts"],
        meta={
            "request_id": request.state.request_id,
            "mode": d["mode"],
            "chain": d["chain"],
            "served_by": d["served_by"],
            "returned": len(tracks),
            "elapsed_ms": d["elapsed_ms"],
        },
    )


@router.get("/stream/{track_id}", response_model=StreamResponse, tags=["bitchord"])
async def stream(track_id: str, request: Request, quality: str = Query("LOSSLESS")):
    st = request.app.state
    s = st.settings
    q = _quality(quality)
    source, source_id = decode_track_id(s.signing_secret, track_id)
    try:
        info = await st.orchestrator.resolve_stream(source, source_id, q)
    except SourceError as e:
        return JSONResponse(
            status_code=502,
            content={
                "error": e.kind,
                "detail": e.message,
                "request_id": request.state.request_id,
            },
        )

    if s.proxy_stream or info.headers or info.local_path:
        play_token = encode_play_token(
            s.signing_secret, source, source_id, q, s.play_token_ttl
        )
        play_url = f"{_base_url(request)}/audio/{play_token}"
        exp = int(time.time()) + s.play_token_ttl
    else:
        play_url = info.url
        exp = info.expires_at

    return StreamResponse(
        url=play_url,
        codec=info.codec,
        container=info.container,
        manifest=info.manifest,
        sample_rate=info.sample_rate,
        bit_depth=info.bit_depth,
        bitrate=info.bitrate,
        expires_at=exp,
    )


@router.api_route("/audio/{play_token}", methods=["GET", "HEAD"], tags=["bitchord"])
async def proxy_audio(play_token: str, request: Request):
    """HTTP 206 Range-aware 오디오 프록시. 업스트림 키/URL을 숨기고 탐색(Seek)을 지원한다."""
    st = request.app.state
    s = st.settings
    source, source_id, quality = decode_play_token(s.signing_secret, play_token)
    try:
        info = await st.orchestrator.resolve_stream(source, source_id, quality)
    except SourceError as e:
        return JSONResponse(
            status_code=502,
            content={
                "error": e.kind,
                "detail": e.message,
                "request_id": request.state.request_id,
            },
        )

    if info.local_path:
        return _serve_local(request, info.local_path)

    fwd_headers = dict(info.headers)
    for h in _FWD_REQ_HEADERS:
        if val := request.headers.get(h):
            fwd_headers[h] = val

    client: httpx.AsyncClient = st.http_client
    timeout = httpx.Timeout(s.stream_read_timeout, connect=s.connect_timeout)
    try:
        req = client.build_request(
            request.method, info.url, headers=fwd_headers, timeout=timeout
        )
        upstream = await client.send(req, stream=True)
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "timeout", "detail": "upstream audio timeout"},
        )
    except httpx.TransportError as e:
        return JSONResponse(
            status_code=502, content={"error": "network", "detail": type(e).__name__}
        )

    resp_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() in _FWD_RESP_HEADERS
    }
    resp_headers.setdefault("Accept-Ranges", "bytes")
    resp_headers.setdefault("Content-Type", "audio/flac")

    if request.method == "HEAD":
        await upstream.aclose()
        return Response(status_code=upstream.status_code, headers=resp_headers)

    async def body_iter():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        body_iter(), status_code=upstream.status_code, headers=resp_headers
    )


def _serve_local(request: Request, path: str) -> Response:
    """Serve a file cached on this server, honouring Range like the proxy does."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return JSONResponse(
            status_code=502,
            content={"error": "gone", "detail": "cached audio is no longer available"},
        )
    headers = {"Accept-Ranges": "bytes", "Content-Type": content_type(path)}
    try:
        rng = parse_range(request.headers.get("range"), size)
    except RangeNotSatisfiable:
        return Response(
            status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
        )
    start, end = rng if rng else (0, max(size - 1, 0))
    status = 206 if rng else 200
    headers["Content-Length"] = str(end - start + 1 if size else 0)
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    if request.method == "HEAD" or size == 0:
        return Response(status_code=status, headers=headers)
    return StreamingResponse(
        iter_file(path, start, end), status_code=status, headers=headers
    )
