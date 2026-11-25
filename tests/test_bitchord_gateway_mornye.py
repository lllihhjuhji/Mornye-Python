"""The Mornye backend: search mapping, ISRC matching, download cache, Range."""

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest

from bitchord_gateway.adapters.mornye_backend import MornyeAdapter
from bitchord_gateway.config import ConfigError, Settings
from bitchord_gateway.errors import SourceError
from bitchord_gateway.localfile import (
    RangeNotSatisfiable,
    content_type,
    iter_file,
    parse_range,
)
from bitchord_gateway.models import QueryOptions

AUDIO = b"fLaC" + bytes(range(256)) * 8  # 1028 bytes


def meta(id="4uLU6hMCjMI75M1A2tKUQC", title="Never Gonna Give You Up", **kw):
    base = dict(
        id=id,
        title=title,
        artists="Rick Astley",
        artist_names=[],
        album="Whenever You Need Somebody",
        duration_ms=213000,
        isrc="gbarl8700001",
        cover_url="https://img.example/c.jpg",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FakeBackend:
    def __init__(self, tmp_path, rows=None, fail=None):
        self.rows, self.fail, self.tmp = rows or [], fail, tmp_path
        self.searches, self.downloads = [], []

    async def search(self, query, limit):
        self.searches.append((query, limit))
        return self.rows

    async def download(self, track_id):
        self.downloads.append(track_id)
        await asyncio.sleep(0.05)
        if self.fail:
            raise SourceError("download_failed", self.fail)
        p = self.tmp / "LOSSLESS" / f"{track_id}.flac"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(AUDIO)
        return str(p)

    async def aclose(self):
        pass


def make(tmp_path, backend, **env):
    os.environ.update(
        {
            "SIGNING_SECRET": "s",
            "MORNYE_BACKEND_ENABLED": "true",
            "MORNYE_BACKEND_CACHE_DIR": str(tmp_path),
            "DEFAULT_CHAIN": "mornye",
            **env,
        }
    )
    st = Settings.from_env()
    return MornyeAdapter(
        httpx.AsyncClient(),
        st,
        backends={"LOSSLESS": backend, "HI_RES_LOSSLESS": backend},
    )


OPTS = QueryOptions(limit=5)


def run(coro):
    return asyncio.run(coro)


def test_search_maps_metadata_to_bitchord_track(tmp_path):
    ad = make(tmp_path, FakeBackend(tmp_path, [meta(), meta(id="x", title="")]))
    tracks = run(ad.search("rick", OPTS))
    assert len(tracks) == 1  # the untitled row is dropped
    t = tracks[0]
    assert (t.source, t.source_id, t.id) == (
        "mornye",
        "4uLU6hMCjMI75M1A2tKUQC",
        "mornye:4uLU6hMCjMI75M1A2tKUQC",
    )
    assert t.artists == ["Rick Astley"] and t.isrc == "GBARL8700001"
    assert t.codec == t.container == "flac" and t.duration_ms == 213000


def test_isrc_needs_an_exact_match(tmp_path):
    be = FakeBackend(tmp_path, [meta(isrc="OTHER0000001"), meta(id="b2")])
    ad = make(tmp_path, be)
    assert run(ad.resolve_isrc("gbarl8700001", OPTS))[0].source_id == "b2"
    assert be.searches[-1][0] == "isrc:GBARL8700001"
    assert (
        run(
            make(tmp_path, FakeBackend(tmp_path, [meta(isrc="X")])).resolve_isrc(
                "GBARL8700001", OPTS
            )
        )
        == []
    )


def test_stream_downloads_once_then_serves_from_cache(tmp_path):
    be = FakeBackend(tmp_path)
    ad = make(tmp_path, be)

    async def go():
        # two players ask at once: one download
        a, b = await asyncio.gather(
            ad.resolve_stream("abc123", "LOSSLESS"),
            ad.resolve_stream("abc123", "LOSSLESS"),
        )
        c = await ad.resolve_stream("abc123", "LOSSLESS")
        return a, b, c

    a, b, c = run(go())
    assert be.downloads == ["abc123"]
    assert a.local_path == b.local_path == c.local_path
    assert a.container == "flac" and a.url == ""


def test_download_failure_is_a_source_error(tmp_path):
    ad = make(tmp_path, FakeBackend(tmp_path, fail="no provider matched"))
    with pytest.raises(SourceError) as e:
        run(ad.resolve_stream("abc123", "LOSSLESS"))
    assert e.value.kind == "download_failed"


def test_rejects_path_like_ids(tmp_path):
    ad = make(tmp_path, FakeBackend(tmp_path))
    for bad in ("../etc/passwd", "a/b", "", "x" * 65):
        with pytest.raises(SourceError):
            run(ad.resolve_stream(bad, "LOSSLESS"))


def test_eviction_keeps_the_new_file_and_drops_old_ones(tmp_path):
    ad = make(tmp_path, FakeBackend(tmp_path), MORNYE_BACKEND_CACHE_MAX_MB="64")
    st = Settings.from_env()
    object.__setattr__(st, "mornye_cache_max_mb", 0)
    ad.settings = st
    old = tmp_path / "LOSSLESS" / "old.flac"
    new = tmp_path / "LOSSLESS" / "new.flac"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(AUDIO)
    new.write_bytes(AUDIO)
    past = os.path.getmtime(old) - 3600
    os.utime(old, (past, past))
    ad._evict(str(new))
    assert not old.exists() and new.exists()


def test_missing_mornye_package_fails_fast(tmp_path, monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    os.environ.update(
        {"SIGNING_SECRET": "s", "MORNYE_BACKEND_CACHE_DIR": str(tmp_path)}
    )
    with pytest.raises(ConfigError):
        MornyeAdapter(httpx.AsyncClient(), Settings.from_env())


def test_parse_range():
    assert parse_range(None, 100) is None
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=90-", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=50-999", 100) == (50, 99)
    assert parse_range("bytes=0-1,5-6", 100) is None  # multi-range: ignored
    assert parse_range("items=0-1", 100) is None
    for bad in ("bytes=100-", "bytes=9-2", "bytes=-0"):
        with pytest.raises(RangeNotSatisfiable):
            parse_range(bad, 100)


def test_iter_file_and_content_type(tmp_path):
    p = tmp_path / "a.flac"
    p.write_bytes(AUDIO)

    async def collect(s, e):
        return b"".join([c async for c in iter_file(str(p), s, e)])

    assert run(collect(4, 9)) == AUDIO[4:10]
    assert run(collect(0, len(AUDIO) - 1)) == AUDIO
    assert (
        content_type("x.flac") == "audio/flac" and content_type("x.m4a") == "audio/mp4"
    )


def test_gateway_serves_mornye_tracks_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from bitchord_gateway.main import create_app

    be = FakeBackend(tmp_path, [meta()])
    monkeypatch.setattr(
        "bitchord_gateway.adapters.MornyeAdapter",
        lambda client, settings: MornyeAdapter(
            client, settings, backends={"LOSSLESS": be, "HI_RES_LOSSLESS": be}
        ),
    )
    for k in ("PUBLIC_LOSSLESS_BASE_URL", "SUBSONIC_BASE_URL", "ADDON_PATH_SECRET"):
        os.environ.pop(k, None)
    os.environ.update(
        {
            "SIGNING_SECRET": "s",
            "MORNYE_BACKEND_ENABLED": "true",
            "MORNYE_BACKEND_CACHE_DIR": str(tmp_path),
            "DEFAULT_CHAIN": "mornye",
            "PROXY_STREAM": "false",
        }
    )
    app = create_app(
        Settings.from_env(),
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    with TestClient(app) as c:
        assert "mornye" in c.get("/health").json()["sources"]
        tr = c.get("/search", params={"q": "rick"}).json()["tracks"][0]
        assert tr["source"] == "mornye" and tr["codec"] == "flac"
        st = c.get(f"/stream/{tr['id']}").json()
        assert (
            "/audio/" in st["url"] and st["container"] == "flac"
        )  # proxied even with PROXY_STREAM=false
        path = st["url"].split("://", 1)[1].split("/", 1)[1]
        full = c.get("/" + path)
        assert full.status_code == 200 and full.content == AUDIO
        assert full.headers["accept-ranges"] == "bytes"
        part = c.get("/" + path, headers={"Range": "bytes=4-9"})
        assert part.status_code == 206 and part.content == AUDIO[4:10]
        assert part.headers["content-range"] == f"bytes 4-9/{len(AUDIO)}"
        assert c.get("/" + path, headers={"Range": "bytes=99999-"}).status_code == 416
        assert c.head("/" + path).headers["content-length"] == str(len(AUDIO))
    assert be.downloads == [tr["source_id"]]
