"""하이브리드 실행 계획: 기본 체인 + (환경변수 자동 첨부) + (요청 옵션 include/sources)."""

from __future__ import annotations

from .config import ALL_SOURCES, Settings
from .errors import PlanError


def _split(s: str | None) -> list[str]:
    return [x.strip().lower() for x in (s or "").split(",") if x.strip()]


def build_chain(
    settings: Settings, available: set[str], sources: str | None, include: str | None
) -> list[str]:
    explicit = _split(sources)
    if explicit:
        wanted, strict = explicit, True
    else:
        wanted, strict = (
            list(settings.default_chain) + list(settings.auto_extra_sources),
            False,
        )
    inc = _split(include)

    for name in explicit + inc:
        if name not in ALL_SOURCES:
            raise PlanError(
                f"unknown source '{name}' (allowed: {', '.join(ALL_SOURCES)})"
            )
        if name not in available:
            raise PlanError(f"source '{name}' is not configured on this server")

    chain: list[str] = []
    for name in wanted + inc:
        if name in chain:
            continue
        if name in available:
            chain.append(name)
        elif strict:
            raise PlanError(f"source '{name}' is not configured on this server")
    if not chain:
        raise PlanError("no usable source in chain")
    return chain
