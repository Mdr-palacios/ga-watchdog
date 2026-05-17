"""Tests for the TargetSmart-shaped voter-file reader.

The reader has three contracts (see `sources/targetsmart_format.py`):
  1. Refuse files containing statutorily-confidential columns at
     header time, before any record is constructed
     (`ConfidentialColumnError`).
  2. Refuse files containing TargetSmart-licensed / modeled / enriched
     columns at header time (`LicensedColumnError`). This is the
     boundary that makes the reader safe for a public-only civic-tech
     tool that occasionally receives partner files.
  3. Silently ignore unknown columns; locked the Voter shape, not the
     file shape.

These tests pin all three, plus a smoke test against the checked-in
synthetic TargetSmart fixture asserting the row count and that every
mapped field arrives sane.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pipelines.voter_file.sources.targetsmart_format import (
    TARGETSMART_LICENSED_FIELDS,
    ConfidentialColumnError,
    LicensedColumnError,
    TargetSmartFileError,
    _normalize_header,
    _split_address1,
    iter_voters,
)
from pipelines.voter_file.transforms.models import (
    STATUTORY_CONFIDENTIAL_FIELDS,
    Voter,
    VoterStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (
    REPO_ROOT / "pipelines" / "voter_file" / "fixtures" / "synthetic_targetsmart_voter_file.csv"
)


# ---------------------------------------------------------------------------
# Smoke test against the checked-in synthetic TargetSmart fixture
# ---------------------------------------------------------------------------


def test_reader_loads_synthetic_fixture() -> None:
    """The 50-row TargetSmart-shaped fixture must parse without error."""
    voters = list(iter_voters(FIXTURE))
    assert len(voters) == 50
    assert all(isinstance(v, Voter) for v in voters)


def test_reader_assigns_voter_ids_in_synthetic_range(tmp_path: Path) -> None:
    """Every fixture voter_id sits in the obviously-synthetic 9M range.

    The fixture's voterbase_ids look like 'TS009000000'..'TS009000049';
    the reader strips the 'TS' prefix and parses to int.
    """
    for voter in iter_voters(FIXTURE):
        assert 9_000_000 <= voter.voter_id < 9_000_100


def test_reader_maps_county_to_title_case() -> None:
    """TargetSmart ships county in ALL CAPS; the reader produces title case.

    Downstream code (and the SOS reader) uses title case, so we
    normalize here to keep the warehouse representation single-shaped.
    """
    counties = {v.county for v in iter_voters(FIXTURE) if v.county is not None}
    expected = {"Fulton", "Chatham", "Richmond", "Bibb", "Muscogee", "Clarke", "Dekalb"}
    assert counties.issubset(expected)
    assert counties, "expected at least one county to come through"


def test_reader_splits_address1_into_house_and_street() -> None:
    """vf_reg_address1 splits into house_number + street_name."""
    for voter in iter_voters(FIXTURE):
        # Fixture always produces a numeric house + street.
        assert voter.residence_house_number is not None
        assert voter.residence_street_name is not None
        assert voter.residence_house_number.isdigit()
        # Street side has at least the street name + suffix → 2 tokens.
        assert len(voter.residence_street_name.split()) >= 2


def test_reader_zero_pads_zipcode() -> None:
    """vf_reg_zip arrives zero-padded to 5 digits."""
    for voter in iter_voters(FIXTURE):
        if voter.residence_zip5 is not None:
            assert len(voter.residence_zip5) == 5
            assert voter.residence_zip5.isdigit()


def test_reader_maps_status_labels() -> None:
    """vf_voter_status labels map to the model's VoterStatus enum."""
    statuses = {v.status for v in iter_voters(FIXTURE)}
    # Fixture only emits ACTIVE / INACTIVE.
    assert statuses.issubset({VoterStatus.ACTIVE, VoterStatus.INACTIVE})


def test_reader_never_populates_birth_year() -> None:
    """The TargetSmart reader never sets birth_year — the licensed-column
    refusal stops `voterbase_age` from arriving, and we don't accept any
    other DOB-shaped field. Year-of-birth must come from the SOS file.
    """
    for voter in iter_voters(FIXTURE):
        assert voter.birth_year is None


# ---------------------------------------------------------------------------
# Boundary #1: statutorily-confidential columns
# ---------------------------------------------------------------------------


def _write_csv(tmp_path: Path, header: str, row: str) -> Path:
    """Tiny helper: write a one-row CSV with the given header + row."""
    p = tmp_path / "test.csv"
    p.write_text(f"{header}\n{row}\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("confidential", sorted(STATUTORY_CONFIDENTIAL_FIELDS))
def test_reader_refuses_statutory_confidential_columns(tmp_path: Path, confidential: str) -> None:
    """Every confidential column triggers ConfidentialColumnError at header time.

    Parametrized so adding a name to STATUTORY_CONFIDENTIAL_FIELDS
    automatically grows this test's coverage.
    """
    header = f"voterbase_id,{confidential},tsmart_first_name,tsmart_last_name"
    row = "TS000000001,whatever,SYNTHETIC,TESTRECORD"
    p = _write_csv(tmp_path, header, row)
    with pytest.raises(ConfidentialColumnError, match=confidential):
        list(iter_voters(p))


# ---------------------------------------------------------------------------
# Boundary #2: TargetSmart-licensed / modeled / enriched columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("licensed", sorted(TARGETSMART_LICENSED_FIELDS))
def test_reader_refuses_targetsmart_licensed_columns(tmp_path: Path, licensed: str) -> None:
    """Every licensed column triggers LicensedColumnError at header time.

    Parametrized so adding a name to TARGETSMART_LICENSED_FIELDS
    automatically grows this test's coverage. THIS IS THE TEST that
    makes the boundary credible: if someone slips a new vendor field
    into the mapping table without adding it to the refusal set, this
    test (or its absence) tells them.
    """
    header = f"voterbase_id,{licensed},tsmart_first_name,tsmart_last_name"
    row = "TS000000001,whatever,SYNTHETIC,TESTRECORD"
    p = _write_csv(tmp_path, header, row)
    with pytest.raises(LicensedColumnError, match=licensed):
        list(iter_voters(p))


def test_licensed_and_confidential_lists_are_disjoint() -> None:
    """The two refusal lists must not overlap.

    Confidential = statute. Licensed = vendor contract / privacy
    posture. A column could in principle be on both lists, but if so we
    want the exception message to be unambiguous about which boundary
    tripped. We check confidential first in the reader, so overlap
    would mean licensed-only columns silently get the "confidential"
    label. Keep them disjoint.
    """
    overlap = STATUTORY_CONFIDENTIAL_FIELDS & TARGETSMART_LICENSED_FIELDS
    assert not overlap, f"overlap between refusal lists: {sorted(overlap)}"


def test_licensed_refusal_includes_documented_categories() -> None:
    """Spot-check that the licensed list covers each documented category.

    If someone trims this list too aggressively, the test catches it.
    """
    # Age (DOB leak)
    assert "voterbase_age" in TARGETSMART_LICENSED_FIELDS
    # Multi-sourced demographics
    assert "voterbase_race" in TARGETSMART_LICENSED_FIELDS
    assert "voterbase_gender" in TARGETSMART_LICENSED_FIELDS
    # Modeled scores
    assert "tsmart_partisan_score" in TARGETSMART_LICENSED_FIELDS
    assert "tsmart_midterm_general_turnout_score" in TARGETSMART_LICENSED_FIELDS
    # Geocoded residence
    assert "reg_latitude" in TARGETSMART_LICENSED_FIELDS
    assert "reg_longitude" in TARGETSMART_LICENSED_FIELDS
    # Vendor-cleaned address duplicates
    assert "tsmart_full_address" in TARGETSMART_LICENSED_FIELDS
    # Commercial enrichment flags
    assert "voterbase_phone_presence_flag" in TARGETSMART_LICENSED_FIELDS


# ---------------------------------------------------------------------------
# Boundary #3: unknown columns pass through silently
# ---------------------------------------------------------------------------


def test_reader_ignores_unknown_columns(tmp_path: Path) -> None:
    """Columns the reader doesn't know about are silently dropped."""
    csv_text = dedent(
        """\
        voterbase_id,vf_reg_state,tsmart_first_name,tsmart_last_name,some_future_column
        TS000000001,GA,SYNTHETIC,TESTRECORD,future-value
        """
    )
    p = tmp_path / "future.csv"
    p.write_text(csv_text, encoding="utf-8")
    voters = list(iter_voters(p))
    assert len(voters) == 1
    assert voters[0].first_name == "SYNTHETIC"


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def test_reader_maps_purged_to_cancelled(tmp_path: Path) -> None:
    """TargetSmart's PURGED label maps to the model's CANCELLED status."""
    csv_text = dedent(
        """\
        voterbase_id,tsmart_first_name,tsmart_last_name,vf_voter_status
        TS000000001,SYNTHETIC,TESTRECORD,PURGED
        """
    )
    p = tmp_path / "purged.csv"
    p.write_text(csv_text, encoding="utf-8")
    voter = next(iter_voters(p))
    assert voter.status == VoterStatus.CANCELLED


def test_reader_raises_on_unknown_status_label(tmp_path: Path) -> None:
    """A vf_voter_status value we don't know triggers UnknownStatusLabelError."""
    csv_text = dedent(
        """\
        voterbase_id,tsmart_first_name,tsmart_last_name,vf_voter_status
        TS000000001,SYNTHETIC,TESTRECORD,MARTIAN
        """
    )
    p = tmp_path / "martian.csv"
    p.write_text(csv_text, encoding="utf-8")
    with pytest.raises(TargetSmartFileError):
        list(iter_voters(p))


def test_reader_defaults_blank_status_to_active(tmp_path: Path) -> None:
    """Blank vf_voter_status defaults to ACTIVE, matching the SOS reader."""
    csv_text = dedent(
        """\
        voterbase_id,tsmart_first_name,tsmart_last_name,vf_voter_status
        TS000000001,SYNTHETIC,TESTRECORD,
        """
    )
    p = tmp_path / "blank.csv"
    p.write_text(csv_text, encoding="utf-8")
    voter = next(iter_voters(p))
    assert voter.status == VoterStatus.ACTIVE


# ---------------------------------------------------------------------------
# Address parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("123 MAIN ST", ("123", "MAIN ST")),
        ("4567 IMAGINARY AVE", ("4567", "IMAGINARY AVE")),
        ("MAIN ST", (None, "MAIN ST")),  # no house number
        ("", (None, None)),
        ("   ", (None, None)),
        ("PO BOX 17", (None, "PO BOX 17")),  # first token isn't a digit
    ],
)
def test_split_address1(line: str, expected: tuple[str | None, str | None]) -> None:
    """The address-line splitter handles the cases the dictionary documents."""
    assert _split_address1(line) == expected


# ---------------------------------------------------------------------------
# voterbase_id parsing
# ---------------------------------------------------------------------------


def test_reader_parses_pure_digit_voterbase_id(tmp_path: Path) -> None:
    """An all-digit voterbase_id parses straight to int.

    Future-proofing: if a partner ever ships an all-numeric id, we
    accept it rather than failing.
    """
    csv_text = dedent(
        """\
        voterbase_id,tsmart_first_name,tsmart_last_name
        9000001,SYNTHETIC,TESTRECORD
        """
    )
    p = tmp_path / "digits.csv"
    p.write_text(csv_text, encoding="utf-8")
    voter = next(iter_voters(p))
    assert voter.voter_id == 9_000_001


def test_reader_rejects_garbage_voterbase_id(tmp_path: Path) -> None:
    """A voterbase_id that isn't TS-prefixed digits or pure digits errors out.

    This pins the synthetic-fixture-only contract documented in the
    `_parse_voterbase_id` docstring. If we ever receive a real
    TargetSmart export (32-char hex), this test will fail and force
    the decision to be re-made explicitly.
    """
    csv_text = dedent(
        """\
        voterbase_id,tsmart_first_name,tsmart_last_name
        abc-def-not-a-number,SYNTHETIC,TESTRECORD
        """
    )
    p = tmp_path / "garbage.csv"
    p.write_text(csv_text, encoding="utf-8")
    with pytest.raises(TargetSmartFileError):
        list(iter_voters(p))


# ---------------------------------------------------------------------------
# Header normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("voterbase_id", "voterbase_id"),
        ("VOTERBASE_ID", "voterbase_id"),  # casing change must still match refusal
        ("VF_County_Name", "vf_county_name"),
        ("  voterbase_id  ", "voterbase_id"),
        ("voterbase-id", "voterbase_id"),
    ],
)
def test_header_normalization(raw: str, normalized: str) -> None:
    assert _normalize_header(raw) == normalized


def test_uppercase_licensed_column_still_refused(tmp_path: Path) -> None:
    """A licensed column in upper-case still trips the refusal.

    Belt-and-suspenders: licensed-column refusal must survive casing
    games. Normalization happens before set membership.
    """
    header = "voterbase_id,VOTERBASE_AGE,tsmart_first_name,tsmart_last_name"
    row = "TS000000001,42,SYNTHETIC,TESTRECORD"
    p = _write_csv(tmp_path, header, row)
    with pytest.raises(LicensedColumnError):
        list(iter_voters(p))


# ---------------------------------------------------------------------------
# Empty file handling
# ---------------------------------------------------------------------------


def test_reader_raises_on_headerless_file(tmp_path: Path) -> None:
    """A file with no header row produces a TargetSmartFileError."""
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(TargetSmartFileError):
        list(iter_voters(p))
