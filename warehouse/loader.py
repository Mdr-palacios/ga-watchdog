"""DuckDB warehouse loader.

Thin wrapper around `duckdb` that:
1. Opens (or creates) `data/warehouse/ga_watchdog.duckdb`
2. Applies every `.sql` file under `warehouse/schema/` (idempotent)
3. Provides helpers to upsert seed and incremental data with provenance

This is intentionally not dlt. dlt handles the *ingest source → typed
records* leg. Once records are validated, we land them ourselves so that
the SQL is auditable and so that course readers can see every write
plainly. See ADR-0003 §"Where dlt stops and we begin".

Provenance
----------
Every row carries a `source` column ('workbook_v0' or 'youtube_rss').
Re-running the seed loader against a warehouse that already has
workbook rows is a no-op (INSERT OR REPLACE on PK). Re-running the RSS
loader fills in gaps without clobbering workbook-sourced values for the
same meeting — see `upsert_meetings_from_rss` for the precedence rule.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from pipelines.seb_meetings.transforms.models import Meeting

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "warehouse" / "ga_watchdog.duckdb"
SCHEMA_DIR = REPO_ROOT / "warehouse" / "schema"


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a DuckDB connection, ensuring the parent directory exists."""
    target = db_path or DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(target))
    try:
        yield conn
    finally:
        conn.close()


def apply_schema(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Run every `.sql` file under `warehouse/schema/`. Returns filenames applied.

    Files are executed in lexical order. Each file must be idempotent
    (uses `CREATE ... IF NOT EXISTS`).
    """
    applied: list[str] = []
    for sql_path in sorted(SCHEMA_DIR.glob("*.sql")):
        conn.execute(sql_path.read_text())
        applied.append(sql_path.name)
    return applied


# ---------------------------------------------------------------------------
# Seed-loader writes: workbook → seb.meetings / seb.controversies / seb.sources
# ---------------------------------------------------------------------------

_MEETING_COLUMNS = (
    "meeting_id",
    "meeting_date",
    "day_of_week",
    "meeting_type",
    "meeting_format",
    "chair",
    "members_present",
    "quorum_met",
    "agenda_summary",
    "key_decisions",
    "video_url",
    "source_url",
    "compliance_status",
    "compliance_notes",
    "controversies",
    "hours_logged",
    "source",
)


def _meeting_row_tuple(m: Meeting, source: str) -> tuple:
    return (
        m.meeting_id,
        m.meeting_date,
        m.day_of_week,
        m.meeting_type.value,
        m.meeting_format,
        m.chair,
        m.members_present,
        m.quorum_met,
        m.agenda_summary,
        m.key_decisions,
        str(m.video_url) if m.video_url else None,
        str(m.source_url) if m.source_url else None,
        m.compliance_status.value,
        m.compliance_notes,
        m.controversies,
        m.hours_logged,
        source,
    )


def upsert_seed_meetings(
    conn: duckdb.DuckDBPyConnection,
    meetings: Iterable[Meeting],
    *,
    source: str = "workbook_v0",
) -> int:
    """Insert or replace meeting rows, tagged with the given source.

    Returns the number of rows written. INSERT OR REPLACE makes the loader
    safely re-runnable — the workbook is the system of record for these
    rows in Phase 1, so a re-run is allowed to overwrite.
    """
    placeholders = ", ".join(["?"] * len(_MEETING_COLUMNS))
    columns = ", ".join(_MEETING_COLUMNS)
    sql = f"INSERT OR REPLACE INTO seb.meetings ({columns}) VALUES ({placeholders})"
    count = 0
    for m in meetings:
        conn.execute(sql, _meeting_row_tuple(m, source))
        count += 1
    return count


def upsert_controversies(
    conn: duckdb.DuckDBPyConnection,
    rows: Iterable[dict],
) -> int:
    sql = (
        "INSERT OR REPLACE INTO seb.controversies "
        "(controversy_id, title, first_seen_date, status, description, "
        " latest_action, primary_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    count = 0
    for r in rows:
        conn.execute(
            sql,
            (
                r["controversy_id"],
                r["title"],
                r.get("first_seen_date"),
                r["status"],
                r.get("description"),
                r.get("latest_action"),
                r.get("primary_source"),
            ),
        )
        count += 1
    return count


def upsert_sources(
    conn: duckdb.DuckDBPyConnection,
    rows: Iterable[dict],
) -> int:
    sql = (
        "INSERT OR REPLACE INTO seb.sources "
        "(source_id, name, source_type, url, notes) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    count = 0
    for r in rows:
        conn.execute(
            sql,
            (
                r["source_id"],
                r["name"],
                r["source_type"],
                r["url"],
                r.get("notes"),
            ),
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# RSS-loader writes: YouTube → seb.videos (always) + seb.meetings (gap fill)
# ---------------------------------------------------------------------------


def upsert_videos(
    conn: duckdb.DuckDBPyConnection,
    rows: Iterable[dict],
    *,
    source: str = "youtube_rss",  # noqa: ARG001 — used by future provenance column
) -> int:
    """Write video records from the RSS feed. Idempotent on video_id PK."""
    sql = (
        "INSERT OR REPLACE INTO seb.videos "
        "(video_id, meeting_id, video_url, title, published_date, description) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    count = 0
    for r in rows:
        conn.execute(
            sql,
            (
                r["video_id"],
                r.get("meeting_id"),
                r["video_url"],
                r["title"],
                r.get("published_date"),
                r.get("description"),
            ),
        )
        count += 1
    return count


def fill_missing_video_urls_from_rss(
    conn: duckdb.DuckDBPyConnection,
) -> int:
    """For meetings with NULL video_url, populate from seb.videos when there
    is exactly one video for that date.

    Precedence rule (locked here, documented in LESSONS §3):
    - Workbook-sourced meeting rows are NEVER overwritten on a video_url
      that is already populated. The workbook is the human-curated truth.
    - We only FILL meetings where video_url IS NULL.
    - We only fill if exactly one video exists for that meeting date, to
      avoid attaching a Day-1 recording to a Day-2 meeting row.
    """
    sql = """
    WITH date_video AS (
        SELECT v.video_url, v.published_date::DATE AS d
        FROM seb.videos v
        WHERE v.meeting_id IS NULL
        GROUP BY ALL
    ),
    unique_per_day AS (
        SELECT d, ANY_VALUE(video_url) AS video_url
        FROM date_video
        GROUP BY d
        HAVING COUNT(*) = 1
    )
    UPDATE seb.meetings AS m
    SET video_url = u.video_url
    FROM unique_per_day u
    WHERE m.meeting_date = u.d
      AND m.video_url IS NULL;
    """
    cur = conn.execute(sql)
    # DuckDB exposes the affected row count via the cursor's row description
    # only for certain statements; fall back to a follow-up COUNT.
    return cur.fetchone()[0] if cur.description else _count_filled(conn)


def _count_filled(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute("SELECT COUNT(*) FROM seb.meetings WHERE video_url IS NOT NULL").fetchone()[
        0
    ]


# ---------------------------------------------------------------------------
# Convenience read helpers (used by tests and the digest emitter)
# ---------------------------------------------------------------------------


def count_meetings(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute("SELECT COUNT(*) FROM seb.meetings").fetchone()[0]


def count_videos(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute("SELECT COUNT(*) FROM seb.videos").fetchone()[0]


def latest_meeting_date(
    conn: duckdb.DuckDBPyConnection,
) -> dt.date | None:
    row = conn.execute("SELECT MAX(meeting_date) FROM seb.meetings").fetchone()
    return row[0] if row else None
