"""Tests for the YouTube RSS source.

Uses a saved fixture so tests pass offline. The fixture is a real,
captured payload from the SEB channel feed — refresh it occasionally
but don't let tests depend on the live feed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pipelines.seb_meetings.sources import youtube_rss

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "seb_youtube_rss.xml"


def test_fixture_exists():
    assert FIXTURE.exists()


def test_parse_fixture_yields_fifteen_entries():
    entries = youtube_rss.parse_fixture(FIXTURE)
    # YouTube caps the public Atom feed at 15. If this fails, the cap
    # changed OR the fixture is stale — investigate before "fixing".
    assert len(entries) == 15


def test_every_entry_has_required_fields():
    for entry in youtube_rss.parse_fixture(FIXTURE):
        assert entry.video_id
        assert entry.title
        assert entry.video_url.startswith("https://www.youtube.com/")
        assert isinstance(entry.published_at, dt.datetime)


def test_title_date_parser_handles_known_shapes():
    cases = {
        "State Election Board Meeting:  April 15, 2026": dt.date(2026, 4, 15),
        'Georgia State Election Board "Special Called Meeting":  May 1, 2026': dt.date(2026, 5, 1),
        "State Election Board Meeting: 03.18.26": dt.date(2026, 3, 18),
        "State Election Board Meeting: 12.09.25 Part 2": dt.date(2025, 12, 9),
        'State Election Board "Special Called Meeting" - May 14, 2026': dt.date(2026, 5, 14),
    }
    for title, expected in cases.items():
        assert youtube_rss._parse_title_date(title) == expected, title


def test_unknown_title_yields_none():
    assert youtube_rss._parse_title_date("Random Title No Date Here") is None


def test_to_warehouse_rows_keeps_meeting_id_null():
    entries = youtube_rss.parse_fixture(FIXTURE)
    rows = youtube_rss.to_warehouse_rows(entries)
    assert all(r["meeting_id"] is None for r in rows)
    assert {r["video_id"] for r in rows} == {e.video_id for e in entries}


def test_malformed_feed_raises_loudly():
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        youtube_rss.parse_feed(b"<not><a feed</not>")


def test_missing_required_element_raises():
    """If YouTube drops yt:videoId we want the pipeline to scream."""
    bad_feed = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <entry>
        <title>No videoId here</title>
        <published>2026-01-01T00:00:00+00:00</published>
      </entry>
    </feed>
    """
    with pytest.raises(ValueError, match="missing required element"):
        youtube_rss.parse_feed(bad_feed)
