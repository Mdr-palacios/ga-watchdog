"""Tests for the SEB Meeting model.

These are contract tests. They guard the boundary between the warehouse
schema (immutable) and the model (mutable). If a test here fails, either
the model changed in a breaking way or the warehouse schema needs to
change to match — and both deserve an ADR.

Worth reading even if you're not modifying the model: the assertions
here document the *invariants* the rest of the pipeline relies on.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from pipelines.seb_meetings.transforms.models import (
    ComplianceStatus,
    Meeting,
    MeetingType,
)


def _example_meeting(**overrides: object) -> Meeting:
    """Build a valid meeting record. Tests override specific fields."""
    base: dict[str, object] = {
        "meeting_id": 1,
        "meeting_date": date(2026, 5, 14),
        "day_of_week": "Thu",
        "meeting_type": MeetingType.SPECIAL_CALLED,
        "meeting_format": "Zoom + YouTube",
        "chair": "Janice Johnston (Vice Chair, Acting)",
        "members_present": "Johnston, Grubbs, King",
        "quorum_met": "Yes (3, then 4)",
        "agenda_summary": "Special called meeting; ED Mills report and three personnel actions.",
        "key_decisions": "Appointed Hope Cohen as Deputy Director (3-0).",
        "video_url": "https://www.youtube.com/watch?v=example",
        "source_url": "https://sos.ga.gov/state-election-board",
        "compliance_status": ComplianceStatus.COMPLIANT,
        "compliance_notes": "Special called notice provided.",
        "controversies": None,
        "hours_logged": 2.5,
    }
    base.update(overrides)
    return Meeting(**base)


class TestMeetingHappyPath:
    """Round-trip and basic-validity checks."""

    def test_builds_from_valid_data(self) -> None:
        meeting = _example_meeting()
        assert meeting.meeting_id == 1
        assert meeting.meeting_type is MeetingType.SPECIAL_CALLED
        assert meeting.compliance_status is ComplianceStatus.COMPLIANT

    def test_workbook_row_has_one_value_per_column(self) -> None:
        """The workbook has 16 columns. The row writer must produce 16 values."""
        row = _example_meeting().workbook_row()
        assert len(row) == 16, "workbook column count drift — update models.workbook_row()"


class TestMeetingValidation:
    """Failure modes — these are the contract."""

    def test_rejects_unknown_meeting_type(self) -> None:
        with pytest.raises(ValidationError):
            _example_meeting(meeting_type="Town Hall")

    def test_rejects_unknown_compliance_status(self) -> None:
        with pytest.raises(ValidationError):
            _example_meeting(compliance_status="Vibes")

    def test_rejects_negative_hours(self) -> None:
        with pytest.raises(ValidationError):
            _example_meeting(hours_logged=-1.0)

    def test_rejects_absurdly_long_meetings(self) -> None:
        """A meeting cannot run more than 24 hours.

        This catches a real failure mode: typo'd hours (e.g. '105' instead of '10.5')
        would otherwise sail through and look like a 4-day meeting.
        """
        with pytest.raises(ValidationError):
            _example_meeting(hours_logged=25.0)

    def test_rejects_extra_fields(self) -> None:
        """The model rejects unknown fields (extra='forbid').

        Reason: schema drift is one of the most common ways pipelines
        silently corrupt downstream data. Better to fail loudly here.
        """
        with pytest.raises(ValidationError):
            Meeting(**_example_meeting().model_dump(), is_secret=True)  # type: ignore[arg-type]


class TestMeetingDefaults:
    """Default values are part of the contract."""

    def test_unreviewed_is_the_default_compliance_status(self) -> None:
        """A pipeline-ingested meeting starts Unreviewed, not Compliant.

        Sources do not get to declare compliance — only human review does.
        See ADR-0004 (forthcoming): why qualitative columns are human-set.
        """
        minimal = Meeting(
            meeting_id=99,
            meeting_date=date(2026, 1, 1),
            day_of_week="Thu",
            meeting_type=MeetingType.REGULAR,
            meeting_format="In-person + YouTube",
            chair="Test Chair",
            members_present="A, B, C",
            quorum_met="Yes",
        )
        assert minimal.compliance_status is ComplianceStatus.UNREVIEWED
