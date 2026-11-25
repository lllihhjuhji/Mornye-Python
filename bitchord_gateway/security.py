"""HMAC-SHA256 기반 불투명(opaque) 트랙 ID 및 재생 토큰 서명/검증."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from .errors import PlanError


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def sign_payload(secret: str, payload: dict[str, Any]) -> str:
    body = _b64e(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    sig = _b64e(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_payload(
    secret: str, token: str, *, check_exp: bool = True
) -> dict[str, Any]:
    if "." not in token:
        raise PlanError("invalid token format")
    body, sig = token.rsplit(".", 1)
    expected = _b64e(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise PlanError("invalid token signature")
    try:
        data = json.loads(_b64d(body).decode("utf-8"))
    except Exception as e:
        raise PlanError("corrupted token payload") from e
    if check_exp and "exp" in data and time.time() > float(data["exp"]):
        raise PlanError("token expired")
    return data


def encode_track_id(secret: str, source: str, source_id: str) -> str:
    return sign_payload(secret, {"s": source, "id": source_id})


def decode_track_id(secret: str, token: str) -> tuple[str, str]:
    data = verify_payload(secret, token, check_exp=False)
    src, sid = data.get("s"), data.get("id")
    if not src or not sid:
        raise PlanError("invalid track id")
    return str(src), str(sid)


def encode_play_token(
    secret: str, source: str, source_id: str, quality: str, ttl: int
) -> str:
    return sign_payload(
        secret,
        {
            "s": source,
            "id": source_id,
            "q": quality,
            "exp": int(time.time()) + ttl,
        },
    )


def decode_play_token(secret: str, token: str) -> tuple[str, str, str]:
    data = verify_payload(secret, token, check_exp=True)
    src, sid, q = data.get("s"), data.get("id"), data.get("q", "LOSSLESS")
    if not src or not sid:
        raise PlanError("invalid play token")
    return str(src), str(sid), str(q)
