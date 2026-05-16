# Voter file pipeline — Phase 2 (scaffold)

This directory is the second of the two pipelines defined in [ADR-0001](../../docs/adr/0001-architecture-overview.md). It is **scaffold only** at the moment — there is no live ingestion, no real voter data in the repo, and no production deployment. The scaffold pins the schema and the ethics in code before any data flows.

## Read first

- [ADR-0004 — Voter file: data sources, redaction, and distribution ethics](../../docs/adr/0004-voter-file-sources-and-ethics.md) — the rules of engagement, in long form.
- [LESSONS.md §L09](../../docs/teaching/LESSONS.md) — the corrections workflow (the audit pattern this pipeline extends to suppressions).

## What's in the scaffold

```
pipelines/voter_file/
├── sources/        ← Source readers (forthcoming: bulk SOS file reader)
├── transforms/
│   └── models.py   ← Pydantic Voter model. Confidential fields by statute
│                     do not exist here, on purpose.
├── flows/          ← Prefect entrypoints (forthcoming)
├── tests/
│   └── test_models.py   ← Statute-as-test: confidential fields raise.
└── fixtures/
    └── README.md   ← Why this directory stays empty.
```

The warehouse schema for this pipeline lives at [`warehouse/schema/voter.sql`](../../warehouse/schema/voter.sql).

The suppressions surface (any voter or representative can request their record be filtered from public outputs) lives at [`suppressions/voter_file.yaml`](../../suppressions/voter_file.yaml).

## What's deliberately not here

- **No real voter data.** Not in `fixtures/`, not in CI, not in this repo, not anywhere. The operator acquires the file from the Secretary of State, lands it on the production worker's disk under `data/voter_file/` (gitignored), and the pipeline reads it from there. See ADR-0004 Rule 3.
- **No HTTP fetcher.** The pipeline never fetches the file over the network. The acquisition step is the operator's responsibility and stays out of automation. See ADR-0004 Rule 3.
- **No confidential fields.** The `Voter` model does not declare `ssn`, `dl_number`, `email`, `birth_month`, or `birth_day`. Year of birth is the only date component we store. See ADR-0004 Rule 1 + Rule 2.
- **No per-voter output endpoints.** The eventual public surface aggregates upward (precinct, county, turnout-trend). The pipeline knows about individual voters; the public outputs do not. See ADR-0004 Rule 4.

## Phase 2 roadmap

| Step | What lands |
| --- | --- |
| **2.0 — Scaffold (this PR)** | ADR-0004, `Voter` model, `voter.sql`, suppressions skeleton, fixture-only tests |
| 2.1 — Bulk file source | Reader for the SOS-delivered statewide file format. Acquisition stays manual. |
| 2.2 — Suppressions workflow | Apply-suppressions task in the flow, mirroring the corrections workflow |
| 2.3 — Cross-pipeline analytics | SQL joining `seb.meetings` (SEB decisions) to `voter.aggregates` (turnout/registration trends) |
| 2.4 — Public read API | The output surface from ADR-0001, with ADR-0005 (forthcoming) on the commercial-use prohibition |
