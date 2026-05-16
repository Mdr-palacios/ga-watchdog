"""Source: SEB YouTube channel RSS feed.

Phase 1, step 1. The cheapest signal that a new SEB meeting happened
is a new video on the official channel. We read the channel's RSS feed,
filter for entries that look like meeting recordings (vs. PSAs, ads,
or random uploads), and yield one record per candidate meeting.

The record is intentionally minimal at this stage: we only know what
the RSS feed tells us. Other sources (the SOS website, the official
meeting agenda PDFs, official minutes) enrich the same meeting later
in the pipeline.

Status: stub. Returns no records. Real implementation comes in the
'feat/seb-youtube-source' PR. Tests against this stub use the fixture
data in `pipelines/seb_meetings/fixtures/`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import TypedDict

import dlt

# The official SEB YouTube channel handle. Sourced from the v0 workbook
# Sources sheet. Update only via PR with an ADR if this ever changes.
SEB_YOUTUBE_CHANNEL = "https://www.youtube.com/@georgiastateelectionboard"


class YouTubeMeetingCandidate(TypedDict):
    """A row produced by this source.

    Deliberately narrow. Enrichment happens downstream. The only fields
    the YouTube feed can authoritatively provide are the ones below.
    """

    video_id: str
    video_url: str
    title: str
    published_date: date
    description: str


@dlt.resource(  # type: ignore[misc]
    name="seb_youtube_candidates",
    primary_key="video_id",
    write_disposition="merge",
)
def seb_youtube_candidates(
    channel_url: str = SEB_YOUTUBE_CHANNEL,
    since: date | None = None,
) -> Iterator[YouTubeMeetingCandidate]:
    """Yield candidate meeting videos from the SEB YouTube channel.

    Phase 1 stub. Yields nothing.

    Args:
        channel_url: Channel URL. Default points at the official SEB channel.
        since: Optional cutoff — only yield videos published on or after this date.

    Yields:
        YouTubeMeetingCandidate dicts.
    """
    # TODO(seb_youtube_source): implement RSS fetch + filtering.
    # Tracking: https://github.com/Mdr-palacios/ga-watchdog/issues (open the issue
    # before starting the PR).
    if False:  # pragma: no cover — placeholder for type-check parity with real generator
        yield {
            "video_id": "",
            "video_url": "",
            "title": "",
            "published_date": date.today(),
            "description": "",
        }
    return
