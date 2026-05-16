# Lessons

This file is the course's running notebook. It's organized by lesson, not by chronology — each lesson points at the commits, PRs, files, or runbooks that demonstrate it. As the repo grows, lessons grow with it.

The lessons are deliberately *political* as well as technical. The whole premise of this repo is that data pipeline design encodes political choices — what counts as "clean," whose definitions you encode, who gets surfaced and who gets erased — and that the field rarely says so out loud.

## Lesson index

### Architecture & strategy

- **L01 — Why two pipelines in one repo.** Cross-pipeline analytics are the whole point. → See [`docs/adr/0001-architecture-overview.md`](../adr/0001-architecture-overview.md).
- **L02 — Why DuckDB before Postgres.** Single-file warehouse, embedded, no infra. The right tool *for this stage*, not forever. → [`docs/adr/0002-duckdb-warehouse.md`](../adr/0002-duckdb-warehouse.md).
- **L03 — Why dlt + Prefect (and not Airbyte + Airflow).** Right-sized orchestration; declarative ingestion; minimal infra footprint. → [`docs/adr/0003-dlt-and-prefect.md`](../adr/0003-dlt-and-prefect.md).

### Working with unreliable sources

- *L04 — How to absorb format drift without breaking downstream.* Coming with Phase 1 SEB ingestion.
- *L05 — When to fail loudly vs. quarantine vs. coerce.* Coming with Phase 2 voter file ingestion.
- *L06 — Schema contracts: writing the test you wish the upstream had.* Coming with the first schema contract test.

### Politics inside pipelines

- *L07 — "Clean" is a choice. Whose definition?* Coming with the first compliance-flag transform.
- *L08 — When the qualitative columns matter more than the quantitative ones.* Coming with the controversies model.
- *L09 — Who can pull this data, and what's distribution ethics here?* Coming with the public API surface.

### Operations

- *L10 — Runbooks: writing for the version of you who is woken up at 6am.* Coming with the first runbook.
- *L11 — Observability without an observability platform.* Coming with structured logging conventions.
- *L12 — Project management: why the issue tracker is part of the system.* Ongoing.

### Testing

- *L13 — Property tests over fixture tests where the universe is bigger than your examples.*
- *L14 — Contract tests: protecting downstream from upstream.*
- *L15 — Golden-file tests for transforms that aren't worth re-deriving in test code.*

## How to read this file

If you're taking the course, lessons run in roughly the order they appear above. The lesson index doubles as a table of contents.

If you're contributing to the repo, you don't need to write a lesson with every PR. Lessons emerge from real decisions; if your PR encodes a meaningful one, propose a lesson in the PR description and we'll wire it up.
