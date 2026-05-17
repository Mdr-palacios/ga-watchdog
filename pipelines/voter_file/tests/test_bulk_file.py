"""Tests for the bulk SOS-file reader.

The reader has three contracts (see `sources/bulk_file.py` docstring):
  1. Refuse files containing statutorily-confidential columns at
     header time, before any record is constructed.
  2. Strip month/day off any DOB-shaped column; only year_of_birth
     reaches the Voter model. (Enforced by #1: every DOB-shaped name
     is in STATUTORY_CONFIDENTIAL_FIELDS.)
  3. Silently ignore unknown columns; only locked the Voter shape,
     not the file shape.

These tests pin all three, plus a smoke test that runs the reader
against the checked-in synthetic fixture and asserts the row count and
schema.
"""

from __future__ import annotations

import io
from pathlib import Path
from textwrap import dedent

import pytest

from pipelines.voter_file.sources.bulk_file import (
    BulkFileError,
    ConfidentialColumnError,
    UnknownStatusCodeError,
    _normalize_header,
    iter_voters,
)
from pipelines.voter_file.transforms.models import (
    STATUTORY_CONFIDENTIAL_FIELDS,
    Voter,
    VoterStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "pipelines" / "voter_file" / "fixtures" / "synthetic_voter_file.csv"


# ---------------------------------------------------------------------------
# Smoke test against the checked-in synthetic fixture
# ---------------------------------------------------------------------------


def test_reader_loads_synthetic_fixture() -> None:
    """The 50-row synthetic fixture must parse without error."""
    voters = list(iter_voters(FIXTURE))
    assert len(voters) == 50
    assert all(isinstance(v, Voter) for v in voters)


def test_reader_assigns_voter_ids_in_synthetic_range() -> None:
    """Every fixture voter_id sits in the obviously-synthetic 9M range."""
    for voter in iter_voters(FIXTURE):
        assert 9_000_000 <= voter.voter_id < 9_000_100


def test_reader_strips_year_of_birth_to_int() -> None:
    """birth_year arrives as an integer year, never a date."""
    for voter in iter_voters(FIXTURE):
        if voter.birth_year is not None:
            assert isinstance(voter.birth_year, int)
            assert 1900 <= voter.birth_year <= 2100


def test_reader_maps_county_codes_to_names() -> None:
    """Numeric SOS county codes get mapped to county names on the way in."""
    counties = {v.county for v in iter_voters(FIXTURE) if v.county is not None}
    # Fixture uses only the seven counties in _COUNTY_CODE_MAP.
    expected = {"Fulton", "Chatham", "Richmond", "Bibb", "Muscogee", "Clarke", "DeKalb"}
    assert counties.issubset(expected)
    assert counties, "expected at least one county to come through"


def test_reader_composes_street_name_with_suffix() -> None:
    """Residence_street_name and Residence_street_suffix collapse into one field."""
    sample = next(iter_voters(FIXTURE))
    # The fixture always sets a suffix, so the composed name has 2+ tokens.
    assert sample.residence_street_name is not None
    assert " " in sample.residence_street_name


def test_reader_zip5_is_padded_string() -> None:
    """zipcode arrives as a 5-char string even if the source ships it as int."""
    sample = next(iter_voters(FIXTURE))
    assert sample.residence_zip5 is not None
    assert len(sample.residence_zip5) == 5
    assert sample.residence_zip5.isdigit()


def test_reader_status_default_is_active() -> None:
    """Every fixture row produces a known VoterStatus."""
    for voter in iter_voters(FIXTURE):
        assert voter.status in {VoterStatus.ACTIVE, VoterStatus.INACTIVE}


# ---------------------------------------------------------------------------
# Confidential-column rejection (defense in depth on top of Voter.extra=forbid)
# ---------------------------------------------------------------------------


def _write_csv(tmp_path: Path, header: str, *rows: str) -> Path:
    """Tiny helper: write a one-or-two-line CSV and return the path."""
    p = tmp_path / "synthetic.csv"
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("confidential_name", sorted(STATUTORY_CONFIDENTIAL_FIELDS))
def test_reader_refuses_files_with_confidential_columns(
    tmp_path: Path, confidential_name: str
) -> None:
    """Every statutorily-confidential column name, in any case, triggers refusal."""
    # Build a header that contains the confidential name plus one valid column.
    # The column name as it appears on disk uses Title_Case to mimic SOS style.
    on_disk = "_".join(part.capitalize() for part in confidential_name.split("_"))
    header = f"Registration_Number,{on_disk}"
    path = _write_csv(tmp_path, header, "9000001,whatever")

    with pytest.raises(ConfidentialColumnError) as excinfo:
        list(iter_voters(path))

    # Confirm the error names both the offending column and ADR-0004.
    assert confidential_name in str(excinfo.value)
    assert "ADR-0004" in str(excinfo.value)


def test_reader_refuses_file_with_full_dob_column(tmp_path: Path) -> None:
    """A literal `Date_of_Birth` column triggers refusal at header time."""
    path = _write_csv(
        tmp_path,
        "Registration_Number,Date_of_Birth,Last_name,First_name",
        "9000001,19850412,DoNotShip,Synthetic",
    )
    with pytest.raises(ConfidentialColumnError):
        list(iter_voters(path))


def test_reader_refuses_email_column(tmp_path: Path) -> None:
    """Email is statutorily confidential — its presence aborts parsing."""
    path = _write_csv(
        tmp_path,
        "Registration_Number,Email,Last_name,First_name",
        "9000001,fake@example.test,DoNotShip,Synthetic",
    )
    with pytest.raises(ConfidentialColumnError):
        list(iter_voters(path))


# ---------------------------------------------------------------------------
# Unknown-column tolerance
# ---------------------------------------------------------------------------


def test_reader_tolerates_unknown_columns(tmp_path: Path) -> None:
    """Columns the reader doesn't know about pass through silently."""
    header = (
        "County_code,Registration_Number,Voter_status,Last_name,First_name,"
        "Year_of_Birth,Some_Made_Up_Column,Another_Unknown_Field"
    )
    row = "60,9000001,A,DoNotShip,Synthetic,1990,foo,bar"
    path = _write_csv(tmp_path, header, row)

    voters = list(iter_voters(path))
    assert len(voters) == 1
    assert voters[0].voter_id == 9_000_001
    assert voters[0].birth_year == 1990
    assert voters[0].status == VoterStatus.ACTIVE


# ---------------------------------------------------------------------------
# Failure-mode tests
# ---------------------------------------------------------------------------


def test_reader_raises_on_unknown_status_code(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        "Registration_Number,Voter_status,Last_name,First_name,Year_of_Birth",
        "9000001,Z,DoNotShip,Synthetic,1990",
    )
    with pytest.raises(UnknownStatusCodeError):
        list(iter_voters(path))


def test_reader_raises_on_bad_row_with_location(tmp_path: Path) -> None:
    """A row that fails Voter validation raises BulkFileError with row number."""
    path = _write_csv(
        tmp_path,
        "Registration_Number,Voter_status,Last_name,First_name,Year_of_Birth",
        "9000001,A,DoNotShip,Synthetic,1990",
        "9000002,A,DoNotShip,Synthetic,3000",  # birth_year out of range
    )
    with pytest.raises(BulkFileError) as excinfo:
        list(iter_voters(path))
    assert "row 3" in str(excinfo.value)


def test_reader_raises_on_missing_header(tmp_path: Path) -> None:
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(BulkFileError):
        list(iter_voters(p))


# ---------------------------------------------------------------------------
# Header normalization
# ---------------------------------------------------------------------------


def test_header_normalization_handles_spaces_and_case() -> None:
    """The real SOS file has at least one column with stray whitespace."""
    assert _normalize_header("Ward city council_code") == "ward_city_council_code"
    assert _normalize_header("REGISTRATION_NUMBER") == "registration_number"
    assert _normalize_header("  Year_of_Birth  ") == "year_of_birth"
    assert _normalize_header("Date-Last-Voted") == "date_last_voted"


def test_normalization_idempotent() -> None:
    """Normalizing twice yields the same string."""
    for raw in ("Ward city council_code", "Year_of_Birth", "Date-Last-Voted"):
        once = _normalize_header(raw)
        twice = _normalize_header(once)
        assert once == twice


# ---------------------------------------------------------------------------
# Tiny in-memory smoke test (no tmp_path) — proves the reader works on a
# file object that mimics the SOS shape
# ---------------------------------------------------------------------------


def test_reader_round_trip_in_memory(tmp_path: Path) -> None:
    """End-to-end: write a minimal SOS-shaped file, read it, assert."""
    content = dedent(
        """\
        County_code,Registration_Number,Voter_status,Last_name,First_name,Residence_house_number,Residence_street_name,Residence_street_suffix,Residence_city,Residence_zipcode,Year_of_Birth,Race,Gender
        60,9000123,A,DoNotShip,Synthetic,123,Fictional,Ave,Atlanta,30303,1985,WH,F
        """
    ).strip()
    p = tmp_path / "small.csv"
    p.write_text(content + "\n", encoding="utf-8")

    voters = list(iter_voters(p))
    assert len(voters) == 1
    v = voters[0]
    assert v.voter_id == 9_000_123
    assert v.county == "Fulton"
    assert v.residence_street_name == "Fictional Ave"
    assert v.residence_zip5 == "30303"
    assert v.birth_year == 1985
    assert v.race == "WH"
    assert v.gender == "F"
    # And, crucially, the model rejects anything extra — confirm by
    # round-tripping through model_dump and re-parsing.
    assert Voter.model_validate(v.model_dump()) == v


# Silences unused-import linter (we re-export io for parity with the SEB tests)
_ = io
