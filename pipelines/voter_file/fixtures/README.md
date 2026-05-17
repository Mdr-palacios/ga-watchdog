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
- `synthetic_targetsmart_voter_file.csv` — 50 synthetic rows matching the **TargetSmart** Georgia voter-file column names (a strict subset). Same kind of artifact as the SOS fixture, but shaped for the alternate column convention some partner organizations use. **Every value is synthetic**; voterbase_ids look like `TS009000000`, well clear of real TargetSmart identifiers (which are 32-char hex). Used by `tests/test_targetsmart_format.py`.
- `build_synthetic_targetsmart_fixture.py` — the deterministic generator for the TargetSmart-shaped CSV. Same seed (`20260516`) as the SOS generator so the two fixtures are visually consistent.

## Why a TargetSmart-shaped fixture exists at all

TargetSmart is a commercial voter-file vendor with a license-restricted product. A few civic-tech partners hold licenses and occasionally hand us files in TargetSmart's column layout. We want the pipeline to **read those files when handed to us**, while never ingesting TargetSmart's licensed, modeled, or commercially-enriched columns. So:

- The fixture demonstrates the column **shape** only — names, addresses, county, registration status — all of which map back to information [O.C.G.A. § 21-2-225(b)](../../../docs/adr/0004-voter-file-sources-and-ethics.md) already makes public.
- The reader (`sources/targetsmart_format.py`) **refuses** every TargetSmart-licensed / modeled / enriched column at header time (`LicensedColumnError`), separately from the statutorily-confidential refusal (`ConfidentialColumnError`). The two refusal lists are pinned by parametrized tests.
- Columns explicitly refused include `voterbase_age` (derives from DOB → ADR-0004 Rule 2), `voterbase_race` and `voterbase_gender` (multi-sourced from commercial data — the SOS file's statute-direct versions are fine, the blended versions aren't), `tsmart_partisan_score` and all `tsmart_*_score` models (vendor IP, Democratic-aligned target audience), `reg_latitude`/`reg_longitude` (geocoded residence — privacy intensifier), all `tsmart_*` cleaned-address duplicates (vendor IP via CASS certification), and `voterbase_phone_*` commercial-enrichment flags.

If a partner sends a TargetSmart export with any of those columns, the reader refuses the file at header time and emits an error message instructing the operator to request a clean export with only statutorily-public columns.

The full reasoning is in [ADR-0004](../../../docs/adr/0004-voter-file-sources-and-ethics.md).
