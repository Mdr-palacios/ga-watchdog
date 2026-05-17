# Voter file pipeline — Phase 2

This directory is the second of the two pipelines defined in [ADR-0001](../../docs/adr/0001-architecture-overview.md). It is **not yet in production** — there is no live ingestion and no real voter data in the repo — but the scaffold, schema, ethics, bulk-file reader, and address composer are in place. The reader is functional today against the synthetic fixture; pointing it at a real SOS-delivered file is an operator action, not a code change.

## Read first

- [ADR-0004 — Voter file: data sources, redaction, and distribution ethics](../../docs/adr/0004-voter-file-sources-and-ethics.md) — the rules of engagement, in long form.
- [LESSONS.md §L09](../../docs/teaching/LESSONS.md) — the corrections workflow (the audit pattern this pipeline extends to suppressions).

## What's here

```
pipelines/voter_file/
├── sources/
│   └── bulk_file.py    ← Reads SOS-format CSV from local disk. Refuses files
│                         with statutorily-confidential columns at header time.
├── transforms/
│   ├── models.py       ← Pydantic Voter model. Confidential fields by statute
│   │                     do not exist here, on purpose.
│   └── address.py      ← Composes/splits residence display lines. Property-tested.
├── flows/              ← Prefect entrypoints (forthcoming: 2.2 suppressions)
├── tests/
│   ├── test_models.py      ← Statute-as-test: confidential fields raise.
│   ├── test_bulk_file.py   ← Reader contract + fixture round-trip.
│   └── test_address.py     ← Hypothesis property tests (see LESSONS §L13).
└── fixtures/
    ├── synthetic_voter_file.csv     ← 50 obviously-synthetic rows, SOS-shaped.
    ├── build_synthetic_fixture.py   ← Deterministic generator for the CSV above.
    └── README.md                    ← Why no real voter data lives here.
```

The warehouse schema for this pipeline lives at [`warehouse/schema/voter.sql`](../../warehouse/schema/voter.sql).

The suppressions surface (any voter or representative can request their record be filtered from public outputs) lives at [`suppressions/voter_file.yaml`](../../suppressions/voter_file.yaml).

## What's deliberately not here

- **No real voter data.** Not in `fixtures/`, not in CI, not in this repo, not anywhere. The operator acquires the file from the Secretary of State, lands it on the production worker's disk under `data/voter_file/` (gitignored), and the pipeline reads it from there. See ADR-0004 Rule 3.
- **No HTTP fetcher.** The pipeline never fetches the file over the network. The acquisition step is the operator's responsibility and stays out of automation. See ADR-0004 Rule 3.
- **No confidential fields.** The `Voter` model does not declare `ssn`, `dl_number`, `email`, `birth_month`, or `birth_day`. Year of birth is the only date component we store. See ADR-0004 Rule 1 + Rule 2.
- **No per-voter output endpoints.** The eventual public surface aggregates upward (precinct, county, turnout-trend). The pipeline knows about individual voters; the public outputs do not. See ADR-0004 Rule 4.

## Phase 2 roadmap

| Step | What lands | Status |
| --- | --- | --- |
| 2.0 — Scaffold | ADR-0004, `Voter` model, `voter.sql`, suppressions skeleton, fixture-only tests | shipped (PR #3) |
| **2.1 — Bulk file reader** | SOS-format CSV reader with statutory-column refusal, property-tested address composer, synthetic fixture | shipped (this PR) |
| 2.2 — Suppressions workflow | Apply-suppressions task in the flow, mirroring the corrections workflow | next |
| 2.3 — Cross-pipeline analytics | SQL joining `seb.meetings` (SEB decisions) to `voter.aggregates` (turnout/registration trends) | |
| 2.4 — Public read API | The output surface from ADR-0001, with ADR-0005 (forthcoming) on the commercial-use prohibition | |
