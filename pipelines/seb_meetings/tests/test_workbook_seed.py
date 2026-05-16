"""Tests for the workbook seed loader.

These tests are deliberately broad — they're the safety net for the
"workbook is the system of record" invariant. If any of them fails, the
narrative in LESSONS.md §1 is broken and we have to rewrite it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pipelines.seb_meetings.sources import workbook_seed
from pipelines.seb_meetings.transforms.models import ComplianceStatus, MeetingType

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "seb_meetings_v0.xlsx"


def test_fixture_exists():
    assert FIXTURE.exists(), f"v0 workbook missing at {FIXTURE}"


def test_iter_meetings_returns_all_rows():
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    # The workbook records 17 meetings from Feb 2025 → May 2026.
    # If you change this count, change LESSONS.md §1 too.
    assert len(rows) == 17


def test_meeting_ids_are_unique_and_dense():
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    ids = sorted(m.meeting_id for m in rows)
    assert ids == list(range(1, 18)), (
        "meeting_id must be a dense 1..N sequence — gaps would break "
        "the workbook's row numbering on round-trip."
    )


def test_first_meeting_is_may_14_2026():
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    first = rows[0]
    assert first.meeting_id == 1
    assert first.meeting_date == dt.date(2026, 5, 14)
    assert first.meeting_type == MeetingType.SPECIAL_CALLED


def test_video_hyperlinks_are_extracted_not_display_text():
    """The workbook shows 'Watch' as cell text and links to YouTube.

    A naive reader would store the literal string 'Watch'. We must
    extract the hyperlink target instead.
    """
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    with_video = [m for m in rows if m.video_url is not None]
    assert with_video, "expected at least one meeting with a video URL"
    for m in with_video:
        assert str(m.video_url).startswith("http"), (
            f"video_url for meeting {m.meeting_id} looks like display "
            f"text, not a URL: {m.video_url!r}"
        )


def test_compliance_defaults_to_a_known_enum():
    """No row should have a free-text compliance value."""
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    valid = set(ComplianceStatus)
    for m in rows:
        assert m.compliance_status in valid, (
            f"meeting {m.meeting_id} has unknown compliance: {m.compliance_status!r}"
        )


def test_hours_logged_within_bounds():
    """The Pydantic model bounds 0..24 — if any row violates, the loader
    raises and this test never reaches the assertion. This is a smoke
    check that the bound is actually wired."""
    rows = list(workbook_seed.iter_meetings(FIXTURE))
    for m in rows:
        if m.hours_logged is not None:
            assert 0 <= m.hours_logged <= 24


def test_controversies_table_has_eight_rows():
    rows = list(workbook_seed.iter_controversies(FIXTURE))
    assert len(rows) == 8
    assert {r["status"] for r in rows} <= {"Active", "Resolved", "Monitoring"}


def test_sources_table_has_fifteen_rows():
    rows = list(workbook_seed.iter_sources(FIXTURE))
    assert len(rows) == 15
    for r in rows:
        assert r["url"].startswith("http"), (
            f"source {r['source_id']} URL extraction failed: {r['url']!r}"
        )


def test_load_all_returns_all_three_collections():
    payload = workbook_seed.load_all(FIXTURE)
    assert set(payload.keys()) == {"meetings", "controversies", "sources"}
    assert len(payload["meetings"]) == 17
    assert len(payload["controversies"]) == 8
    assert len(payload["sources"]) == 15


def test_loader_is_idempotent_when_called_twice():
    """Reading twice returns equivalent data — no hidden generator state."""
    first = workbook_seed.load_all(FIXTURE)
    second = workbook_seed.load_all(FIXTURE)
    assert len(first["meetings"]) == len(second["meetings"])
    assert [m.meeting_id for m in first["meetings"]] == [m.meeting_id for m in second["meetings"]]


def test_validation_error_message_includes_row_number(tmp_path: Path):
    """Failing rows must surface their row number for course debugging."""
    import openpyxl

    bad_path = tmp_path / "bad.xlsx"
    # Build a minimal corrupted workbook by copying the v0 fixture and
    # poisoning row 6's hours_logged with an out-of-range value.
    wb = openpyxl.load_workbook(FIXTURE)
    ws = wb["Meetings"]
    ws.cell(6, 17).value = 999  # hours_logged > 24
    wb.save(bad_path)

    with pytest.raises(ValueError, match="row 6"):
        list(workbook_seed.iter_meetings(bad_path))
