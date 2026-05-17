# Bulk artifacts

Published snapshots of allow-listed public views. Regenerated per warehouse build.

- `seb_meetings.{csv,parquet}` — full `seb.meetings`.
- `voter_county_registration.{csv,parquet}` — full `voter.county_registration_summary`. County-level only; no precinct data per ADR-0004.
- `seb_voter_overlap.{csv,parquet}` — full `analytics.seb_voter_overlap`.
- `MANIFEST.json` — generated timestamp, warehouse mtime, sha256 of each file.

These files are populated by `python -m outputs.api.bulk_export --out outputs/bulk/`. They are gitignored at runtime; the directory is kept by `.gitkeep`.

Publication to object storage (with versioned, hash-pinned URLs) is a separate CI job, documented when it lands.
