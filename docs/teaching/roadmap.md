# Roadmap

This roadmap is honest about what exists, what's next, and what's hypothetical. It updates as the work updates.

## Phase 0 — Scaffolding (current)

**Goal:** A repo a data engineer can clone, install, and read in 30 minutes and understand the *shape* of what's being built before any pipeline runs.

- [x] Repo created, public, MIT-licensed
- [x] Directory layout for two pipelines + shared warehouse
- [x] `pyproject.toml` with pinned dependency floors
- [x] Pre-commit, ruff, pytest, mypy configured
- [x] CI workflow that lints and tests on every PR
- [x] CODEOWNERS + branch protection
- [x] ADR-0001 architecture overview
- [x] ADR-0002 why DuckDB
- [x] ADR-0003 why dlt + Prefect
- [x] Seed fixture: the existing GA SEB Meetings workbook as `pipelines/seb_meetings/fixtures/seb_meetings_v0.xlsx` (truth for the schema until live ingestion replaces it)

## Phase 1 — SEB Meetings Watcher, end to end

**Goal:** A scheduled Prefect flow that detects new SEB meetings, ingests structured metadata, lands a clean record in DuckDB, and emits a markdown digest. Qualitative columns (controversies, compliance notes) remain human-reviewed; the pipeline flags candidates for review rather than auto-filling them.

- [ ] `pipelines/seb_meetings/sources/youtube_rss.py` — dlt source reading the SEB YouTube channel feed
- [ ] `pipelines/seb_meetings/sources/sos_website.py` — dlt source fetching the SOS SEB page (agenda PDFs, minutes)
- [ ] `pipelines/seb_meetings/transforms/normalize.py` — canonical meeting record schema (Pydantic)
- [ ] `pipelines/seb_meetings/flows/ingest.py` — Prefect flow orchestrating sources + transforms
- [ ] `warehouse/schema/seb.sql` — `seb_meetings`, `seb_videos`, `seb_agenda_items` tables in DuckDB
- [ ] `pipelines/seb_meetings/tests/` — schema contract tests, source fixture tests, transform property tests
- [ ] `outputs/digests/` — markdown digest emitter for each new meeting
- [ ] `outputs/workbook_sync/` — round-trip back to the existing workbook schema for human reviewers
- [ ] `docs/runbooks/seb-source-format-drift.md` — what to do when the YouTube feed structure changes or SOS rearranges their page
- [ ] ADR-0004 — How we handle the qualitative-vs-quantitative split (humans approve controversies)

## Phase 2 — Voter File Watcher

**Goal:** Same orchestration, same warehouse, different source domain. Ingests publicly available GA registration aggregates, normalizes format drift between releases, surfaces county/precinct-level signal.

- [ ] Inventory of publicly accessible GA voter data (county registration totals, monthly aggregates, precinct lists where available)
- [ ] ADR — what counts as "public" for this repo's purposes
- [ ] `pipelines/voter_file/sources/` — Sling-based ingestion of bulk files
- [ ] `pipelines/voter_file/transforms/` — schema normalizer that tolerates format drift
- [ ] `warehouse/schema/voter_file.sql` — registration history, change events
- [ ] Anomaly detection SQL: unusual purge activity, unusual registration spikes
- [ ] `outputs/api/` — read-only API surface (FastAPI or Datasette)

## Phase 3 — Cross-pipeline analytics

**Goal:** SQL views and reports that join SEB decisions to voter file changes. "What did the board decide, and what changed on the ground?"

- [ ] `warehouse/queries/board-decisions-vs-registration-change.sql`
- [ ] `warehouse/queries/special-meetings-correlation.sql`
- [ ] Dashboard surface (Evidence or Datasette) that exposes the cross-cuts

## Phase 4 — Public surface

**Goal:** A real consumer surface — not just a warehouse. Whether that's a dashboard, an API, an email digest, or a published dataset depends on what gets used.

- [ ] User interviews with first 3–5 coalition partners
- [ ] Pick surfaces based on those conversations
- [ ] Ship the smallest one that gets clicked

## Non-goals (for now)

- A frontend SPA. The Drawn Together GA site at [`Mdr-palacios/ga-redistricting-hub`](https://github.com/Mdr-palacios/ga-redistricting-hub) is the consumer-facing surface; this repo is its data layer plus a teaching artifact.
- Paid data sources. This repo is public; everything in it must be redistributable.
- A general-purpose election framework. This repo is GA-specific by design. If patterns generalize, they generalize after they work once.
