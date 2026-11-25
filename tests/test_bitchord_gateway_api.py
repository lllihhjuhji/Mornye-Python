"""BitChord 애드온 HTTP 계층 통합 테스트 (MockTransport 사용, 외부 네트워크 호출 없음)."""

import os

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from bitchord_gateway.config import Settings
from bitchord_gateway.main import create_app

FLAC_BYTES = b"fLaC" + b"\x00" * 100


def client(handler, **env):
    keys = [
        "ADDON_PATH_SECRET",
        "PUBLIC_LOSSLESS_BASE_URL",
        "SUBSONIC_BASE_URL",
        "SUBSONIC_USER",
        "SUBSONIC_PASSWORD",
        "CUSTOM_BASE_URL",
        "CUSTOM_API_KEY",
        "PROXY_STREAM",
        "AUTO_EXTRA_SOURCES",
    ]
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(
        {
            "RETRY_BACKOFF": "0",
            "MAX_RETRIES": "0",
            "SIGNING_SECRET": "test-secret-key",
            "PUBLIC_LOSSLESS_BASE_URL": "https://lossless.example.test",
            "SUBSONIC_BASE_URL": "https://navidrome.example.test",
            "SUBSONIC_USER": "demo",
            "SUBSONIC_PASSWORD": "pw",
            **env,
        }
    )
    app = create_app(Settings.from_env(), transport=httpx.MockTransport(handler))
    return TestClient(app)


def test_health_and_manifest():
    with client(lambda r: httpx.Response(200, json={})) as c:
        h = c.get("/health").json()
        assert (
            h["status"] == "ok"
            and "public_lossless" in h["sources"]
            and "subsonic" in h["sources"]
        )
        assert "pw" not in str(h)
        m = c.get("/manifest.json").json()
        assert (
            m["allowDownloads"] == 0
            and "flac" in m["formats"]
            and "stream" in m["capabilities"]
        )


def test_search_fallback_stream_and_range_proxy():
    def h(req):
        host = req.url.host
        if host == "lossless.example.test":
            return httpx.Response(503)  # 1순위 장애 -> subsonic 폴백
        if host == "navidrome.example.test":
            if req.url.path.endswith("/search3.view"):
                return httpx.Response(
                    200,
                    json={
                        "subsonic-response": {
                            "status": "ok",
                            "searchResult3": {
                                "song": [
                                    {
                                        "id": "tr-1",
                                        "title": "Dune Theme",
                                        "artist": "Hans Zimmer",
                                        "duration": 180,
                                        "suffix": "flac",
                                        "samplingRate": 96000,
                                        "bitDepth": 24,
                                    }
                                ]
                            },
                        }
                    },
                )
            if req.url.path.endswith("/stream.view"):
                rng = req.headers.get("range")
                if rng == "bytes=0-3":
                    return httpx.Response(
                        206,
                        content=FLAC_BYTES[:4],
                        headers={
                            "Content-Range": f"bytes 0-3/{len(FLAC_BYTES)}",
                            "Content-Type": "audio/flac",
                        },
                    )
                return httpx.Response(
                    200, content=FLAC_BYTES, headers={"Content-Type": "audio/flac"}
                )
        return httpx.Response(404)

    with client(h) as c:
        sr = c.get("/search", params={"q": "dune", "quality": "HI_RES"})
        assert sr.status_code == 200
        sj = sr.json()
        assert sj["status"] == "degraded" and sj["meta"]["served_by"] == ["subsonic"]
        track_id = sj["tracks"][0]["id"]

        st = c.get(f"/stream/{track_id}", params={"quality": "HI_RES"})
        assert st.status_code == 200
        stj = st.json()
        assert stj["codec"] == "flac" and "/audio/" in stj["url"]

        audio_path = "/audio/" + stj["url"].split("/audio/")[1]
        ar = c.get(audio_path, headers={"Range": "bytes=0-3"})
        assert ar.status_code == 206 and ar.content == b"fLaC"
        assert ar.headers["content-range"].startswith("bytes 0-3/")


def test_resolve_isrc_and_path_secret():
    def h(req):
        if "resolve-isrc" in req.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "p99",
                    "title": "Time",
                    "artist": "Hans Zimmer",
                    "isrc": "USQX91000123",
                },
            )
        return httpx.Response(404)

    with client(h, ADDON_PATH_SECRET="my-secret-prefix") as c:
        assert c.get("/manifest.json").status_code == 404
        assert c.get("/health").status_code == 200
        assert c.get("/my-secret-prefix/manifest.json").status_code == 200
        r = c.get("/my-secret-prefix/resolve-isrc", params={"isrc": "USQX91000123"})
        assert r.status_code == 200 and r.json()["track"]["title"] == "Time"


def test_mornye_compatible_hifi_and_qobuz_rest_adapters():
    def h(req):
        if req.url.host == "hifi.example.test":
            if "/search" in req.url.path:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "items": [
                                {
                                    "id": 55,
                                    "title": "Intro",
                                    "artist": {"name": "M83"},
                                    "duration": 120,
                                }
                            ]
                        }
                    },
                )
            if "/track" in req.url.path:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "OriginalTrackUrl": "https://cdn.example.test/55.flac",
                            "bitDepth": 24,
                            "sampleRate": 96000,
                        }
                    },
                )
        if req.url.host == "qobuz.example.test":
            assert req.headers.get("x-api-key") == "q-key"
            if "/search" in req.url.path:
                return httpx.Response(
                    200,
                    json={
                        "tracks": [
                            {
                                "id": "q1",
                                "title": "Outro",
                                "artist": "M83",
                                "duration": 200,
                            }
                        ]
                    },
                )
            if "/download-url/q1" in req.url.path:
                return httpx.Response(
                    200, json={"url": "https://cdn.example.test/q1.flac"}
                )
        return httpx.Response(404)

    with client(
        h,
        HIFI_API_BASE_URL="https://hifi.example.test",
        QOBUZ_REST_BASE_URL="https://qobuz.example.test",
        QOBUZ_REST_API_KEY="q-key",
    ) as c:
        s1 = c.get("/search", params={"q": "M83", "sources": "hifi_api"}).json()
        assert s1["meta"]["served_by"] == ["hifi_api"]
        st1 = c.get(
            f"/stream/{s1['tracks'][0]['id']}", params={"quality": "HI_RES"}
        ).json()
        assert st1["bit_depth"] == 24 and st1["sample_rate"] == 96000

        s2 = c.get("/search", params={"q": "M83", "sources": "qobuz_rest"}).json()
        assert s2["meta"]["served_by"] == ["qobuz_rest"]
        st2 = c.get(f"/stream/{s2['tracks'][0]['id']}").json()
        assert st2["codec"] == "flac" and "/audio/" in st2["url"]
