"""End-to-end flow test against a temp DuckDB warehouse.

Skips the YouTube network step (`skip_network=True`) so this test is
hermetic. The RSS branch has its own unit tests in `test_youtube_rss.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from pipelines.seb_meetings.flows.ingest import ingest_seb_meetings  # noqa: E402
from warehouse import loader as warehouse  # noqa: E402


def test_seed_flow_lands_expected_row_counts(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    summary = ingest_seb_meetings(db_path=db_path, skip_network=True)
    assert summary["seed"] == {
        "meetings": 17,
        "controversies": 8,
        "sources": 15,
    }
    assert summary["schema_files_applied"] >= 1

    with warehouse.connect(db_path) as conn:
        assert warehouse.count_meetings(conn) == 17
        # The 'source' provenance column is populated, not NULL.
        all_sourced = conn.execute(
            "SELECT COUNT(*) FROM seb.meetings WHERE source IS NULL"
        ).fetchone()[0]
        assert all_sourced == 0


def test_seed_flow_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    ingest_seb_meetings(db_path=db_path, skip_network=True)
    ingest_seb_meetings(db_path=db_path, skip_network=True)
    with warehouse.connect(db_path) as conn:
        assert warehouse.count_meetings(conn) == 17


def test_hours_check_constraint_actually_works(tmp_path: Path):
    """The CHECK constraint on hours_logged should reject 25.0."""
    db_path = tmp_path / "test.duckdb"
    ingest_seb_meetings(db_path=db_path, skip_network=True)
    with warehouse.connect(db_path) as conn, pytest.raises(duckdb.ConstraintException):
        conn.execute(
            "INSERT INTO seb.meetings "
            "(meeting_id, meeting_date, day_of_week, meeting_type, "
            " meeting_format, chair, members_present, quorum_met, "
            " compliance_status, hours_logged) "
            "VALUES (9999, '2026-01-01', 'Thu', 'Regular', 'Zoom', "
            "'X', 'X', 'Yes', 'Compliant', 25.0)"
        )
