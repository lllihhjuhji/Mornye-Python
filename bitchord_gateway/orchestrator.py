"""폴백/병합 오케스트레이터. 장애 격리, 재시도, 서킷 브레이커, 전체 데드라인을 담당한다."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol
from collections.abc import Awaitable, Callable, Mapping

from .circuit import CircuitBreaker
from .config import Settings
from .errors import SourceError
from .models import Attempt, Result, StreamInfo, Track
from .normalize import dedupe

log = logging.getLogger("gateway.orchestrator")


class Adapter(Protocol):
    name: str


Op = Callable[[Adapter], Awaitable[list[Track]]]


class Orchestrator:
    def __init__(self, settings: Settings, adapters: Mapping[str, Adapter]):
        self.s = settings
        self.adapters = adapters
        self.breakers = {
            n: CircuitBreaker(settings.cb_failure_threshold, settings.cb_cooldown)
            for n in adapters
        }

    async def _call(
        self, name: str, op: Op, deadline: float
    ) -> tuple[list[Track], Attempt]:
        adapter, breaker = self.adapters[name], self.breakers[name]
        started = time.monotonic()

        def attempt(
            outcome: str,
            items: int = 0,
            retries: int = 0,
            err: SourceError | None = None,
        ) -> Attempt:
            return Attempt(
                source=name,
                outcome=outcome,
                items=items,
                retries=retries,
                latency_ms=int((time.monotonic() - started) * 1000),
                error_kind=err.kind if err else None,
                error_message=err.message[:200] if err else None,
                http_status=err.http_status if err else None,
            )

        if not breaker.allow():
            return [], attempt(
                "skipped", err=SourceError("circuit_open", "circuit breaker open")
            )

        retries = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [], attempt(
                    "skipped",
                    retries=retries,
                    err=SourceError("deadline", "total deadline exceeded"),
                )
            try:
                items = await asyncio.wait_for(
                    op(adapter), timeout=min(self.s.attempt_timeout, remaining)
                )
                breaker.success()
                return items, attempt(
                    "ok" if items else "empty", items=len(items), retries=retries
                )
            except SourceError as e:
                err = e
            except TimeoutError:
                err = SourceError("timeout", "attempt timed out", retryable=True)
            except Exception as e:
                log.exception("adapter %s crashed", name)
                err = SourceError("internal", f"{type(e).__name__}: {e}")

            if err.retryable and retries < self.s.max_retries:
                retries += 1
                await asyncio.sleep(self.s.retry_backoff * (2 ** (retries - 1)))
                continue
            breaker.failure()
            log.warning(
                "source=%s failed kind=%s status=%s retries=%d",
                name,
                err.kind,
                err.http_status,
                retries,
            )
            return [], attempt("error", retries=retries, err=err)

    async def run(
        self, chain: list[str], op: Op, *, mode: str = "fallback", limit: int = 10
    ) -> Result:
        t0 = time.monotonic()
        deadline = t0 + self.s.total_deadline
        attempts: list[Attempt] = []
        items: list[Track] = []
        served_by: list[str] = []

        if mode == "merge":
            outs = await asyncio.gather(*(self._call(n, op, deadline) for n in chain))
            for name, (its, att) in zip(chain, outs, strict=True):
                attempts.append(att)
                if its:
                    served_by.append(name)
                    items.extend(its)
            items = dedupe(items)[:limit]
        else:
            for name in chain:
                its, att = await self._call(name, op, deadline)
                attempts.append(att)
                if its:
                    items, served_by = its[:limit], [name]
                    break

        had_error = any(a.outcome in ("error", "skipped") for a in attempts)
        reached = any(a.outcome in ("ok", "empty") for a in attempts)
        if items:
            status = "degraded" if had_error else "ok"
        else:
            status = "empty" if reached else "failed"

        return Result(
            status=status,
            mode=mode,
            items=items,
            attempts=attempts,
            served_by=served_by,
            chain=chain,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    async def resolve_stream(
        self, source: str, source_id: str, quality: str
    ) -> StreamInfo:
        adapter = self.adapters.get(source)
        if adapter is None:
            raise SourceError("not_configured", f"source '{source}' not configured")
        breaker = self.breakers[source]
        if not breaker.allow():
            raise SourceError("circuit_open", f"circuit open for '{source}'")
        try:
            info = await asyncio.wait_for(
                adapter.resolve_stream(source_id, quality),
                timeout=getattr(adapter, "stream_timeout", None)
                or self.s.attempt_timeout,
            )
            breaker.success()
            return info
        except SourceError:
            breaker.failure()
            raise
        except TimeoutError as e:
            breaker.failure()
            raise SourceError(
                "timeout", "stream resolve timed out", retryable=True
            ) from e
        except Exception as e:
            breaker.failure()
            raise SourceError("internal", f"{type(e).__name__}: {e}") from e

    def circuit_states(self) -> dict[str, str]:
        return {n: b.state for n, b in self.breakers.items()}
