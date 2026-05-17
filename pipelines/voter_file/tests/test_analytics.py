"""Tests for the cross-pipeline analytics surface (Phase 2.3).

These tests pin three things:

1. Voter aggregate views read through `voter.public_voters`, so
   suppressions cascade automatically into county and precinct
   rollups.

2. The precinct-level rollup enforces a minimum-cell-size threshold
   (small cells return NULL with `suppressed_for_size = TRUE`). The
   threshold is referenced symbolically here so a future bump must be
   made in BOTH the SQL and the tests, which forces an explicit code
   review of the privacy posture.

3. The cross-pipeline view `analytics.seb_voter_overlap` joins SEB
   meetings to voter aggregates by TIME (calendar quarter) and
   GEOGRAPHY (county), never by per-voter identifiers. This is the
   ADR-0004 Rule 4 contract.

Tests build their warehouse with synthetic data so we can predict exact
counts. They do not touch the real workbook or the real SOS voter file.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import pytest

from warehouse import loader as warehouse
from warehouse.suppressions import Suppression, apply_suppressions

# Minimum cell size for precinct-level rollups. Must match the threshold
# in `warehouse/schema/voter.sql` view `voter.precinct_registration_summary`.
# Bumping the threshold requires changing both files; that's the point.
PRECINCT_MIN_CELL_SIZE = 25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connect_with_schema(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db_path = tmp_path / "ga.duckdb"
    conn = duckdb.connect(str(db_path))
    warehouse.apply_schema(conn)
    return conn


def _insert_voter(
    conn: duckdb.DuckDBPyConnection,
    *,
    voter_id: int,
    county: str = "FULTON",
    precinct: str = "FULTON-001",
    status: str = "Active",
    zip5: str = "30303",
) -> None:
    conn.execute(
        "INSERT INTO voter.voters "
        "(voter_id, first_name, last_name, county, precinct, status, residence_zip5) "
        "VALUES (?, 'A', 'B', ?, ?, ?, ?)",
        (voter_id, county, precinct, status, zip5),
    )


def _insert_meeting(
    conn: duckdb.DuckDBPyConnection,
    *,
    meeting_id: int,
    meeting_date: dt.date,
    compliance_status: str = "Clean",
    quorum_met: str = "Yes",
    controversies: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO seb.meetings "
        "(meeting_id, meeting_date, day_of_week, meeting_type, meeting_format, "
        " chair, members_present, quorum_met, compliance_status, controversies) "
        "VALUES (?, ?, ?, 'Regular', 'In-Person', 'Chair', 'A,B,C', ?, ?, ?)",
        (
            meeting_id,
            meeting_date,
            meeting_date.strftime("%a")[:3],
            quorum_met,
            compliance_status,
            controversies,
        ),
    )


# ---------------------------------------------------------------------------
# Loader: schema and queries both apply
# ---------------------------------------------------------------------------


def test_apply_schema_loads_query_files_after_schema_files(tmp_path: Path):
    """`apply_schema` runs schema/*.sql, then queries/*.sql, in that order.

    The cross-pipeline analytics views depend on per-pipeline base
    tables, so query files must run second.
    """
    conn = _connect_with_schema(tmp_path)
    rows = conn.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema IN ('analytics', 'voter', 'seb') "
        "  AND table_name IN ('seb_voter_overlap', 'seb_meeting_quarter', "
        "                     'county_registration_summary', 'meetings') "
        "ORDER BY table_schema, table_name"
    ).fetchall()
    names = {(s, t) for s, t in rows}
    assert ("seb", "meetings") in names
    assert ("voter", "county_registration_summary") in names
    assert ("analytics", "seb_meeting_quarter") in names
    assert ("analytics", "seb_voter_overlap") in names


def test_apply_queries_is_idempotent(tmp_path: Path):
    """Running apply_queries twice doesn't error (uses CREATE OR REPLACE)."""
    conn = _connect_with_schema(tmp_path)
    # already applied once via apply_schema; apply once more directly
    warehouse.apply_queries(conn)
    warehouse.apply_queries(conn)
    # views still queryable
    conn.execute("SELECT 1 FROM analytics.seb_voter_overlap LIMIT 0")


# ---------------------------------------------------------------------------
# County rollup
# ---------------------------------------------------------------------------


def test_county_rollup_counts_voters_by_county_and_status(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_voter(conn, voter_id=1, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=2, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=3, county="FULTON", status="Inactive")
    _insert_voter(conn, voter_id=4, county="DEKALB", status="Active")

    rows = conn.execute(
        "SELECT county, status, voter_count "
        "FROM voter.county_registration_summary "
        "ORDER BY county, status"
    ).fetchall()
    assert rows == [
        ("DEKALB", "Active", 1),
        ("FULTON", "Active", 2),
        ("FULTON", "Inactive", 1),
    ]


def test_county_rollup_excludes_null_county(tmp_path: Path):
    """A voter with NULL county is not in any county rollup row."""
    conn = _connect_with_schema(tmp_path)
    _insert_voter(conn, voter_id=1, county="FULTON")
    # NULL county
    conn.execute("INSERT INTO voter.voters (voter_id, first_name, last_name) VALUES (2, 'X', 'Y')")
    counties = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT county FROM voter.county_registration_summary"
        ).fetchall()
    ]
    assert counties == ["FULTON"]


def test_suppressions_cascade_into_county_rollup(tmp_path: Path):
    """Suppressing a voter drops their row from the county rollup."""
    conn = _connect_with_schema(tmp_path)
    _insert_voter(conn, voter_id=1, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=2, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=3, county="FULTON", status="Active")

    # Baseline: 3 active in Fulton
    assert _county_count(conn, "FULTON", "Active") == 3

    # Suppress voter 2
    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=2,
                action="suppress",
                reason="test",
                requested_by="rosario",
            )
        ],
    )

    # County rollup drops to 2
    assert _county_count(conn, "FULTON", "Active") == 2

    # And the underlying voters table still has the row (suppression
    # is a filter, not a rewrite).
    raw = conn.execute("SELECT COUNT(*) FROM voter.voters WHERE county = 'FULTON'").fetchone()[0]
    assert raw == 3


def test_suppression_reverse_restores_county_count(tmp_path: Path):
    """An 'unsuppress' that supersedes a 'suppress' restores the rollup."""
    conn = _connect_with_schema(tmp_path)
    _insert_voter(conn, voter_id=1, county="FULTON")
    _insert_voter(conn, voter_id=2, county="FULTON")

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=2,
                action="suppress",
                reason="test",
                requested_by="rosario",
            )
        ],
    )
    assert _county_count(conn, "FULTON", "Active") == 1

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s2",
                voter_id=2,
                action="unsuppress",
                reason="reversal",
                requested_by="rosario",
                supersedes="s1",
            )
        ],
    )
    assert _county_count(conn, "FULTON", "Active") == 2


def _county_count(conn: duckdb.DuckDBPyConnection, county: str, status: str) -> int:
    row = conn.execute(
        "SELECT voter_count FROM voter.county_registration_summary WHERE county = ? AND status = ?",
        (county, status),
    ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Precinct rollup with minimum-cell-size suppression
# ---------------------------------------------------------------------------


def test_precinct_rollup_suppresses_small_cells(tmp_path: Path):
    """A precinct/status cell with < PRECINCT_MIN_CELL_SIZE voters returns NULL."""
    conn = _connect_with_schema(tmp_path)
    # Only 5 voters in a precinct — well below threshold
    for vid in range(1, 6):
        _insert_voter(conn, voter_id=vid, precinct="FULTON-001")

    row = conn.execute(
        "SELECT voter_count, suppressed_for_size "
        "FROM voter.precinct_registration_summary "
        "WHERE precinct = 'FULTON-001'"
    ).fetchone()
    assert row == (None, True)


def test_precinct_rollup_passes_through_large_cells(tmp_path: Path):
    """A precinct/status cell with >= PRECINCT_MIN_CELL_SIZE voters reports the count."""
    conn = _connect_with_schema(tmp_path)
    n = PRECINCT_MIN_CELL_SIZE  # exactly at threshold should pass
    for vid in range(1, n + 1):
        _insert_voter(conn, voter_id=vid, precinct="FULTON-002")

    row = conn.execute(
        "SELECT voter_count, suppressed_for_size "
        "FROM voter.precinct_registration_summary "
        "WHERE precinct = 'FULTON-002'"
    ).fetchone()
    assert row == (n, False)


def test_precinct_rollup_excludes_null_precinct(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    # NULL precinct
    conn.execute(
        "INSERT INTO voter.voters (voter_id, first_name, last_name, county) "
        "VALUES (1, 'X', 'Y', 'FULTON')"
    )
    rows = conn.execute("SELECT COUNT(*) FROM voter.precinct_registration_summary").fetchone()[0]
    assert rows == 0


# ---------------------------------------------------------------------------
# SEB meeting quarter rollup
# ---------------------------------------------------------------------------


def test_seb_meeting_quarter_bins_by_calendar_quarter(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    # Two meetings in 2024-Q1 (Jan, Mar), one in 2024-Q2 (Apr)
    _insert_meeting(conn, meeting_id=1, meeting_date=dt.date(2024, 1, 15))
    _insert_meeting(conn, meeting_id=2, meeting_date=dt.date(2024, 3, 20))
    _insert_meeting(conn, meeting_id=3, meeting_date=dt.date(2024, 4, 10))

    rows = conn.execute(
        "SELECT year, quarter, meeting_count "
        "FROM analytics.seb_meeting_quarter "
        "ORDER BY year, quarter"
    ).fetchall()
    assert rows == [(2024, 1, 2), (2024, 2, 1)]


def test_seb_meeting_quarter_separates_compliance_status(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_meeting(
        conn, meeting_id=1, meeting_date=dt.date(2024, 1, 15), compliance_status="Clean"
    )
    _insert_meeting(
        conn,
        meeting_id=2,
        meeting_date=dt.date(2024, 2, 10),
        compliance_status="Concerns",
    )

    rows = conn.execute(
        "SELECT compliance_status, meeting_count "
        "FROM analytics.seb_meeting_quarter "
        "WHERE year = 2024 AND quarter = 1 "
        "ORDER BY compliance_status"
    ).fetchall()
    assert rows == [("Clean", 1), ("Concerns", 1)]


def test_seb_meeting_quarter_counts_controversies(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_meeting(
        conn,
        meeting_id=1,
        meeting_date=dt.date(2024, 1, 15),
        controversies="Major issue with ballot delivery",
    )
    _insert_meeting(conn, meeting_id=2, meeting_date=dt.date(2024, 2, 10), controversies=None)
    _insert_meeting(conn, meeting_id=3, meeting_date=dt.date(2024, 3, 5), controversies="None")

    row = conn.execute(
        "SELECT controversy_meeting_count FROM analytics.seb_meeting_quarter "
        "WHERE year = 2024 AND quarter = 1"
    ).fetchone()
    # Only meeting 1 counts: None-the-string and NULL both don't count
    assert row == (1,)


# ---------------------------------------------------------------------------
# Cross-pipeline view
# ---------------------------------------------------------------------------


def test_overlap_view_has_expected_columns(tmp_path: Path):
    """Pin the column contract so downstream consumers don't break silently."""
    conn = _connect_with_schema(tmp_path)
    cols = [
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analytics' AND table_name = 'seb_voter_overlap' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    assert cols == [
        "year",
        "quarter",
        "county",
        "voter_status",
        "voter_count",
        "distinct_zip5_count",
        "compliance_status",
        "meeting_count",
        "quorum_met_count",
        "controversy_meeting_count",
    ]


def test_overlap_view_excludes_per_voter_identifiers(tmp_path: Path):
    """ADR-0004 Rule 4: no per-voter columns leak into the cross-pipeline view.

    If a future change adds voter_id, residence_zip5, birth_year, or
    precinct to this view, that's a privacy regression and this test
    must fail loudly.
    """
    conn = _connect_with_schema(tmp_path)
    cols = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'analytics' AND table_name = 'seb_voter_overlap'"
        ).fetchall()
    }
    forbidden = {
        "voter_id",
        "first_name",
        "last_name",
        "middle_name",
        "residence_zip5",
        "residence_house_number",
        "residence_street_name",
        "residence_apartment",
        "residence_city",
        "birth_year",
        "precinct",
    }
    leaks = cols & forbidden
    assert leaks == set(), f"Per-voter columns leaked into overlap view: {leaks}"


def test_overlap_view_is_cross_product_of_quarter_status_and_county_status(
    tmp_path: Path,
):
    """The view cross-joins (year, quarter, compliance_status) × (county, voter_status)."""
    conn = _connect_with_schema(tmp_path)
    # 1 meeting in 2024-Q1, 2 voters in Fulton (1 Active, 1 Inactive)
    _insert_meeting(conn, meeting_id=1, meeting_date=dt.date(2024, 1, 15))
    _insert_voter(conn, voter_id=1, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=2, county="FULTON", status="Inactive")

    rows = conn.execute(
        "SELECT year, quarter, county, voter_status, compliance_status, "
        "       voter_count, meeting_count "
        "FROM analytics.seb_voter_overlap "
        "ORDER BY county, voter_status"
    ).fetchall()
    # 1 (year,quarter,compliance) × 2 (county,voter_status) = 2 rows
    assert rows == [
        (2024, 1, "FULTON", "Active", "Clean", 1, 1),
        (2024, 1, "FULTON", "Inactive", "Clean", 1, 1),
    ]


def test_overlap_view_reflects_suppressions(tmp_path: Path):
    """Suppressing a voter drops their contribution to the cross-pipeline view."""
    conn = _connect_with_schema(tmp_path)
    _insert_meeting(conn, meeting_id=1, meeting_date=dt.date(2024, 1, 15))
    _insert_voter(conn, voter_id=1, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=2, county="FULTON", status="Active")

    before = conn.execute(
        "SELECT voter_count FROM analytics.seb_voter_overlap "
        "WHERE year = 2024 AND quarter = 1 AND county = 'FULTON' "
        "  AND voter_status = 'Active'"
    ).fetchone()[0]
    assert before == 2

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=1,
                action="suppress",
                reason="test",
                requested_by="rosario",
            )
        ],
    )

    after = conn.execute(
        "SELECT voter_count FROM analytics.seb_voter_overlap "
        "WHERE year = 2024 AND quarter = 1 AND county = 'FULTON' "
        "  AND voter_status = 'Active'"
    ).fetchone()[0]
    assert after == 1


def test_overlap_view_is_empty_when_one_side_is_empty(tmp_path: Path):
    """If there are no meetings (or no voters), the overlap is empty.

    A cross join with one empty side produces zero rows — that's the
    expected, honest answer.
    """
    conn = _connect_with_schema(tmp_path)
    # Only voters, no meetings
    _insert_voter(conn, voter_id=1, county="FULTON")
    rows = conn.execute("SELECT COUNT(*) FROM analytics.seb_voter_overlap").fetchone()[0]
    assert rows == 0


# ---------------------------------------------------------------------------
# Worked example: non-Clean compliance quarters × county registration
# ---------------------------------------------------------------------------


def test_worked_example_non_clean_quarters_with_registration(tmp_path: Path):
    """The motivating Phase 2.3 query: counties × quarters where SEB had
    non-Clean compliance, alongside registration counts.

    This is the kind of query a civic researcher might write against the
    cross-pipeline view. We pin its shape and result here so the public
    surface stays stable as the underlying schemas evolve.
    """
    conn = _connect_with_schema(tmp_path)
    _insert_meeting(
        conn,
        meeting_id=1,
        meeting_date=dt.date(2024, 1, 15),
        compliance_status="Concerns",
    )
    _insert_meeting(
        conn,
        meeting_id=2,
        meeting_date=dt.date(2024, 2, 10),
        compliance_status="Clean",
    )
    _insert_voter(conn, voter_id=1, county="FULTON", status="Active")
    _insert_voter(conn, voter_id=2, county="DEKALB", status="Active")

    rows = conn.execute(
        """
        SELECT year, quarter, county, voter_count, compliance_status, meeting_count
        FROM analytics.seb_voter_overlap
        WHERE compliance_status <> 'Clean'
          AND voter_status = 'Active'
        ORDER BY county, year, quarter
        """
    ).fetchall()
    assert rows == [
        (2024, 1, "DEKALB", 1, "Concerns", 1),
        (2024, 1, "FULTON", 1, "Concerns", 1),
    ]


# ---------------------------------------------------------------------------
# Architectural boundary: query files must not contain CREATE TABLE
# ---------------------------------------------------------------------------


def test_query_files_define_views_not_tables():
    """Cross-pipeline analytic files must compose views, never declare base tables.

    A `CREATE TABLE` in `warehouse/queries/` would be a base for one
    pipeline that happens to live in the cross-pipeline directory —
    that violates the boundary described in `warehouse/schema/seb.sql`
    line 4.
    """
    queries_dir = warehouse.QUERIES_DIR
    sql_files = list(queries_dir.glob("*.sql"))
    assert sql_files, "expected at least one query file in warehouse/queries/"
    for path in sql_files:
        text = path.read_text().upper()
        # strip line comments so we don't false-positive on commented-out CREATE TABLE
        stripped = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
        assert "CREATE TABLE" not in stripped, (
            f"{path.name}: query files must not define base tables; "
            "use CREATE VIEW or CREATE OR REPLACE VIEW instead"
        )


# silence unused-import warnings when pytest collects but doesn't run a fixture
_ = pytest  # noqa
