"""Canonical models for SEB meeting records.

These Pydantic models are the contract between ingestion (sources) and
the warehouse. Sources produce dicts; transforms produce typed `Meeting`
instances; the warehouse stores their serialized form.

The schema mirrors the columns in the v0 workbook fixture
(`fixtures/seb_meetings_v0.xlsx`) so that the workbook stays a valid
output sink during Phase 1, even after live ingestion lands.

Important: free-text qualitative columns (controversies, compliance
notes, key decisions) are kept as strings on purpose. The pipeline does
NOT attempt to auto-classify them in Phase 1 — that's a human-review
step. See LESSONS.md L08 for the reasoning.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MeetingType(StrEnum):
    """SEB meetings come in a small number of named shapes."""

    REGULAR = "Regular"
    REGULAR_DAY_1 = "Regular (Day 1)"
    REGULAR_DAY_2 = "Regular (Day 2)"
    SPECIAL_CALLED = "Special Called"
    EMERGENCY = "Emergency"
    EXECUTIVE_SESSION = "Executive Session"


class ComplianceStatus(StrEnum):
    """Open Meetings Act compliance posture for a single meeting.

    `Compliant` is the default-positive. `Notice Concerns` flags a meeting
    where notice timing or content was contested. `Other Concerns` covers
    quorum, minutes, or executive-session issues. Sources do not produce
    this; humans set it after review.
    """

    COMPLIANT = "Compliant"
    NOTICE_CONCERNS = "Notice Concerns"
    OTHER_CONCERNS = "Other Concerns"
    UNREVIEWED = "Unreviewed"


class Meeting(BaseModel):
    """One SEB meeting.

    Field naming mirrors the v0 workbook column headers, lowercased and
    snake_cased, so the round-trip to/from the workbook is mechanical.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    meeting_id: int = Field(
        ..., description="Stable ascending integer; assigned by warehouse, not by source."
    )
    meeting_date: date
    day_of_week: str = Field(..., max_length=3, description="Mon / Tue / Wed / ...")
    meeting_type: MeetingType
    meeting_format: str = Field(..., description="In-person + YouTube, Zoom + YouTube, etc.")
    chair: str
    members_present: str = Field(
        ..., description="Free text — comma-separated names with annotations like '(partial)'."
    )
    quorum_met: str = Field(
        ..., description="Free text — 'Yes', 'Yes (3, then 4)', 'No', etc. Not boolean on purpose."
    )
    agenda_summary: str | None = None
    key_decisions: str | None = None
    video_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    compliance_status: ComplianceStatus = ComplianceStatus.UNREVIEWED
    compliance_notes: str | None = None
    controversies: str | None = None
    hours_logged: float | None = Field(default=None, ge=0, le=24)

    def workbook_row(self) -> list[object]:
        """Return values in the v0 workbook column order.

        Used by `outputs/workbook_sync` to write a row back to the human-
        reviewed workbook. Keep in sync with the workbook header row.
        """
        return [
            self.meeting_id,
            self.meeting_date.isoformat(),
            self.day_of_week,
            self.meeting_type.value,
            self.meeting_format,
            self.chair,
            self.members_present,
            self.quorum_met,
            self.agenda_summary or "",
            self.key_decisions or "",
            str(self.video_url) if self.video_url else "",
            str(self.source_url) if self.source_url else "",
            self.compliance_status.value,
            self.compliance_notes or "",
            self.controversies or "",
            self.hours_logged if self.hours_logged is not None else "",
        ]
