"""Tests that pin the statute into the schema.

These tests exist because the `Voter` model carries promises that
ADR-0004 (and Georgia law) make to voters. A future contributor adding
a "convenient" `ssn` field to make a JOIN easier should fail CI before
they get the chance to land it.

What we're proving:
  1. No statutorily-confidential field can land on Voter via extra=allow drift.
  2. `Voter` instances cannot be constructed with a full date of birth.
  3. The confidential-field list is a single source of truth, exported.
  4. The warehouse schema mirrors the model — both refuse confidential columns.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

duckdb = pytest.importorskip("duckdb")

from pipelines.voter_file.transforms.models import (  # noqa: E402
    STATUTORY_CONFIDENTIAL_FIELDS,
    Voter,
    VoterStatus,
)
from warehouse import loader as warehouse  # noqa: E402


def _valid_kwargs() -> dict:
    """Minimal Voter kwargs — all statutorily public, obviously synthetic."""
    return {
        "voter_id": 999_999,
        "first_name": "Synthetic",
        "last_name": "TestRecord",
        "birth_year": 1990,
        "residence_city": "Atlanta",
        "residence_zip5": "30303",
        "status": VoterStatus.ACTIVE,
    }


# ---------------------------------------------------------------------------
# Rule 1: confidential fields cannot land on Voter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("confidential_field", sorted(STATUTORY_CONFIDENTIAL_FIELDS))
def test_voter_rejects_every_statutory_confidential_field(confidential_field: str):
    """For every name in the confidential list, constructing a Voter
    with that field must raise. This is the statute, encoded as a test.
    """
    kwargs = _valid_kwargs()
    kwargs[confidential_field] = "leaked-value"
    with pytest.raises(ValidationError) as exc_info:
        Voter(**kwargs)
    # Pydantic's `extra="forbid"` reports the offending field by name.
    assert confidential_field in str(exc_info.value)


def test_voter_rejects_birth_date_in_any_common_alias():
    """Date-of-birth aliases ('birth_date', 'date_of_birth', 'dob') all fail."""
    for alias in ("birth_date", "date_of_birth", "dob"):
        kwargs = _valid_kwargs()
        kwargs[alias] = date(1990, 5, 14)
        with pytest.raises(ValidationError):
            Voter(**kwargs)


def test_voter_accepts_year_of_birth_only():
    """The statute makes year of birth public — Voter must accept it."""
    v = Voter(**_valid_kwargs())
    assert v.birth_year == 1990


def test_voter_birth_year_bounds_are_enforced():
    """Year-of-birth must be a plausible integer; nonsense rejected."""
    for bad in (1700, 2200, -1):
        kwargs = _valid_kwargs()
        kwargs["birth_year"] = bad
        with pytest.raises(ValidationError):
            Voter(**kwargs)


# ---------------------------------------------------------------------------
# Rule 1, second layer: confidential list is a single source of truth
# ---------------------------------------------------------------------------


def test_confidential_field_list_is_exported_and_non_empty():
    """The list must be importable; the test suite iterates it.

    If a future change makes it empty or drops the well-known names,
    that's a red flag — fail loudly.
    """
    assert "ssn" in STATUTORY_CONFIDENTIAL_FIELDS
    assert "dl_number" in STATUTORY_CONFIDENTIAL_FIELDS
    assert "email" in STATUTORY_CONFIDENTIAL_FIELDS
    assert "birth_date" in STATUTORY_CONFIDENTIAL_FIELDS
    assert "registration_location" in STATUTORY_CONFIDENTIAL_FIELDS


def test_voter_classmethod_exposes_confidential_list():
    """`Voter.confidential_field_names()` mirrors the module constant."""
    assert Voter.confidential_field_names() == STATUTORY_CONFIDENTIAL_FIELDS


# ---------------------------------------------------------------------------
# Rule 1, third layer: the warehouse schema does not contain confidential cols
# ---------------------------------------------------------------------------


def test_warehouse_voter_table_does_not_contain_any_confidential_column(tmp_path: Path):
    """The DuckDB schema for voter.voters must not declare any column
    name from STATUTORY_CONFIDENTIAL_FIELDS. If someone adds one, this
    test fails — they cannot land a confidential column in CI.
    """
    db_path = tmp_path / "test.duckdb"
    with warehouse.connect(db_path) as conn:
        warehouse.apply_schema(conn)
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'voter' AND table_name = 'voters'"
            ).fetchall()
        }
    leaked = columns & STATUTORY_CONFIDENTIAL_FIELDS
    assert not leaked, f"warehouse schema contains confidential columns: {sorted(leaked)}"


def test_warehouse_voter_schema_creates_expected_tables(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    with warehouse.connect(db_path) as conn:
        warehouse.apply_schema(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'voter'"
            ).fetchall()
        }
    assert "voters" in tables
    assert "suppressions" in tables
    assert "active_suppressions" in tables  # the view counts as a table here


def test_voter_record_round_trips_through_warehouse(tmp_path: Path):
    """A valid synthetic Voter can be inserted and read back; sanity check."""
    db_path = tmp_path / "test.duckdb"
    v = Voter(**_valid_kwargs())
    with warehouse.connect(db_path) as conn:
        warehouse.apply_schema(conn)
        conn.execute(
            "INSERT INTO voter.voters "
            "(voter_id, first_name, last_name, birth_year, residence_city, "
            " residence_zip5, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                v.voter_id,
                v.first_name,
                v.last_name,
                v.birth_year,
                v.residence_city,
                v.residence_zip5,
                v.status.value,
            ),
        )
        row = conn.execute(
            "SELECT voter_id, first_name, last_name, birth_year, residence_zip5 "
            "FROM voter.voters WHERE voter_id = ?",
            (v.voter_id,),
        ).fetchone()
    assert row == (999_999, "Synthetic", "TestRecord", 1990, "30303")
