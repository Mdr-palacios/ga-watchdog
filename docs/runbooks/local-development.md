# Runbook: local development

For the version of you (or a course attendee) sitting down to run this repo for the first time.

## Prerequisites

- Python 3.11 or 3.12
- Git
- A terminal where `python --version` returns the above

## Setup

```bash
git clone https://github.com/Mdr-palacios/ga-watchdog.git
cd ga-watchdog
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

## Run the tests

```bash
pytest
```

Expected on a fresh clone: all tests in `pipelines/seb_meetings/tests/test_models.py` pass. Other test files appear as new pipeline work lands.

## Run the (stub) ingestion flow

Phase 1 ingestion is currently a stub — it composes Prefect, dlt, and DuckDB end to end but the YouTube source returns no records. Useful for verifying your install:

```bash
# Terminal 1 — Prefect API
prefect server start

# Terminal 2 — run the flow
python -m pipelines.seb_meetings.flows.ingest
```

Expected: the flow runs cleanly, logs `SEB ingestion complete: {'youtube_candidates': 0}`, and creates `data/warehouse/ga-watchdog.duckdb` (empty).

## Inspect the warehouse

```bash
python -c "import duckdb; print(duckdb.connect('data/warehouse/ga-watchdog.duckdb').sql('SHOW ALL TABLES'))"
```

Or, with the DuckDB CLI installed:

```bash
duckdb data/warehouse/ga-watchdog.duckdb
> SHOW TABLES;
```

## Common issues

**`prefect: command not found`** — your virtualenv isn't activated. `source .venv/bin/activate`.

**`No module named 'pipelines'`** — you're not in the repo root, or you didn't install with `-e`. Re-run `pip install -e ".[dev]"` from the repo root.

**Pre-commit fails on first run** — that's normal; it's applying auto-fixes. Re-stage the modified files and commit again.

**A test marked `network` or `slow` fails** — these are excluded from default runs. Re-check with `pytest -m "not network and not slow"`.

## Wiping local state

```bash
rm -rf data/warehouse/*.duckdb data/warehouse/*.wal .prefect/ .dlt/
```

Safe to do anytime — everything in those directories is regenerable from sources.
