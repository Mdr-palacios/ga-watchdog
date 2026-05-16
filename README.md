# ga-watchdog

Open civic data pipelines watching Georgia elections.

This repo builds — in public — two production-grade data pipelines that the author and their coalition partners actually use, and uses the repo itself as the curriculum for a course teaching data engineers how to think about pipeline design when the data is political, the sources are unreliable, and the stakes are real people's right to vote.

## What it does

Two pipelines, one shared warehouse.

**Pipeline 1 — GA SEB Meetings Watcher.** Tracks every meeting of the Georgia State Election Board: dates, decisions, compliance with the Open Meetings Act, controversies, and source citations. Ingests SEB YouTube livestreams, the SOS website, court filings, and news coverage. Lands in a queryable warehouse. Outputs a structured workbook, a public meeting digest, and a documented dataset.

**Pipeline 2 — GA Voter File Watcher.** Ingests publicly available GA voter registration data (county- and precinct-level aggregates), normalizes the format drift between releases, and surfaces signal: which counties had unusual purge activity, which precincts saw registration spikes, where the system is moving and how fast.

**Cross-pipeline analytics.** The two pipelines share a warehouse on purpose. SEB decisions can be joined to voter file changes: what did the board decide, and what changed on the ground afterward?

## Why it exists

Civic tech tools that actually run in production almost never get written about. The decisions that go into them — what counts as "clean" data, what to do when a source format breaks, how to flag a compliance issue, whose definitions you encode — are the actual work, and they almost never get taught.

This repo is a working tool **and** the worked example. Every meaningful design decision lives in an ADR. Every operational lesson lives in a runbook. The course built on top of this repo points at specific commits, PRs, and decision docs and says "here's why."

## Status

Phase 0. Scaffolding only. See [`docs/teaching/roadmap.md`](docs/teaching/roadmap.md) for what's planned.

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
