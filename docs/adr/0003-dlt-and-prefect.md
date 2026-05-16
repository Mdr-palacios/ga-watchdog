# ADR-0003 — dlt for ingestion, Prefect for orchestration

**Status:** Accepted
**Date:** 2026-05-16
**Decision owner:** Rosario Palacios

## Context

Both pipelines need to do two things that are different in kind:

1. **Ingest** — pull data from a source (YouTube RSS, a SOS website, a downloadable CSV), normalize the shape, land it in the warehouse.
2. **Orchestrate** — schedule the ingestion, retry on failure, observe what happened, alert when something is wrong, run downstream transforms in the right order.

These are different problems. Conflating them with a single tool is a common pattern in this field and a common source of confusion when something breaks — was the failure in the ingestion logic, or in the scheduler? We want them to be different tools so that the answer is obvious from the stack trace.

The hiring posture this repo is partly designed around explicitly names dlt or Sling for loading, and Prefect for orchestration. That's not coincidence — it's the right shape for our scale, and an increasingly common combination in production civic-tech and small-team data work.

## Decision

**dlt for ingestion (loading + normalization). Prefect for orchestration (scheduling + retries + observability).**

```
Source → dlt source → dlt pipeline → DuckDB        ← dlt's job
       Prefect flow ──────────────────────┘         ← Prefect's job
       ↑
       schedules, retries, alerts, logs
```

A dlt **source** is a Python generator that yields records from one upstream system. It declares its schema (or lets dlt infer one), handles incremental loads via cursor fields, and produces a `dlt.pipeline` run when invoked.

A Prefect **flow** is a Python function decorated with `@flow` that runs one or more dlt source pipelines, then runs downstream transforms (SQL or Python). Flows are scheduled via Prefect deployments and run by a Prefect worker process.

The boundary is strict: **dlt code does not schedule itself, and Prefect code does not contain ingestion logic.**

### Why dlt over Sling

Both are good. We pick dlt because:

- dlt is Python-native; sources are testable in plain pytest without spinning up an external process.
- dlt's incremental-load primitives (cursor fields, merge strategies) match the shape of the data we're ingesting better than Sling's bulk-replicate model.
- The course this repo supports needs to teach pipeline *thinking* in code that's readable to a Python audience. dlt's source pattern is the more legible artifact.

We will revisit if Phase 2 (voter file bulk ingestion) makes Sling the better fit for that pipeline specifically. Sling and dlt can coexist; the orchestration layer doesn't care which loader runs.

### Why Prefect over Airflow

- Single-file local dev (`prefect server start`) — Airflow's local dev story has improved but still drags more weight.
- Python-native flow API; no DAG file with a separate import path.
- The work-pool model maps cleanly to "one DuckDB writer at a time" (see ADR-0002).
- Prefect Cloud's free tier covers our scale through Phase 2.

### Why not Dagster

Strong contender. Dagster's asset model is arguably a better fit for the cross-pipeline analytics in Phase 3. We chose Prefect for the smaller mental footprint at Phase 1 and because the JD this repo trains for names Prefect. If Phase 3 cross-pipeline coordination gets gnarly enough, we revisit.

## Alternatives considered

**Just dlt, with cron.** Possible. Loses observability, loses retry policy, loses any notion of "what ran when" beyond log files. We'd reinvent half of Prefect badly within two months.

**Just Prefect, with raw `httpx` / `pandas` ingestion code.** Common in mature codebases. Loses dlt's schema-inference and incremental-load machinery, which are exactly the features that make handling unreliable sources tractable.

**Airbyte / Fivetran / Stitch.** Hosted connectors. Too heavyweight, costly, and not all sources we need are supported. The point of doing the ingestion ourselves *is* the learning — and the political control over how data is shaped.

## Consequences

**Positive.** The boundary between ingestion and orchestration is explicit in the file tree (`sources/` vs. `flows/`), explicit in the test layout, and explicit in the dependency graph. A failure in ingestion shows up in dlt logs; a failure in orchestration shows up in Prefect. The course can teach each layer separately.

**Negative.** Two tools to learn instead of one. We mitigate with a runbook (`docs/runbooks/local-development.md`) and by keeping the surface area minimal — flows are thin wrappers; sources are short generators.

**Negative.** Prefect requires a worker process to run scheduled flows. In dev that's `prefect worker start`; in prod that's a long-running process somewhere. The "somewhere" is intentionally deferred to Phase 2.

## Related

- [ADR-0001 — Architecture overview](0001-architecture-overview.md)
- [ADR-0002 — DuckDB as the warehouse](0002-duckdb-warehouse.md)
