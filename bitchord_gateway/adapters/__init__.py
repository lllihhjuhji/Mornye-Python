"""어댑터 레지스트리: 환경변수가 설정된 FLAC 소스만 등록한다."""

from __future__ import annotations

import httpx

from ..config import Settings
from .base import SourceAdapter
from .custom import CustomFlacAdapter
from .hifi_api import HifiApiAdapter
from .jellyfin import JellyfinAdapter
from .mornye_backend import MornyeAdapter
from .public_lossless import PublicLosslessAdapter
from .qobuz_rest import QobuzRestAdapter
from .subsonic import SubsonicAdapter


def build_registry(
    client: httpx.AsyncClient, settings: Settings
) -> dict[str, SourceAdapter]:
    reg: dict[str, SourceAdapter] = {}
    if settings.public_lossless_base:
        reg["public_lossless"] = PublicLosslessAdapter(client, settings)
    if settings.subsonic_base and settings.subsonic_user and settings.subsonic_password:
        reg["subsonic"] = SubsonicAdapter(client, settings)
    if (
        settings.jellyfin_base
        and settings.jellyfin_api_key
        and settings.jellyfin_user_id
    ):
        reg["jellyfin"] = JellyfinAdapter(client, settings)
    if settings.hifi_api_base:
        reg["hifi_api"] = HifiApiAdapter(client, settings)
    if settings.qobuz_rest_base:
        reg["qobuz_rest"] = QobuzRestAdapter(client, settings)
    if settings.mornye_enabled:
        reg["mornye"] = MornyeAdapter(client, settings)
    if settings.custom_base:
        reg["custom"] = CustomFlacAdapter(client, settings)
    return reg
