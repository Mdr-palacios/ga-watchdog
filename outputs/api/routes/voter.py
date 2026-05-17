"""Voter-aggregate endpoints.

Only one route: county-level registration summaries. Precinct data is
held, not published, per ADR-0004 Rule 4 and ADR-0005 §1.

This module deliberately does not import or reference `voter.voters`,
`voter.suppressions`, `voter.active_suppressions`, or
`voter.precinct_registration_summary`. If it did, the allow-list test
in `tests/test_api_allowed_sources.py` would fail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .._db import connect
from .._pagination import Page, page_params

router = APIRouter(tags=["voter"])

# Source: voter.county_registration_summary  (allow-listed)
# Optional county filter is a SARGable predicate, not a privacy
# boundary — the view is already aggregated.
_COUNTY_LIST_SQL = """
    SELECT
        county,
        status,
        voter_count,
        distinct_zip5_count,
        earliest_birth_year,
        latest_birth_year
    FROM voter.county_registration_summary
    WHERE ($county IS NULL OR county = $county)
    ORDER BY county, status
    LIMIT $limit OFFSET $offset
"""


@router.get("/v1/voter/county-registration")
def list_county_registration(
    page: Page = Depends(page_params),
    county: str | None = Query(
        default=None,
        description="Optional county filter (exact match, case-sensitive).",
        max_length=64,
    ),
) -> dict[str, object]:
    """Return county-level registration aggregates."""
    conn = connect()
    try:
        rows = conn.execute(
            _COUNTY_LIST_SQL,
            {"limit": page.limit, "offset": page.offset, "county": county},
        ).fetchall()
        columns = [d[0] for d in conn.description]
    finally:
        conn.close()
    return {
        "limit": page.limit,
        "offset": page.offset,
        "count": len(rows),
        "filter": {"county": county},
        "results": [dict(zip(columns, row, strict=True)) for row in rows],
    }
