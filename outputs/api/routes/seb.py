"""SEB-meeting endpoints.

Two routes:

- `GET /v1/seb/meetings` — paginated list, ordered by meeting_date DESC.
- `GET /v1/seb/meetings/{meeting_id}` — one meeting plus its videos.

Both read exclusively from the SEB schema, which is public-safe by
construction: the pipeline never stores per-voter identifiers in any
seb.* table (see ADR-0004 and the cross-pipeline contract in L09d).

Columns returned mirror the warehouse exactly. We deliberately don't
synthesize fields or rename columns here — the API surface IS the
schema, so downstream consumers can read the schema docs and know what
they'll get.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .._db import connect
from .._pagination import Page, page_params

router = APIRouter(tags=["seb"])

# Source: seb.meetings  (allow-listed)
_MEETINGS_LIST_SQL = """
    SELECT
        meeting_id,
        meeting_date,
        day_of_week,
        meeting_type,
        meeting_format,
        chair,
        members_present,
        quorum_met,
        agenda_summary,
        key_decisions,
        video_url,
        source_url,
        compliance_status,
        compliance_notes,
        controversies,
        hours_logged
    FROM seb.meetings
    ORDER BY meeting_date DESC, meeting_id DESC
    LIMIT $limit OFFSET $offset
"""

# Source: seb.meetings  (allow-listed)
_MEETING_DETAIL_SQL = """
    SELECT
        meeting_id,
        meeting_date,
        day_of_week,
        meeting_type,
        meeting_format,
        chair,
        members_present,
        quorum_met,
        agenda_summary,
        key_decisions,
        video_url,
        source_url,
        compliance_status,
        compliance_notes,
        controversies,
        hours_logged
    FROM seb.meetings
    WHERE meeting_id = $meeting_id
"""

# Source: seb.videos  (allow-listed)
_MEETING_VIDEOS_SQL = """
    SELECT video_id, video_url, title, published_date, description
    FROM seb.videos
    WHERE meeting_id = $meeting_id
    ORDER BY published_date NULLS LAST, video_id
"""


@router.get("/v1/seb/meetings")
def list_meetings(page: Page = Depends(page_params)) -> dict[str, object]:
    """Return one page of SEB meetings, newest first."""
    conn = connect()
    try:
        rows = conn.execute(
            _MEETINGS_LIST_SQL,
            {"limit": page.limit, "offset": page.offset},
        ).fetchall()
        columns = [d[0] for d in conn.description]
    finally:
        conn.close()
    return {
        "limit": page.limit,
        "offset": page.offset,
        "count": len(rows),
        "results": [dict(zip(columns, row, strict=True)) for row in rows],
    }


@router.get("/v1/seb/meetings/{meeting_id}")
def get_meeting(meeting_id: int) -> dict[str, object]:
    """Return one meeting plus its videos.

    Returns 404 if the meeting_id is not present in `seb.meetings`.
    The `meeting_id` is an integer per the warehouse schema; FastAPI's
    path-parameter validation enforces that before the handler runs,
    so non-integer paths return 422.
    """
    conn = connect()
    try:
        meeting_row = conn.execute(_MEETING_DETAIL_SQL, {"meeting_id": meeting_id}).fetchone()
        if meeting_row is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        meeting_cols = [d[0] for d in conn.description]
        meeting = dict(zip(meeting_cols, meeting_row, strict=True))

        videos = conn.execute(_MEETING_VIDEOS_SQL, {"meeting_id": meeting_id}).fetchall()
        video_cols = [d[0] for d in conn.description]
    finally:
        conn.close()

    return {
        "meeting": meeting,
        "videos": [dict(zip(video_cols, v, strict=True)) for v in videos],
    }
