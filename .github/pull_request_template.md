<!--
Pull request template for ga-watchdog.
Delete sections that don't apply, but please answer everything that does.
-->

## What this PR does

<!-- One paragraph. Plain language. What changes, what stays the same. -->

## Why

<!-- Link to the issue if there is one. If not, explain the motivation. -->

Closes: #
Related: #

## How to verify

<!-- What should the reviewer click, run, or look at?
     Include commands, queries, or screenshots as needed.
     Example:
       1. `pip install -e ".[dev]"`
       2. `pytest pipelines/seb_meetings/tests/test_models.py`
       3. All tests should pass, including the new `test_rejects_unknown_compliance_status`.
-->

## What kind of change is this?

- [ ] Bug fix (no breaking change)
- [ ] New feature (no breaking change)
- [ ] Breaking change (warehouse schema, model field, public API)
- [ ] Documentation / teaching artifact
- [ ] Operational (CI, runbook, scripts)

## Checklist

- [ ] Tests added or updated (or this PR is doc-only)
- [ ] `pytest` passes locally
- [ ] `pre-commit run --all-files` passes locally
- [ ] Touched the warehouse schema? Wrote or updated an ADR.
- [ ] Touched operations? Wrote or updated a runbook.
- [ ] Touched a meaningful design decision? Proposed a lesson in `docs/teaching/LESSONS.md`.
- [ ] No secrets, tokens, or PII in the diff.

## Anything worth calling out

<!-- Trade-offs you made, things you're unsure about, follow-ups you're punting.
     This section is for the reviewer's situational awareness; don't hide concerns. -->
