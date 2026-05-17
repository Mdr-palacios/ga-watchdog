# Voter file fixtures

This directory is **intentionally empty** of real voter data, and will remain so.

The SEB pipeline ships its v0 workbook as a fixture because that data is, by construction, a record of public meetings — meeting dates, names of public officials, public agendas. It is appropriate to commit and ship as a test artifact.

A voter file is not that. Even a small slice of real voter records, even with confidential fields stripped, is a slice of identified people who did not consent to being a test fixture for this repo. There are also straightforward practical reasons not to ship one — CI logs are public, mirrors are public, forks are public — but the consent reason is the one that matters.

## What goes here instead

- **Synthetic fixtures only.** When tests need a record-shaped input, they construct one in Python (`Voter(voter_id=999, ...)`) with obviously fake data. The `Voter` model's `extra="forbid"` config makes the synthetic instance a real exercise of the schema; we lose nothing by not having a real file.
- **Format fixtures, not content fixtures.** If we need to test "we correctly read column X from a `\t`-delimited file with these headers," we ship a 50-row file with synthetic names and addresses, demonstrating the format. Not real data.

## Files

- `synthetic_voter_file.csv` — 50 synthetic rows matching the Georgia SOS bulk-file column names (subset). Every name is obviously fake; every `Registration_Number` is in the 9,000,000+ range, well clear of real SOS-issued identifiers. Used by `tests/test_bulk_file.py`.
- `build_synthetic_fixture.py` — the deterministic generator that produced the CSV above. Checked in so anyone can audit (and regenerate) exactly how the synthetic data was constructed: `python3 pipelines/voter_file/fixtures/build_synthetic_fixture.py`.

The full reasoning is in [ADR-0004](../../../docs/adr/0004-voter-file-sources-and-ethics.md).
