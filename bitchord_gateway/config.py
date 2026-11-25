"""설정/환경변수 계층: 모든 값은 여기서만 읽고, 기동 시점에 검증한다(fail-fast)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

PUBLIC_SOURCES = (
    "public_lossless",
    "subsonic",
    "jellyfin",
    "hifi_api",
    "qobuz_rest",
    "mornye",
)
EXTRA_SOURCES = ("custom",)
ALL_SOURCES = PUBLIC_SOURCES + EXTRA_SOURCES


class ConfigError(RuntimeError):
    pass


def _raw(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v.strip()


def _bool(name: str, default: bool) -> bool:
    v = _raw(name, "true" if default else "false").lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be a boolean")


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(_raw(name, str(default)))
    except ValueError as e:
        raise ConfigError(f"{name} must be a number") from e
    if not lo <= v <= hi:
        raise ConfigError(f"{name} must be within [{lo}, {hi}], got {v}")
    return v


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(_raw(name, str(default)))
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer") from e
    if not lo <= v <= hi:
        raise ConfigError(f"{name} must be within [{lo}, {hi}], got {v}")
    return v


def _list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in _raw(name, default).split(",") if x.strip())


def _url(name: str, default: str = "") -> str:
    v = _raw(name, default).rstrip("/")
    if v and not v.startswith(("http://", "https://")):
        raise ConfigError(f"{name} must start with http:// or https://")
    return v


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    user_agent: str
    cors_origins: tuple[str, ...]

    addon_id: str
    addon_name: str
    addon_path_secret: str
    signing_secret: str
    proxy_stream: bool
    play_token_ttl: int

    default_chain: tuple[str, ...]
    auto_extra_sources: tuple[str, ...]

    connect_timeout: float
    read_timeout: float
    stream_read_timeout: float
    total_deadline: float
    max_retries: int
    retry_backoff: float

    cb_failure_threshold: int
    cb_cooldown: float

    default_limit: int
    max_limit: int

    public_lossless_base: str
    subsonic_base: str
    subsonic_user: str
    subsonic_password: str
    jellyfin_base: str
    jellyfin_api_key: str
    jellyfin_user_id: str
    hifi_api_base: str
    hifi_api_key: str
    qobuz_rest_base: str
    qobuz_rest_api_key: str

    custom_base: str
    custom_key: str
    custom_key_header: str

    # Mornye-Python backend (search via its metadata client, audio via the
    # extensions the operator installed in Mornye).
    mornye_enabled: bool = False
    mornye_services: tuple[str, ...] = ()
    mornye_cache_dir: str = ""
    mornye_cache_max_mb: int = 4096
    mornye_stream_timeout: float = 180.0

    @property
    def attempt_timeout(self) -> float:
        return self.connect_timeout + self.read_timeout + 0.5

    @classmethod
    def from_env(cls) -> Settings:
        app_env = _raw("APP_ENV", "dev").lower()
        chain = _list("DEFAULT_CHAIN", "public_lossless,subsonic")
        extras = _list("AUTO_EXTRA_SOURCES", "")
        for n in chain + extras:
            if n not in ALL_SOURCES:
                raise ConfigError(
                    f"unknown source '{n}' (allowed: {', '.join(ALL_SOURCES)})"
                )
        if not chain:
            raise ConfigError("DEFAULT_CHAIN must not be empty")

        signing_secret = _raw("SIGNING_SECRET")
        if not signing_secret:
            if app_env == "prod":
                raise ConfigError("SIGNING_SECRET is required in prod")
            signing_secret = secrets.token_hex(32)

        s = cls(
            app_env=app_env,
            log_level=_raw("LOG_LEVEL", "INFO").upper(),
            user_agent=_raw("USER_AGENT", "bitchord-flac-gateway/1.0"),
            cors_origins=tuple(
                x.strip() for x in _raw("CORS_ORIGINS", "*").split(",") if x.strip()
            ),
            addon_id=_raw("ADDON_ID", "com.bitchord.flac.gateway"),
            addon_name=_raw("ADDON_NAME", "BitChord Hybrid FLAC Gateway"),
            addon_path_secret=_raw("ADDON_PATH_SECRET"),
            signing_secret=signing_secret,
            proxy_stream=_bool("PROXY_STREAM", True),
            play_token_ttl=_int("PLAY_TOKEN_TTL", 21600, 60, 86400),
            default_chain=chain,
            auto_extra_sources=extras,
            connect_timeout=_float("CONNECT_TIMEOUT", 2.0, 0.1, 30),
            read_timeout=_float("READ_TIMEOUT", 5.0, 0.1, 60),
            stream_read_timeout=_float("STREAM_READ_TIMEOUT", 30.0, 1.0, 300),
            total_deadline=_float("TOTAL_DEADLINE", 10.0, 0.5, 120),
            max_retries=_int("MAX_RETRIES", 1, 0, 5),
            retry_backoff=_float("RETRY_BACKOFF", 0.3, 0.0, 10),
            cb_failure_threshold=_int("CB_FAILURE_THRESHOLD", 3, 1, 100),
            cb_cooldown=_float("CB_COOLDOWN", 30, 1, 3600),
            default_limit=_int("DEFAULT_LIMIT", 10, 1, 100),
            max_limit=_int("MAX_LIMIT", 40, 1, 200),
            public_lossless_base=_url("PUBLIC_LOSSLESS_BASE_URL"),
            subsonic_base=_url("SUBSONIC_BASE_URL"),
            subsonic_user=_raw("SUBSONIC_USER"),
            subsonic_password=_raw("SUBSONIC_PASSWORD"),
            jellyfin_base=_url("JELLYFIN_BASE_URL"),
            jellyfin_api_key=_raw("JELLYFIN_API_KEY"),
            jellyfin_user_id=_raw("JELLYFIN_USER_ID"),
            hifi_api_base=_url("HIFI_API_BASE_URL"),
            hifi_api_key=_raw("HIFI_API_KEY"),
            qobuz_rest_base=_url("QOBUZ_REST_BASE_URL"),
            qobuz_rest_api_key=_raw("QOBUZ_REST_API_KEY"),
            custom_base=_url("CUSTOM_BASE_URL"),
            custom_key=_raw("CUSTOM_API_KEY"),
            custom_key_header=_raw("CUSTOM_KEY_HEADER", "X-API-Key"),
            mornye_enabled=_bool("MORNYE_BACKEND_ENABLED", False),
            mornye_services=tuple(
                x.strip()
                for x in _raw("MORNYE_BACKEND_SERVICES").split(",")
                if x.strip()
            ),
            mornye_cache_dir=_raw("MORNYE_BACKEND_CACHE_DIR")
            or os.path.join(os.path.expanduser("~"), ".cache", "bitchord_gateway"),
            mornye_cache_max_mb=_int("MORNYE_BACKEND_CACHE_MAX_MB", 4096, 64, 10**7),
            mornye_stream_timeout=_float("MORNYE_BACKEND_STREAM_TIMEOUT", 180, 5, 1800),
        )
        if "custom" in extras and not s.custom_base:
            raise ConfigError(
                "CUSTOM_BASE_URL is required when 'custom' is in AUTO_EXTRA_SOURCES"
            )
        if s.default_limit > s.max_limit:
            raise ConfigError("DEFAULT_LIMIT must be <= MAX_LIMIT")
        return s

    def safe_summary(self) -> dict:
        """로그/헬스체크용. 비밀번호·API 키·서명 키는 절대 포함하지 않는다."""
        return {
            "env": self.app_env,
            "addon_id": self.addon_id,
            "path_secret_enabled": bool(self.addon_path_secret),
            "proxy_stream": self.proxy_stream,
            "default_chain": list(self.default_chain),
            "auto_extra_sources": list(self.auto_extra_sources),
            "timeouts": {
                "connect": self.connect_timeout,
                "read": self.read_timeout,
                "stream_read": self.stream_read_timeout,
                "total": self.total_deadline,
            },
            "max_retries": self.max_retries,
            "public_lossless_configured": bool(self.public_lossless_base),
            "subsonic_configured": bool(
                self.subsonic_base and self.subsonic_user and self.subsonic_password
            ),
            "jellyfin_configured": bool(
                self.jellyfin_base and self.jellyfin_api_key and self.jellyfin_user_id
            ),
            "hifi_api_configured": bool(self.hifi_api_base),
            "qobuz_rest_configured": bool(self.qobuz_rest_base),
            "custom_configured": bool(self.custom_base),
            "mornye_enabled": self.mornye_enabled,
        }
