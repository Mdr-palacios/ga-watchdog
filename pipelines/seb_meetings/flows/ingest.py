"""Prefect flow: SEB meetings ingestion.

This flow runs the SEB sources in order, lets each one merge into the
warehouse via dlt, and emits a structured log line summarizing what
landed. Downstream digesting and workbook sync are separate flows.

Phase 1 stub. Wired up but doesn't run real ingestion yet — the
YouTube source is a stub. Useful right now for:
  - validating that Prefect + dlt + DuckDB compose correctly
  - giving CI something to import without crashing
  - giving the course a concrete artifact to look at when explaining
    the difference between orchestration and ingestion

Run locally:
    prefect server start         # in one terminal
    python -m pipelines.seb_meetings.flows.ingest
"""

from __future__ import annotations

from pathlib import Path

import dlt
import structlog
from prefect import flow, get_run_logger

from pipelines.seb_meetings.sources.youtube_rss import seb_youtube_candidates

log = structlog.get_logger(__name__)

WAREHOUSE_PATH = Path("data/warehouse/ga-watchdog.duckdb")


@flow(name="seb-meetings-ingest", log_prints=True)
def ingest_seb_meetings(since: str | None = None) -> dict[str, int]:
    """Ingest SEB meeting signals from all configured sources.

    Args:
        since: Optional ISO date string. Sources that support filtering
            will skip records earlier than this date.

    Returns:
        A dict of `source_name -> rows_loaded` for the run. Empty values
        are not failures — a source can correctly produce zero new rows.
    """
    prefect_log = get_run_logger()
    prefect_log.info("Starting SEB ingestion; warehouse=%s since=%s", WAREHOUSE_PATH, since)

    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)

    pipeline = dlt.pipeline(
        pipeline_name="seb_meetings",
        destination=dlt.destinations.duckdb(str(WAREHOUSE_PATH)),
        dataset_name="seb",
    )

    counts: dict[str, int] = {}

    # YouTube candidates — Phase 1 stub, returns nothing today.
    load_info = pipeline.run(seb_youtube_candidates())
    counts["youtube_candidates"] = sum(
        package.metrics["loaded_rows"]
        for package in load_info.load_packages
        for _ in package.jobs.get("completed_jobs", [])
    ) if load_info.load_packages else 0

    prefect_log.info("SEB ingestion complete: %s", counts)
    return counts


if __name__ == "__main__":
    ingest_seb_meetings()
