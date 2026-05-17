"""Structured request logging with hashed IPs.

ADR-0005 decision 10: every request logs timestamp, route, status,
latency, IP-hash, and response byte count. The IP itself is never
logged. The hash uses a salt that rotates daily so the same researcher
cannot be re-identified across days from logs alone.

This is observability-grade auditing, not surveillance-grade. The
distinction is the rotation: a salt that rotates per-day means we can
answer "did one source make 50,000 requests in an hour" without ever
being able to answer "did this person come back tomorrow."
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import structlog

log = structlog.get_logger("ga_watchdog.api")


def _daily_salt() -> str:
    """Return today's salt. Rotates at UTC midnight.

    The base salt comes from the env (`GA_WATCHDOG_IP_SALT`), so even
    if the daily component were known, the hashes cannot be reversed
    without the env secret. If the env is unset (local dev) we fall
    back to a fixed dev salt — that's fine because local dev logs are
    not user data.
    """
    base = os.environ.get("GA_WATCHDOG_IP_SALT", "dev-salt-not-for-prod")
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"{base}:{day}"


def hash_ip(ip: str) -> str:
    """Return a per-day stable hash of `ip`. Same IP → same hash today,
    different hash tomorrow.
    """
    h = hashlib.sha256()
    h.update(_daily_salt().encode("utf-8"))
    h.update(b"|")
    h.update(ip.encode("utf-8"))
    return h.hexdigest()[:16]  # 64 bits is enough for daily uniqueness.


def log_request(
    *,
    route: str,
    method: str,
    status: int,
    latency_ms: float,
    ip_hash: str,
    response_bytes: int,
) -> None:
    """Emit a single structured log line for one request.

    Deliberately does not accept query params, request bodies, or
    response bodies. If we ever add an endpoint that takes a voter
    identifier as a parameter, this signature should not silently make
    that identifier loggable.
    """
    log.info(
        "request",
        route=route,
        method=method,
        status=status,
        latency_ms=round(latency_ms, 2),
        ip_hash=ip_hash,
        response_bytes=response_bytes,
    )
