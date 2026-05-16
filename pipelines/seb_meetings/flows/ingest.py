"""Prefect flow: SEB meetings ingestion.

Composes the two sources for Phase 1 — workbook seed and YouTube RSS —
into one orchestrated flow with explicit precedence and clear logs.

Run order matters
-----------------
1. Apply schema (idempotent).
2. Seed from workbook (idempotent; INSERT OR REPLACE on PK).
3. Ingest live YouTube RSS into `seb.videos` (idempotent on video_id).
4. Back-fill `seb.meetings.video_url` from RSS *only when null and
   unambiguous* — workbook-curated URLs are never overwritten.

This order makes the workbook the system of record for what counts as a
"meeting" in Phase 1. YouTube only contributes *videos*, plus opportunistic
gap fills. ADR-0001 documents why.

Run locally:
    python -m pipelines.seb_meetings.flows.ingest
"""

from __future__ import annotations

from pathlib import Path

import structlog
from prefect import flow, get_run_logger, task

from pipelines.seb_meetings.sources import workbook_seed, youtube_rss
from warehouse import corrections as corrections_module
from warehouse import loader as warehouse

log = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "pipelines" / "seb_meetings" / "fixtures" / "seb_meetings_v0.xlsx"


@task(name="apply-schema")
def _apply_schema_task(db_path: Path | None) -> list[str]:
    with warehouse.connect(db_path) as conn:
        return warehouse.apply_schema(conn)


@task(name="seed-from-workbook")
def _seed_from_workbook_task(
    db_path: Path | None,
    workbook_path: Path,
) -> dict[str, int]:
    payload = workbook_seed.load_all(workbook_path)
    with warehouse.connect(db_path) as conn:
        meetings = warehouse.upsert_seed_meetings(conn, payload["meetings"])
        controversies = warehouse.upsert_controversies(conn, payload["controversies"])
        sources = warehouse.upsert_sources(conn, payload["sources"])
    return {
        "meetings": meetings,
        "controversies": controversies,
        "sources": sources,
    }


@task(name="ingest-youtube-rss", retries=3, retry_delay_seconds=30)
def _ingest_youtube_task(db_path: Path | None) -> int:
    entries = youtube_rss.fetch_videos()
    rows = youtube_rss.to_warehouse_rows(entries)
    with warehouse.connect(db_path) as conn:
        return warehouse.upsert_videos(conn, rows)


@task(name="backfill-video-urls")
def _backfill_video_urls_task(db_path: Path | None) -> int:
    with warehouse.connect(db_path) as conn:
        warehouse.fill_missing_video_urls_from_rss(conn)
        return conn.execute(
            "SELECT COUNT(*) FROM seb.meetings WHERE video_url IS NOT NULL"
        ).fetchone()[0]


@task(name="apply-corrections")
def _apply_corrections_task(db_path: Path | None) -> dict[str, int]:
    return corrections_module.run(db_path=db_path)


@flow(name="seb-meetings-ingest", log_prints=True)
def ingest_seb_meetings(
    db_path: Path | None = None,
    workbook_path: Path = DEFAULT_FIXTURE,
    *,
    skip_network: bool = False,
) -> dict[str, int | dict[str, int]]:
    """Ingest SEB meeting data from the workbook seed + YouTube RSS.

    Args:
        db_path: Override the default warehouse location (used by tests).
        workbook_path: Override the v0 workbook path.
        skip_network: If True, skip the YouTube RSS step. Used by tests
            and local smoke runs without internet.

    Returns:
        A dict summarizing what landed.
    """
    prefect_log = get_run_logger()
    prefect_log.info("Applying warehouse schema")
    schema_files = _apply_schema_task(db_path)
    prefect_log.info("Schema files applied: %s", schema_files)

    prefect_log.info("Seeding from workbook: %s", workbook_path)
    seed_counts = _seed_from_workbook_task(db_path, workbook_path)
    prefect_log.info("Seed counts: %s", seed_counts)

    video_count = 0
    meetings_with_video = seed_counts["meetings"]
    if not skip_network:
        prefect_log.info("Ingesting live YouTube RSS")
        video_count = _ingest_youtube_task(db_path)
        prefect_log.info("Videos upserted: %d", video_count)

        prefect_log.info("Back-filling missing video URLs")
        meetings_with_video = _backfill_video_urls_task(db_path)

    prefect_log.info("Applying corrections")
    correction_counts = _apply_corrections_task(db_path)
    prefect_log.info("Correction counts: %s", correction_counts)

    summary: dict[str, int | dict[str, int]] = {
        "schema_files_applied": len(schema_files),
        "seed": seed_counts,
        "videos_upserted": video_count,
        "meetings_with_video_url": meetings_with_video,
        "corrections": correction_counts,
    }
    prefect_log.info("Ingest summary: %s", summary)
    return summary


if __name__ == "__main__":
    ingest_seb_meetings()
