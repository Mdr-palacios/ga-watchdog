"""Shared fixtures for API tests.

Builds a minimal DuckDB warehouse in a tmp_path, populates the schemas
the routes read from, and yields a `TestClient` wired up to it.

Seed data is deliberately tiny — just enough to make every route return
non-empty results. Schema-level invariants are tested elsewhere
(`pipelines/seb_meetings/tests/`, `pipelines/voter_file/tests/`); these
fixtures only exist to exercise the API surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_warehouse(db_path: Path) -> None:
    """Construct a tiny warehouse: real schema, a handful of rows."""
    schema_files = [
        REPO_ROOT / "warehouse" / "schema" / "seb.sql",
        REPO_ROOT / "warehouse" / "schema" / "seb_corrections.sql",
        REPO_ROOT / "warehouse" / "schema" / "voter.sql",
        REPO_ROOT / "warehouse" / "queries" / "seb_voter_overlap.sql",
    ]
    conn = duckdb.connect(str(db_path))
    try:
        for f in schema_files:
            conn.execute(f.read_text())
        # Two meetings, one video, one source row, three voters in two
        # counties. quorum_met is VARCHAR ('Yes'/'No') per the schema.
        conn.execute(
            """
            INSERT INTO seb.meetings
              (meeting_id, meeting_date, day_of_week, meeting_type,
               meeting_format, chair, members_present, quorum_met,
               agenda_summary, key_decisions, video_url, source_url,
               compliance_status, compliance_notes, controversies,
               hours_logged)
            VALUES
              (1, DATE '2024-01-09', 'Tue', 'Regular',
               'In-person', 'Sara Tindall Ghazal', 'All', 'Yes',
               'January regular meeting agenda', '', '', '',
               'Compliant', '', '', 2.5),
              (2, DATE '2024-02-12', 'Mon', 'Special',
               'Hybrid', 'Sara Tindall Ghazal', '4 of 5', 'Yes',
               'February special meeting agenda', '', '', '',
               'Unreviewed', 'Called short-notice', 'Short notice', 1.0)
            """
        )
        conn.execute(
            """
            INSERT INTO seb.videos
              (video_id, meeting_id, video_url, title,
               published_date, description)
            VALUES
              ('v1', 1, 'https://example.com/v1', 'Jan 9 part 1',
               DATE '2024-01-09', 'Recording of the Jan 9 meeting')
            """
        )
        conn.execute(
            """
            INSERT INTO seb.sources
              (source_id, name, source_type, url, notes)
            VALUES
              (1, 'GA SOS', 'Primary', 'https://sos.ga.gov/seb', '')
            """
        )
        # Voters: two in Fulton, one in Bibb. Active status. No
        # suppressions, so all three flow through public_voters into
        # county_registration_summary into seb_voter_overlap.
        conn.execute(
            """
            INSERT INTO voter.voters
              (voter_id, first_name, last_name, birth_year,
               residence_zip5, status, county, source)
            VALUES
              (1, 'A', 'A', 1980, '30303', 'Active', 'Fulton', 'test'),
              (2, 'B', 'B', 1985, '30305', 'Active', 'Fulton', 'test'),
              (3, 'C', 'C', 1970, '31201', 'Active', 'Bibb', 'test')
            """
        )
    finally:
        conn.close()


@pytest.fixture
def warehouse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "warehouse.duckdb"
    _build_warehouse(db_path)
    monkeypatch.setenv("GA_WATCHDOG_WAREHOUSE_PATH", str(db_path))
    yield db_path


@pytest.fixture
def client(warehouse: Path) -> Iterator[TestClient]:
    # Import here so the env var is set before any module reads it.
    from outputs.api._rate_limit import reset as reset_rl
    from outputs.api.app import create_app

    reset_rl()
    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_rl()


@pytest.fixture(autouse=True)
def _isolated_ip_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GA_WATCHDOG_IP_SALT", "test-salt-fixed")
