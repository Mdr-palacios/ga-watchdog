# ga-watchdog

Open civic data pipelines watching Georgia elections.

This repo builds — in public — two production-grade data pipelines that the author and their coalition partners actually use, and uses the repo itself as the curriculum for a course teaching data engineers how to think about pipeline design when the data is political, the sources are unreliable, and the stakes are real people's right to vote.

## What it does

Two pipelines, one shared warehouse.

**Pipeline 1 — GA SEB Meetings Watcher.** Tracks every meeting of the Georgia State Election Board: dates, decisions, compliance with the Open Meetings Act, controversies, and source citations. Ingests SEB YouTube livestreams, the SOS website, court filings, and news coverage. Lands in a queryable warehouse. Outputs a structured workbook, a public meeting digest, and a documented dataset.

**Pipeline 2 — GA Voter File Watcher.** Ingests the statutorily-public Georgia voter registration list (per [O.C.G.A. § 21-2-225](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/)), normalizes format drift between releases, and surfaces signal at county and precinct level: unusual purge activity, registration spikes, where the system is moving and how fast. Confidential fields named in the statute are not ingested, not stored, and not exposed. See [ADR-0004](docs/adr/0004-voter-file-sources-and-ethics.md) for the rules of engagement.

**Cross-pipeline analytics.** The two pipelines share a warehouse on purpose. SEB decisions can be joined to voter file changes: what did the board decide, and what changed on the ground afterward?

## Why it exists

Civic tech tools that actually run in production almost never get written about. The decisions that go into them — what counts as "clean" data, what to do when a source format breaks, how to flag a compliance issue, whose definitions you encode — are the actual work, and they almost never get taught.

This repo is a working tool **and** the worked example. Every meaningful design decision lives in an ADR. Every operational lesson lives in a runbook. The course built on top of this repo points at specific commits, PRs, and decision docs and says "here's why."

## Status

- **Phase 1 — SEB Meetings ingestion: shipped.** Workbook seed + live YouTube RSS, idempotent DuckDB warehouse, 31 tests. See [PR #1](https://github.com/Mdr-palacios/ga-watchdog/pull/1).
- **Phase 1.5 — Corrections workflow: shipped.** YAML-authored, PR-reviewed, audit-logged overrides on top of seed data. See [PR #2](https://github.com/Mdr-palacios/ga-watchdog/pull/2) and [LESSONS §L09](docs/teaching/LESSONS.md).
- **Phase 2 — Voter file pipeline: scaffold + bulk-file reader.** ADR-0004 (statute + ethics), schema, Pydantic model with statutory invariants encoded as tests, plus a [bulk-file reader](pipelines/voter_file/sources/bulk_file.py) that refuses files containing statutorily-confidential columns at header time and a [property-tested address composer](pipelines/voter_file/transforms/address.py). No real voter data lives in this repo — fixture is 50 synthetic rows. See [`pipelines/voter_file/README.md`](pipelines/voter_file/README.md) and [LESSONS §L13](docs/teaching/LESSONS.md).
- Full roadmap: [`docs/teaching/roadmap.md`](docs/teaching/roadmap.md).

## Quickstart

```bash
git clone https://github.com/Mdr-palacios/ga-watchdog.git
cd ga-watchdog
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

[MIT](LICENSE) for the code. Data redistribution follows each source's terms — see [`docs/runbooks/data-licensing.md`](docs/runbooks/data-licensing.md) when it exists.

## Contributing

Issues and PRs welcome. All changes go through PRs reviewed by [@Mdr-palacios](https://github.com/Mdr-palacios). See [`CONTRIBUTING.md`](CONTRIBUTING.md).
