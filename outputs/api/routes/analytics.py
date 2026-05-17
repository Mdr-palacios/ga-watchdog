"""Cross-pipeline analytic endpoints.

One route: the (year, quarter, county) overlap view defined in
`warehouse/queries/seb_voter_overlap.sql`. This is the surface ADR-0001
was written for — it pairs SEB board activity with county registration
shapes, joined on temporal-plus-geographic bins (never on content).
See L09d for the reasoning.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .._db import connect
from .._pagination import Page, page_params

router = APIRouter(tags=["analytics"])

# Source: analytics.seb_voter_overlap  (allow-listed)
_OVERLAP_SQL = """
    SELECT
        year,
        quarter,
        county,
        voter_status,
        voter_count,
        distinct_zip5_count,
        compliance_status,
        meeting_count,
        quorum_met_count,
        controversy_meeting_count
    FROM analytics.seb_voter_overlap
    WHERE ($year IS NULL OR year = $year)
      AND ($county IS NULL OR county = $county)
    ORDER BY year DESC, quarter DESC, county, compliance_status
    LIMIT $limit OFFSET $offset
"""


@router.get("/v1/analytics/seb-voter-overlap")
def seb_voter_overlap(
    page: Page = Depends(page_params),
    year: int | None = Query(default=None, ge=2000, le=2100),
    county: str | None = Query(default=None, max_length=64),
) -> dict[str, object]:
    """Return the cross-pipeline overlap view, newest quarter first."""
    conn = connect()
    try:
        rows = conn.execute(
            _OVERLAP_SQL,
            {
                "limit": page.limit,
                "offset": page.offset,
                "year": year,
                "county": county,
            },
        ).fetchall()
        columns = [d[0] for d in conn.description]
    finally:
        conn.close()
    return {
        "limit": page.limit,
        "offset": page.offset,
        "count": len(rows),
        "filter": {"year": year, "county": county},
        "results": [dict(zip(columns, row, strict=True)) for row in rows],
    }
