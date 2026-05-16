"""YouTube RSS source for the Georgia State Election Board channel.

YouTube exposes a public Atom feed at:

    https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}

…that lists the channel's 15 most-recent uploads. No API key, no quota,
no auth. This is the cheapest, most resilient way to know "did the SEB
post a new meeting recording?" without paying for the YouTube Data API.

Limitations encoded here on purpose (not papered over)
------------------------------------------------------
1. **15-entry ceiling.** The feed never returns older videos. Backfill
   beyond that horizon comes from `workbook_seed.py`. This is a teaching
   moment about why one ingest source is never enough — see LESSONS §2.
2. **Date ≠ meeting date.** A video's `published` timestamp is its
   upload time, which can be hours or days after the actual meeting.
   We store both and trust upload date as a *hint*, never a ground truth.
3. **Title parsing is heuristic.** Channel titles vary in format
   ("State Election Board Meeting: April 15, 2026", "...12.09.25
   Part 2", "Special Called Meeting - May 14, 2026"). The parser
   extracts a best-effort meeting date; non-parseable titles are kept
   with `meeting_date=None` and surfaced for human review.
4. **Schema drift fails loudly.** If YouTube changes the feed
   structure, the XML parser raises — we do not try to recover. Better
   to break the pipeline and ship a fix than silently lose data.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx

# The canonical Georgia State Election Board channel, verified by
# yt-dlp from a workbook-referenced video. If YouTube renames the
# channel this constant gets a new ID and an ADR.
SEB_CHANNEL_ID = "UC3t-f42tkjx9lXejVcWRzrg"
SEB_CHANNEL_HANDLE = "@GAStateElectionBoard"
FEED_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"
_MEDIA_NS = "http://search.yahoo.com/mrss/"

NS = {"a": _ATOM_NS, "yt": _YT_NS, "media": _MEDIA_NS}


@dataclass(frozen=True)
class VideoEntry:
    """One YouTube video as it appears in the RSS feed.

    `meeting_date` is a best-effort parse of the title — None when the
    title format wasn't recognized.
    """

    video_id: str
    title: str
    video_url: str
    published_at: dt.datetime
    meeting_date: dt.date | None
    description: str | None


# ---------------------------------------------------------------------------
# Title → date parsing. Kept as a list of (regex, parser) so we can add
# new shapes without touching the call site.
# ---------------------------------------------------------------------------

_MONTH_RE = (
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "April 15, 2026" / "May 14, 2026" / "Jan 21, 2026"
    (re.compile(rf"({_MONTH_RE})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE), "MDY"),
    # "03.18.26" / "12.09.25"
    (re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2})\b"), "MDY_DOT_SHORT"),
    # "March 18, 2026" stuck inside other text — fallback same as MDY
]


def _parse_title_date(title: str) -> dt.date | None:
    for pattern, kind in _PATTERNS:
        m = pattern.search(title)
        if not m:
            continue
        try:
            if kind == "MDY":
                month_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
                month = _month_num(month_name)
                return dt.date(year, month, day)
            if kind == "MDY_DOT_SHORT":
                month, day, yy = (int(x) for x in m.groups())
                year = 2000 + yy
                return dt.date(year, month, day)
        except (ValueError, KeyError):
            continue
    return None


def _month_num(name: str) -> int:
    name = name.lower()[:3]
    mapping = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    return mapping[name]


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------


def parse_feed(xml_bytes: bytes | str) -> list[VideoEntry]:
    """Parse an Atom feed payload into VideoEntry records.

    Raises `ET.ParseError` on malformed XML. Raises `ValueError` if an
    entry is missing a required element — we'd rather fail than emit
    half-populated records.
    """
    root = ET.fromstring(xml_bytes)

    entries: list[VideoEntry] = []
    for entry_el in root.findall("a:entry", NS):
        video_id_el = entry_el.find("yt:videoId", NS)
        title_el = entry_el.find("a:title", NS)
        published_el = entry_el.find("a:published", NS)
        link_el = entry_el.find("a:link", NS)
        if video_id_el is None or title_el is None or published_el is None:
            raise ValueError(
                "Feed entry missing required element (yt:videoId, title, or published). "
                "If YouTube changed the feed shape, update parse_feed and add an ADR."
            )

        video_id = video_id_el.text or ""
        title = (title_el.text or "").strip()
        published_at = dt.datetime.fromisoformat(published_el.text or "")
        video_url = (
            link_el.attrib.get("href")
            if link_el is not None
            else f"https://www.youtube.com/watch?v={video_id}"
        )
        media_group = entry_el.find("media:group", NS)
        description = None
        if media_group is not None:
            desc_el = media_group.find("media:description", NS)
            if desc_el is not None and desc_el.text:
                description = desc_el.text.strip() or None

        entries.append(
            VideoEntry(
                video_id=video_id,
                title=title,
                video_url=video_url,
                published_at=published_at,
                meeting_date=_parse_title_date(title),
                description=description,
            )
        )
    return entries


def fetch_feed(
    channel_id: str = SEB_CHANNEL_ID,
    *,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> bytes:
    """Fetch the channel's RSS feed bytes. Network call — mocked in tests."""
    url = FEED_URL_TEMPLATE.format(channel_id=channel_id)
    if client is None:
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            return c.get(url).raise_for_status().content
    return client.get(url, timeout=timeout).raise_for_status().content


def fetch_videos(
    channel_id: str = SEB_CHANNEL_ID,
    *,
    client: httpx.Client | None = None,
) -> list[VideoEntry]:
    """End-to-end: fetch the live feed and parse it. The network seam."""
    return parse_feed(fetch_feed(channel_id, client=client))


def parse_fixture(path: Path) -> list[VideoEntry]:
    """Parse a saved feed file. Used by tests and offline reruns."""
    return parse_feed(path.read_bytes())


# ---------------------------------------------------------------------------
# Warehouse projection
# ---------------------------------------------------------------------------


def to_warehouse_rows(entries: list[VideoEntry]) -> list[dict]:
    """Project VideoEntry → dict shaped for `warehouse.loader.upsert_videos`.

    `meeting_id` is left None at this layer. The downstream
    `fill_missing_video_urls_from_rss` step joins videos to meetings by
    date when it can do so unambiguously.
    """
    return [
        {
            "video_id": e.video_id,
            "meeting_id": None,
            "video_url": e.video_url,
            "title": e.title,
            "published_date": e.meeting_date or e.published_at.date(),
            "description": e.description,
        }
        for e in entries
    ]
