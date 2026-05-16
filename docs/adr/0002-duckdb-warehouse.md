# ADR-0002 — DuckDB as the warehouse

**Status:** Accepted
**Date:** 2026-05-16
**Decision owner:** Rosario Palacios

## Context

Both pipelines need a place to land structured records. That place needs to support:

1. SQL — non-Python collaborators (analysts, organizers with some technical fluency, journalists) need to query it without learning the codebase.
2. JOINs across pipelines — cross-cutting analytics are the whole point of having both pipelines in one repo (see ADR-0001).
3. Fast iteration — early-phase development means lots of schema churn. Migrations should be cheap.
4. No infrastructure — this repo runs from a laptop, a cron-scheduled VM, or a small Prefect worker. We do not have, and do not want yet, a dedicated database server.
5. Portable artifacts — the warehouse file should be cheap to share for debugging, to attach to a bug report, to hand to a collaborator who wants to poke at it locally.
6. Honest about its ceiling — whatever we pick, we should know when it stops being the right answer.

## Decision

**DuckDB. Single-file embedded warehouse. One `.duckdb` file per environment (dev, prod), kept out of git, regenerable from sources.**

```
data/warehouse/
├── .gitkeep
└── ga-watchdog.duckdb        # gitignored; regenerable
```

Schemas live in `warehouse/schema/*.sql`. Each file is namespaced by pipeline (`seb.sql`, `voter_file.sql`) plus a shared `reference.sql` for FIPS codes, county metadata, etc. Schemas are applied idempotently at flow startup; the source of truth is the SQL file, not the database state.

dlt writes to DuckDB natively. Prefect doesn't need to know about the database — flows depend on dlt and on raw SQL execution.

## Alternatives considered

**Postgres (self-hosted or managed).** The honest long-term answer for production at any real scale. Rejected for now because: it requires infrastructure we don't have, it slows iteration speed during the schema-churn phase, and the only thing DuckDB can't do that Postgres can — concurrent writes from multiple producers, network access from non-co-located consumers — isn't a constraint we're hitting yet. The migration path is intentionally short: DuckDB and Postgres share enough SQL surface area that schemas port cleanly, and dlt supports both as destinations with a single configuration change.

**SQLite.** Considered. Adequate for storage, weaker for the analytical SQL we want to write. DuckDB's window functions, columnar storage, and PostgreSQL-compatible syntax make it the better fit for the same operational profile.

**Parquet on local disk + DuckDB for querying.** A real option, and one we may move to *under* DuckDB later (DuckDB queries Parquet natively). For now, having tables managed by the database simplifies the mental model: one place to look, one transaction boundary.

**BigQuery / Snowflake / Redshift.** Overkill, costly, and adds an infrastructure dependency that conflicts with the "this repo runs from a laptop" constraint. Revisit if the project ever has paid infrastructure and multiple concurrent producers.

## Consequences

**Positive.** Zero infrastructure to stand up. Schemas iterate fast. The warehouse file can be attached to a GitHub issue when debugging. dlt + DuckDB is a heavily-trodden path with good error messages and good docs.

**Negative.** No concurrent writers. Means: only one Prefect flow run at a time can mutate the database. We enforce this with Prefect work-pool concurrency limits, not at the database level. If we ever need multiple concurrent producers, this becomes the day we move to Postgres.

**Negative.** Network access from outside the worker is awkward. If a downstream consumer (a dashboard, an API) needs to query the warehouse, it needs to be co-located with the file. We mitigate by having the API surface (see Phase 4) be a process that lives next to the file, not by exposing the database over a network.

**Negative.** No row-level security, no per-user access control. Mitigation: the warehouse is not a multi-tenant system. It's a single-tenant analytical store, and the principle is that anyone who has the file has all of it.

## Migration trigger

We will move off DuckDB when **any one of** these becomes true:

1. We need more than one concurrent producer writing to the warehouse.
2. A downstream consumer can't be co-located with the warehouse file.
3. The warehouse exceeds ~100GB (DuckDB handles this size, but operationally it stops being a good fit for the "attach to a bug report" use case).
4. We need row-level access control — e.g., partner orgs sharing data they can see but each other can't.

When any of these triggers fires, the migration target is Postgres, and the migration path is dlt destination config + a one-shot data export. We do not need to commit to that path now.

## Related

- [ADR-0001 — Architecture overview](0001-architecture-overview.md)
- [ADR-0003 — dlt for ingestion, Prefect for orchestration](0003-dlt-and-prefect.md)
