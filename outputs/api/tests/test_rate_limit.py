"""Rate-limit unit and integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from outputs.api import _rate_limit as rl


def test_check_allows_under_limit() -> None:
    rl.reset()
    allowed_count = 0
    for _ in range(rl.MAX_REQUESTS_PER_WINDOW):
        allowed, _retry = rl.check("ip-hash-A", now=1000.0)
        if allowed:
            allowed_count += 1
    assert allowed_count == rl.MAX_REQUESTS_PER_WINDOW


def test_check_denies_over_limit_with_retry_after() -> None:
    rl.reset()
    for _ in range(rl.MAX_REQUESTS_PER_WINDOW):
        rl.check("ip-hash-B", now=1000.0)
    allowed, retry = rl.check("ip-hash-B", now=1010.0)
    assert allowed is False
    assert 1 <= retry <= rl.WINDOW_SECONDS


def test_check_resets_after_window() -> None:
    rl.reset()
    for _ in range(rl.MAX_REQUESTS_PER_WINDOW):
        rl.check("ip-hash-C", now=1000.0)
    allowed, _retry = rl.check("ip-hash-C", now=1000.0 + rl.WINDOW_SECONDS + 1)
    assert allowed is True


def test_check_per_ip_isolated() -> None:
    """One IP saturating its limit must not block another IP."""
    rl.reset()
    for _ in range(rl.MAX_REQUESTS_PER_WINDOW):
        rl.check("ip-hash-D", now=1000.0)
    allowed_d, _ = rl.check("ip-hash-D", now=1000.0)
    allowed_e, _ = rl.check("ip-hash-E", now=1000.0)
    assert allowed_d is False
    assert allowed_e is True


def test_rate_limit_returns_429_via_http(client: TestClient) -> None:
    # The TestClient uses a fixed client host, so all requests collapse
    # to one hashed IP. After MAX_REQUESTS_PER_WINDOW, we should 429.
    for _ in range(rl.MAX_REQUESTS_PER_WINDOW):
        r = client.get("/v1/health")
        assert r.status_code == 200
    r = client.get("/v1/health")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
