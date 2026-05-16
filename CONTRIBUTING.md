# Contributing

This repo is built in public on purpose. PRs and issues are welcome.

## Workflow

1. Open an issue describing the change you want to make (skip this only for typos and obvious doc fixes).
2. Fork or, if you're a collaborator, create a feature branch off `main`. Use a descriptive name: `feat/seb-youtube-source`, `fix/voter-file-encoding`, `docs/adr-0004-prefect-blocks`.
3. Make your change. Keep PRs small — one logical change per PR.
4. Run `pre-commit run --all-files` and `pytest` locally before pushing.
5. Open a PR. Fill out the PR template (it's there for a reason).
6. PRs require **1 approving review** from [@Mdr-palacios](https://github.com/Mdr-palacios) and **all conversations resolved** before merge.
7. CI must pass.

## What goes in a good PR description

- **What** changed — one paragraph
- **Why** — link to the issue, or explain the motivation if no issue exists
- **How to verify** — what should the reviewer click, run, or look at?
- **Anything controversial** — call it out explicitly. If a design decision deserves an ADR, write one in the same PR.

## ADRs (Architecture Decision Records)

We document meaningful technical decisions in [`docs/adr/`](docs/adr/). If your PR introduces a new tool, a new pattern, a schema change, or a choice you'd want to explain to a future maintainer — write an ADR. Format: see [`docs/adr/0001-architecture-overview.md`](docs/adr/0001-architecture-overview.md).

## Runbooks

If your PR changes how something gets operated (a new pipeline, a new failure mode, a new manual step), update or write a runbook in [`docs/runbooks/`](docs/runbooks/).

## Tests

Every pipeline change needs a test. Schema changes get a contract test. Transform changes get a property test or a fixture-based test. The CI workflow runs `pytest` on every PR.

## Data sources

This repo uses **publicly available data only**. If you want to add a source that has access restrictions, distribution terms, or costs, open an issue first — we'll discuss whether and how it fits.

## Conduct

Be the colleague you wish you had. The work this repo supports is contested politically; the standard of care in this repo is high. Disagreement on design is welcome; disrespect is not.
