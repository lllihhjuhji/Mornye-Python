"""코어 계층 단위 테스트(설정/정규화/오케스트레이터/서킷/플래너/보안 토큰)."""

import asyncio
import os
import time

import pytest

pytest.importorskip("fastapi")

from bitchord_gateway.circuit import CircuitBreaker
from bitchord_gateway.config import ConfigError, Settings
from bitchord_gateway.errors import PlanError, SourceError
from bitchord_gateway.models import Track
from bitchord_gateway.normalize import (
    dedupe,
    from_custom,
    from_public_lossless,
    from_subsonic,
)
from bitchord_gateway.orchestrator import Orchestrator
from bitchord_gateway.planner import build_chain
from bitchord_gateway.security import (
    decode_play_token,
    decode_track_id,
    encode_play_token,
    encode_track_id,
)


def settings(**env):
    keys = [
        "APP_ENV",
        "DEFAULT_CHAIN",
        "AUTO_EXTRA_SOURCES",
        "PUBLIC_LOSSLESS_BASE_URL",
        "SUBSONIC_BASE_URL",
        "SUBSONIC_USER",
        "SUBSONIC_PASSWORD",
        "CUSTOM_BASE_URL",
        "MAX_RETRIES",
        "RETRY_BACKOFF",
        "CB_FAILURE_THRESHOLD",
        "CB_COOLDOWN",
        "TOTAL_DEADLINE",
        "CONNECT_TIMEOUT",
        "READ_TIMEOUT",
        "SIGNING_SECRET",
    ]
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update({"RETRY_BACKOFF": "0", **env})
    return Settings.from_env()


def track(src, n=1, title="Track", artist="Artist", isrc=None):
    return Track(
        id=f"{src}:{n}",
        source=src,
        source_id=str(n),
        title=title,
        artist=artist,
        artists=[artist],
        isrc=isrc,
    )


class Fake:
    def __init__(self, name, *behavior):
        self.name, self.beh, self.calls = name, list(behavior), 0

    async def search(self):
        self.calls += 1
        b = self.beh.pop(0) if len(self.beh) > 1 else self.beh[0]
        if b == "ok":
            return [track(self.name)]
        if b == "empty":
            return []
        if b == "timeout":
            raise SourceError("timeout", "t", retryable=True)
        if b == "e500":
            raise SourceError("http_error", "500", http_status=500, retryable=True)
        if b == "e404":
            raise SourceError("http_error", "404", http_status=404)
        if b == "crash":
            raise KeyError("boom")
        if b == "hang":
            await asyncio.sleep(60)


def run(orch, chain, **kw):
    return asyncio.run(orch.run(chain, lambda a: a.search(), **kw))


def test_primary_ok_no_fallback():
    a, b = Fake("a", "ok"), Fake("b", "ok")
    r = run(Orchestrator(settings(), {"a": a, "b": b}), ["a", "b"])
    assert r.status == "ok" and r.served_by == ["a"] and b.calls == 0


@pytest.mark.parametrize("beh", ["timeout", "e500", "e404", "crash", "empty"])
def test_fallback_on_failure_or_empty(beh):
    a, b = Fake("a", beh), Fake("b", "ok")
    r = run(Orchestrator(settings(), {"a": a, "b": b}), ["a", "b"])
    assert r.served_by == ["b"] and len(r.items) == 1
    assert r.status == ("ok" if beh == "empty" else "degraded")


def test_retry_only_for_retryable():
    a = Fake("a", "timeout", "ok")
    r = run(Orchestrator(settings(MAX_RETRIES="1"), {"a": a}), ["a"])
    assert r.status == "ok" and r.attempts[0].retries == 1 and a.calls == 2
    a = Fake("a", "e404", "ok")
    r = run(Orchestrator(settings(MAX_RETRIES="3"), {"a": a}), ["a"])
    assert a.calls == 1 and r.status == "failed"


def test_hard_timeout_and_total_deadline():
    s = settings(
        TOTAL_DEADLINE="0.5", CONNECT_TIMEOUT="0.3", READ_TIMEOUT="0.3", MAX_RETRIES="0"
    )
    o = Orchestrator(
        s, {"a": Fake("a", "hang"), "b": Fake("b", "hang"), "c": Fake("c", "ok")}
    )
    t0 = time.monotonic()
    r = run(o, ["a", "b", "c"])
    assert (
        r.status == "failed"
        and r.attempts[-1].outcome == "skipped"
        and time.monotonic() - t0 < 2
    )


def test_circuit_breaker_lifecycle():
    t = [0.0]
    cb = CircuitBreaker(2, 10, clock=lambda: t[0])
    cb.failure()
    cb.failure()
    assert cb.state == "open" and not cb.allow()
    t[0] = 11
    assert cb.state == "half_open" and cb.allow()
    cb.success()
    assert cb.state == "closed"


def test_merge_mode_dedupes_by_isrc_and_title():
    o = Orchestrator(
        settings(),
        {
            "a": type(
                "M",
                (),
                {
                    "name": "a",
                    "search": lambda self: asyncio.sleep(
                        0, [track("a", 1, "Dune", "Hans", "US123")]
                    ),
                },
            )(),
            "b": type(
                "M",
                (),
                {
                    "name": "b",
                    "search": lambda self: asyncio.sleep(
                        0,
                        [
                            track("b", 9, "Dune (Remaster)", "Hans", "US123"),
                            track("b", 2, "Only B"),
                        ],
                    ),
                },
            )(),
        },
    )
    r = run(o, ["a", "b"], mode="merge", limit=10)
    assert [i.id for i in r.items] == ["a:1", "b:2"]


def test_planner_hybrid_rules():
    s = settings()
    avail = {"public_lossless", "subsonic"}
    assert build_chain(s, avail, None, None) == ["public_lossless", "subsonic"]
    with pytest.raises(PlanError):
        build_chain(s, avail, None, "custom")
    s = settings(CUSTOM_BASE_URL="https://x.test")
    avail |= {"custom"}
    assert build_chain(s, avail, None, "custom") == [
        "public_lossless",
        "subsonic",
        "custom",
    ]
    assert build_chain(s, avail, "custom,subsonic", None) == ["custom", "subsonic"]


def test_config_validation_and_secret_masking():
    with pytest.raises(ConfigError):
        settings(DEFAULT_CHAIN="public_lossless,bogus")
    with pytest.raises(ConfigError):
        settings(AUTO_EXTRA_SOURCES="custom")
    with pytest.raises(ConfigError):
        settings(APP_ENV="prod")  # SIGNING_SECRET 누락
    s = settings(SUBSONIC_PASSWORD="top-secret-password", CUSTOM_API_KEY="my-api-key")
    dump = str(s.safe_summary())
    assert "top-secret-password" not in dump and "my-api-key" not in dump


def test_hmac_tokens():
    tid = encode_track_id("sec", "subsonic", "tr-42")
    assert decode_track_id("sec", tid) == ("subsonic", "tr-42")
    with pytest.raises(PlanError):
        decode_track_id("sec", tid + "x")
    pt = encode_play_token("sec", "subsonic", "tr-42", "LOSSLESS", 60)
    assert decode_play_token("sec", pt) == ("subsonic", "tr-42", "LOSSLESS")
    expired = encode_play_token("sec", "subsonic", "tr-42", "LOSSLESS", -10)
    with pytest.raises(PlanError):
        decode_play_token("sec", expired)


def test_normalizers():
    p = from_public_lossless(
        {
            "id": "p1",
            "title": "  Time ",
            "artist": "Hans Zimmer",
            "duration": 275,
            "sampleRate": 96000,
            "bitDepth": 24,
            "isrc": "US1",
        }
    )
    assert (
        p and p.duration_ms == 275000 and p.sample_rate == 96000 and p.bit_depth == 24
    )
    sub = from_subsonic(
        {
            "id": "s1",
            "title": "Cornfield Chase",
            "artist": "Hans Zimmer",
            "duration": 126,
            "suffix": "flac",
            "samplingRate": 44100,
            "bitDepth": 16,
        }
    )
    assert sub and sub.codec == "flac" and sub.duration_ms == 126000
    cu = from_custom(
        {"uid": 7, "name": "Stay", "writers": "Hans Zimmer", "length_ms": 400000}
    )
    assert cu and cu.id == "custom:7" and cu.duration_ms == 400000
    assert from_public_lossless({"id": "x"}) is None
    assert len(dedupe([track("a", 1, "Dune", "H"), track("b", 2, "dune", "h")])) == 1
