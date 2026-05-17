"""Prefect flow: voter-file apply-suppressions.

A standalone flow that reads every `suppressions/*.yaml` file and logs
any new suppression requests into the warehouse. This is the audited
write path for "filter this voter from public outputs"; see ADR-0004
Rule 5 and `warehouse/suppressions.py`.

Run order
---------
1. Apply schema (idempotent).
2. Read every YAML file under `suppressions/` and validate structure.
3. Resolve any `supersedes` references against this batch + the DB.
4. INSERT new entries into `voter.suppressions` (idempotent on PK).
5. (Implicit) `voter.active_suppressions` and `voter.public_voters`
   are views, so the moment step 4 lands, every public read picks up
   the filter \u2014 no extra projection step needed.

The flow does NOT touch `voter.voters`. Suppressions are
filter-by-anti-join, not row-rewrite. See `warehouse/suppressions.py`
for the rationale.

Run locally:
    python -m pipelines.voter_file.flows.apply_suppressions
"""

from __future__ import annotations

from pathlib import Path

import structlog
from prefect import flow, get_run_logger, task

from warehouse import loader as warehouse
from warehouse import suppressions as suppressions_module

log = structlog.get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]


@task(name="apply-schema")
def _apply_schema_task(db_path: Path | None) -> list[str]:
    with warehouse.connect(db_path) as conn:
        return warehouse.apply_schema(conn)


@task(name="apply-suppressions")
def _apply_suppressions_task(
    db_path: Path | None,
    *,
    require_voter_exists: bool,
) -> dict[str, int]:
    # Re-read DEFAULT_SUPPRESSIONS_DIR from the module at call time so
    # tests (and any future operator who monkeypatches) get the current
    # value, not the bound default captured at import time.
    return suppressions_module.run(
        db_path=db_path,
        suppressions_dir=suppressions_module.DEFAULT_SUPPRESSIONS_DIR,
        require_voter_exists=require_voter_exists,
    )


@flow(name="voter-file-apply-suppressions")
def voter_file_apply_suppressions(
    db_path: Path | None = None,
    *,
    require_voter_exists: bool = True,
) -> dict[str, object]:
    """Read suppressions/*.yaml and log them into voter.suppressions.

    Returns a small dict for the Prefect run UI / caller inspection:
      - schema_files: list of SQL files applied
      - counts: {logged: int, skipped: int}

    `require_voter_exists` defaults to True; set False only when
    pre-staging filters before the voter file has been loaded (rare
    operator-driven scenario, never the default for scheduled runs).
    """
    prefect_log = get_run_logger()
    prefect_log.info("Applying schema")
    schema_files = _apply_schema_task(db_path)

    prefect_log.info("Reading suppressions YAML and applying")
    counts = _apply_suppressions_task(db_path, require_voter_exists=require_voter_exists)
    prefect_log.info(
        "Suppressions applied: logged=%d skipped=%d",
        counts["logged"],
        counts["skipped"],
    )

    return {
        "schema_files": schema_files,
        "counts": counts,
    }


if __name__ == "__main__":
    voter_file_apply_suppressions()
