"""앱 조립: 설정 로드(fail-fast) -> HTTP 클라이언트/어댑터/오케스트레이터 구성 -> 라우터/미들웨어."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters import build_registry
from .config import Settings
from .errors import PlanError
from .orchestrator import Orchestrator
from .router import router

log = logging.getLogger("gateway")
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    client = httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": settings.user_agent},
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=True,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("started: %s", settings.safe_summary())
        yield
        for adapter in app.state.registry.values():
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    log.exception("closing source %s failed", adapter.name)
        await client.aclose()

    app = FastAPI(
        title=settings.addon_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "prod" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.http_client = client
    app.state.registry = build_registry(client, settings)
    app.state.orchestrator = Orchestrator(settings, app.state.registry)
    app.state.started_at = time.time()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins) or ["*"],
        allow_methods=["GET", "HEAD"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        request.state.request_id = rid if _RID_OK.match(rid) else uuid.uuid4().hex[:16]
        t0 = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        log.info(
            "rid=%s %s %s -> %s %dms",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - t0) * 1000,
        )
        return response

    @app.exception_handler(PlanError)
    async def plan_error(request: Request, exc: PlanError):
        return JSONResponse(
            status_code=400,
            content={
                "error": "bad_request",
                "detail": str(exc),
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception(
            "unhandled error rid=%s", getattr(request.state, "request_id", None)
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "unexpected server error",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    prefix = f"/{settings.addon_path_secret}" if settings.addon_path_secret else ""
    app.include_router(router, prefix=prefix)
    if prefix:
        # /health 는 비밀 경로 없이도 로드밸런서가 체크할 수 있도록 루트에도 노출
        @app.get("/health", include_in_schema=False)
        async def root_health(request: Request):
            from .router import health

            return await health(request)

    return app
