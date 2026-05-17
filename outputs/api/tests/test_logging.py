"""IP-hash and logging unit tests."""

from __future__ import annotations

import pytest

from outputs.api import _logging


def test_hash_ip_is_stable_within_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "fixed-test-salt")
    h1 = _logging.hash_ip("203.0.113.5")
    h2 = _logging.hash_ip("203.0.113.5")
    assert h1 == h2


def test_hash_ip_differs_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "fixed-test-salt")
    h1 = _logging.hash_ip("203.0.113.5")
    h2 = _logging.hash_ip("203.0.113.6")
    assert h1 != h2


def test_hash_ip_differs_across_salts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily-rotating salt means the same IP hashes differently
    if the base salt changes — simulating the day-boundary rotation."""
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "salt-day-1")
    h1 = _logging.hash_ip("203.0.113.5")
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "salt-day-2")
    h2 = _logging.hash_ip("203.0.113.5")
    assert h1 != h2


def test_hash_ip_is_16_hex_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "fixed-test-salt")
    h = _logging.hash_ip("203.0.113.5")
    assert len(h) == 16
    int(h, 16)  # parses as hex.
