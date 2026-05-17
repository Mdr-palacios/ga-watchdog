"""Allow-list contract tests for the public read API.

These tests are the second half of the two-layer enforcement described
in ADR-0005 decision 2. The first half (SQL view chain) lives in
`warehouse/schema/voter.sql` and `warehouse/queries/seb_voter_overlap.sql`.
This file enforces, at PR time, that no route handler reads from a
source that isn't on the allow-list.

The strategy is mechanical: walk every `.py` in `outputs/api/routes/`
and `outputs/api/bulk_export.py`, regex out every `FROM schema.name`
fragment, and assert each one is in `ALLOWED_PUBLIC_SOURCES` and not
in `EXPLICITLY_DENIED_SOURCES`. The regex is intentionally simple —
SQL is a static string in this codebase, no dynamic FROM clauses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from outputs.api._allowed_sources import (
    ALLOWED_PUBLIC_SOURCES,
    EXPLICITLY_DENIED_SOURCES,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTES_DIR = REPO_ROOT / "outputs" / "api" / "routes"
BULK_EXPORT = REPO_ROOT / "outputs" / "api" / "bulk_export.py"

# Matches `FROM schema.name` where schema and name are SQL identifiers.
# Two-part only — we never read from `main.something` without a schema
# qualifier, and this regex pins that convention.
_FROM_RE = re.compile(r"\bFROM\s+([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)", re.IGNORECASE)


def _route_files() -> list[Path]:
    files = [p for p in ROUTES_DIR.glob("*.py") if p.name != "__init__.py"]
    files.append(BULK_EXPORT)
    return files


def _from_sources_in(path: Path) -> set[str]:
    text = path.read_text()
    return set(_FROM_RE.findall(text))


def test_every_route_file_uses_only_allowed_sources() -> None:
    """No route handler may read from a non-allow-listed source."""
    offenders: dict[str, set[str]] = {}
    for f in _route_files():
        bad = {s for s in _from_sources_in(f) if s not in ALLOWED_PUBLIC_SOURCES}
        if bad:
            offenders[str(f.relative_to(REPO_ROOT))] = bad
    assert not offenders, (
        f"Disallowed sources used in route handlers: {offenders}. "
        "Either add them to ALLOWED_PUBLIC_SOURCES (with an ADR review) "
        "or rewrite the route to use an aggregate view."
    )


@pytest.mark.parametrize("denied", sorted(EXPLICITLY_DENIED_SOURCES))
def test_no_route_reads_explicitly_denied_source(denied: str) -> None:
    """No route handler may read from a source on the denial list.

    This is belt-and-suspenders next to the allow-list test. A
    contributor who hits both failures sees two different messages:
    one about the allow-list (mechanical) and one about the denial
    (with reasoning attached to each denied name in `_allowed_sources.py`).
    """
    offenders: list[str] = []
    for f in _route_files():
        if denied in _from_sources_in(f):
            offenders.append(str(f.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"Source {denied!r} is on EXPLICITLY_DENIED_SOURCES but is "
        f"queried from: {offenders}. See `_allowed_sources.py` for "
        "why this source is denied."
    )


def test_allow_list_and_deny_list_are_disjoint() -> None:
    """A source cannot be both allowed and denied. Sanity check."""
    overlap = ALLOWED_PUBLIC_SOURCES & EXPLICITLY_DENIED_SOURCES
    assert not overlap, f"Sources both allowed and denied: {overlap}"


def test_allow_list_names_match_warehouse_schemas() -> None:
    """Every name in ALLOWED_PUBLIC_SOURCES must exist in warehouse SQL.

    Catches the case where a view gets renamed in the warehouse and the
    allow-list silently keeps pointing at a name that no longer exists.
    Scans the warehouse SQL files for `CREATE TABLE`/`CREATE VIEW` and
    builds the universe of real names; every allow-listed name must be
    in that universe.
    """
    warehouse_sql = list((REPO_ROOT / "warehouse").rglob("*.sql"))
    universe: set[str] = set()
    create_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)"
        r"(?:\s+IF\s+NOT\s+EXISTS)?\s+([a-zA-Z_][\w]*\.[a-zA-Z_][\w]*)",
        re.IGNORECASE,
    )
    for sql_file in warehouse_sql:
        universe.update(create_re.findall(sql_file.read_text()))
    missing = ALLOWED_PUBLIC_SOURCES - universe
    assert not missing, (
        f"Allow-listed sources not found in warehouse SQL: {missing}. "
        f"Either the view was renamed or the allow-list is stale. "
        f"Known names: {sorted(universe)}"
    )
