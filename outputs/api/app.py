"""FastAPI application factory and entrypoint.

This is the public read API for the ga-watchdog warehouse. Every
decision in this module traces back to ADR-0005.

Run locally:

    uvicorn outputs.api.app:app --reload

Deployed via Vercel's Python serverless runtime — see `vercel.json`
and `outputs/api/index.py` for the serverless handler.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ._logging import hash_ip, log_request
from ._rate_limit import check as rate_limit_check
from .routes import analytics, health, seb, voter


def create_app() -> FastAPI:
    """Build the FastAPI app. Factory pattern so tests can rebuild."""
    app = FastAPI(
        title="ga-watchdog public read API",
        version="0.1.0",
        description=(
            "Read-only access to the ga-watchdog warehouse. Every "
            "endpoint reads from a curated allow-list of views; the "
            "underlying voter table and audit logs are not exposed. "
            "See ADR-0005 for the full surface contract."
        ),
        # Routes live under /v1/. The OpenAPI doc is at /docs.
    )

    app.include_router(health.router)
    app.include_router(seb.router)
    app.include_router(voter.router)
    app.include_router(analytics.router)

    @app.middleware("http")
    async def request_pipeline(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Rate-limit, cache-tag, and log every request."""
        start = time.perf_counter()
        ip = request.client.host if request.client else "0.0.0.0"
        ip_h = hash_ip(ip)

        allowed, retry_after = rate_limit_check(ip_h)
        if not allowed:
            response: Response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded."},
                headers={"Retry-After": str(retry_after)},
            )
        else:
            response = await call_next(request)
            # ADR-0005 §6: HTTP-native caching for GETs.
            if request.method == "GET" and response.status_code == 200:
                response.headers.setdefault("Cache-Control", "public, max-age=3600")

        latency_ms = (time.perf_counter() - start) * 1000
        body_len = int(response.headers.get("content-length", 0) or 0)
        log_request(
            route=request.url.path,
            method=request.method,
            status=response.status_code,
            latency_ms=latency_ms,
            ip_hash=ip_h,
            response_bytes=body_len,
        )
        return response

    return app


app = create_app()
