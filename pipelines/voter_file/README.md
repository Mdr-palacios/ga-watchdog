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
├── flows/
│   └── apply_suppressions.py   ← Prefect flow: read suppressions/*.yaml,
│                                  log into voter.suppressions (audit-only;
│                                  never UPDATEs voter.voters).
├── tests/
│   ├── test_models.py              ← Statute-as-test: confidential fields raise.
│   ├── test_bulk_file.py           ← SOS reader contract + fixture round-trip.
│   ├── test_targetsmart_format.py  ← TargetSmart reader contract; parametrized
│   │                                  refusal over both refusal lists.
│   ├── test_suppressions.py        ← YAML → audit log → public_voters view.
│   └── test_address.py             ← Hypothesis property tests (see LESSONS §L13).
└── fixtures/
    ├── synthetic_voter_file.csv                ← 50 synthetic rows, SOS-shaped.
    ├── build_synthetic_fixture.py              ← Generator for the above.
    ├── synthetic_targetsmart_voter_file.csv    ← 50 synthetic rows, TargetSmart-shaped.
    ├── build_synthetic_targetsmart_fixture.py  ← Generator for the above.
    └── README.md                               ← Why no real voter data lives here.
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
| 2.1 — Bulk file reader (SOS) | SOS-format CSV reader with statutory-column refusal, property-tested address composer, synthetic fixture | shipped (PR #4) |
| 2.1b — TargetSmart-shape reader | Alt-format reader for partner-shared TargetSmart files; public-only subset; licensed-column refusal at header time; synthetic shape-fixture | shipped (PR #5) |
| 2.2 — Suppressions workflow | YAML-authored, audit-logged "filter this voter from public outputs" requests; mirrors the SEB corrections workflow; adds `voter.public_voters` view as the canonical safe surface | shipped (PR #6) |
| **2.3 — Cross-pipeline analytics** | `voter.county_registration_summary` + `voter.precinct_registration_summary` (with N&lt;25 cell suppression); `analytics.seb_voter_overlap` view in `warehouse/queries/` joining SEB meetings to voter aggregates by quarter and county; cross-pipeline files architecturally distinct from per-pipeline schema files | shipped (this PR) |
| 2.4 — Public read API | The output surface from ADR-0001, with ADR-0005 (forthcoming) on the commercial-use prohibition | |

### How the cross-pipeline join works

[`warehouse/queries/seb_voter_overlap.sql`](../../warehouse/queries/seb_voter_overlap.sql) builds the analytic views in the `analytics` schema. Two rules are enforced by both the SQL and the tests:

1. **Aggregates only, never per-voter.** The view reads `voter.county_registration_summary`, which reads `voter.public_voters`, which respects suppressions. No per-voter columns (voter_id, zip5, birth_year, precinct, address parts) reach the cross-pipeline surface. ADR-0004 Rule 4. Pinned by [`test_overlap_view_excludes_per_voter_identifiers`](tests/test_analytics.py).
2. **Temporal + geographic, never topical.** SEB meetings have free-text `key_decisions` / `controversies` columns; the pipeline does not claim to know which county a specific decision affected. The join binds SEB activity by calendar quarter and pairs it with county registration shape. Researchers layer their own topical judgment on top.

Minimum cell size for precinct rollups is 25 voters (cells below threshold return `voter_count = NULL`, `suppressed_for_size = TRUE`). The threshold lives in `warehouse/schema/voter.sql` and is referenced by [`test_precinct_rollup_suppresses_small_cells`](tests/test_analytics.py); changing it requires changing both, which forces an explicit code review of the privacy posture.
