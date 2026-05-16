# ADR-0001 — Architecture overview

**Status:** Accepted
**Date:** 2026-05-16
**Decision owner:** Rosario Palacios

## Context

This repo serves two purposes simultaneously: it is a production civic data tool that the author and coalition partners use, and it is the worked example for a course teaching data engineers about civic data work. Those two purposes don't usually live well together — production systems get optimized for not breaking, teaching artifacts get optimized for being readable. Most repos pick one and lose the other.

Two pipelines are in scope: a GA State Election Board (SEB) meetings watcher, and a GA voter file watcher. Both share a domain (Georgia elections), both deal with unreliable upstream data, and both produce outputs that get consumed by humans making advocacy decisions.

The question this ADR answers: **what's the smallest architecture that lets both pipelines coexist, share what should be shared, stay independent where they should be, and read clearly enough for a course attendee to follow without a guide?**

## Decision

**One repo. Two pipelines. One shared warehouse. Independent sources, independent transforms, intersecting only at the warehouse boundary.**

```
ga-watchdog/
├── pipelines/
│   ├── seb_meetings/         ← Pipeline 1: sources, transforms, flows, tests
│   └── voter_file/           ← Pipeline 2: sources, transforms, flows, tests
├── warehouse/
│   ├── schema/               ← SQL schemas, owned per pipeline by file
│   ├── seeds/                ← Static reference data (FIPS codes, etc.)
│   └── queries/              ← Cross-cutting analytical queries
├── outputs/
│   ├── digests/              ← Markdown meeting digests
│   ├── workbook_sync/        ← Round-trip to the human-reviewed workbook
│   └── api/                  ← Public read API surface
├── docs/
│   ├── adr/                  ← Architecture decision records
│   ├── runbooks/             ← Operational playbooks
│   └── teaching/             ← Roadmap, lessons, course material
└── scripts/                  ← Operator-facing CLI utilities
```

Pipelines never reach into each other's code. They only meet at the warehouse — by SQL JOIN, never by Python import. That's a deliberate boundary: it forces the warehouse schema to be the contract, makes each pipeline replaceable, and lets each pipeline be reasoned about in isolation.

Each pipeline owns its own `sources/`, `transforms/`, `flows/`, `tests/`, and `fixtures/`. Sources do ingestion only (no business logic). Transforms produce typed records and lean on Pydantic for shape validation. Flows are Prefect entrypoints — orchestration, retries, scheduling, observability.

## Alternatives considered

**One pipeline per repo.** Cleaner separation, but loses the cross-pipeline analytics that are the whole point of putting both under one roof. The "what did the board decide, and what changed on the ground after" question doesn't survive a repo boundary.

**One monolithic pipeline.** Conceptually simple, but the two domains have nothing in common at the ingestion layer — SEB is YouTube + PDFs + court filings, voter file is bulk CSV/Excel from a different state agency on a different cadence. A monolith would mean each domain pollutes the other with concerns it doesn't share.

**Microservices / per-pipeline deployments from day one.** Premature. We have one author and one engineer-collaborator. The deployment story can be one Prefect worker reading one repo. If that stops being true, the seam to split is already drawn (the two `pipelines/` subdirectories).

## Consequences

**Positive.** Course attendees can read either pipeline in isolation and understand it. The warehouse is the contract; everything else is replaceable. New pipelines (election results, court filings, anything else) follow the same shape and need no architectural conversation to add.

**Negative.** The shared warehouse is a coupling point. If we get its schema wrong early, both pipelines suffer. Mitigation: warehouse schemas are versioned (see ADR-0002), and changes go through a contract-test gate in CI.

**Operational.** One repo means one CI surface, one issue tracker, one PR review queue. For two engineers, that's an asset. For ten, it would become noisy and we'd split.

## Related

- [ADR-0002 — DuckDB as the warehouse](0002-duckdb-warehouse.md)
- [ADR-0003 — dlt for ingestion, Prefect for orchestration](0003-dlt-and-prefect.md)
