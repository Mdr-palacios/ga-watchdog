"""Bulk-export script: publish snapshot artifacts of allow-listed views.

ADR-0005 decision 7: researchers who want full tables do not get them
from the paginated API. They get them from CSV and Parquet artifacts,
regenerated per warehouse build, served from object storage with their
own URL.

This script generates the artifacts from the local warehouse. The CI
job that publishes them to object storage is a separate concern (and
out of scope for this PR; see the README in `outputs/bulk/`).

Every artifact reads from a name in `ALLOWED_PUBLIC_SOURCES`. Same
allow-list, same enforcement: this script is part of the public surface
and the test suite checks it the same way it checks the API routes.

Usage:

    python -m outputs.api.bulk_export --out outputs/bulk/

Produces:

    outputs/bulk/seb_meetings.csv
    outputs/bulk/seb_meetings.parquet
    outputs/bulk/voter_county_registration.csv
    outputs/bulk/voter_county_registration.parquet
    outputs/bulk/seb_voter_overlap.csv
    outputs/bulk/seb_voter_overlap.parquet
    outputs/bulk/MANIFEST.json   (file list, sha256 each, warehouse mtime)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ._allowed_sources import is_allowed
from ._db import connect, warehouse_path

# (allow-listed-source, output-stem). Stems are stable filenames — they
# are part of the public contract, same as route paths.
EXPORTS: list[tuple[str, str]] = [
    ("seb.meetings", "seb_meetings"),
    ("voter.county_registration_summary", "voter_county_registration"),
    ("analytics.seb_voter_overlap", "seb_voter_overlap"),
]


def export(out_dir: Path) -> dict[str, object]:
    """Write all artifacts to `out_dir`, return a manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        artifacts: list[dict[str, object]] = []
        for source, stem in EXPORTS:
            if not is_allowed(source):
                # Defensive: the test suite catches this at PR time, but
                # in case a runtime branch ever sneaks in, refuse to
                # write rather than ship an unauthorized export.
                raise RuntimeError(
                    f"Refusing to export disallowed source: {source!r}. "
                    "Add it to ALLOWED_PUBLIC_SOURCES first."
                )
            csv_path = out_dir / f"{stem}.csv"
            parquet_path = out_dir / f"{stem}.parquet"
            conn.execute(f"COPY (SELECT * FROM {source}) TO '{csv_path}' (FORMAT CSV, HEADER)")
            conn.execute(f"COPY (SELECT * FROM {source}) TO '{parquet_path}' (FORMAT PARQUET)")
            artifacts.append(
                {
                    "source": source,
                    "csv": _sha_record(csv_path),
                    "parquet": _sha_record(parquet_path),
                }
            )
    finally:
        conn.close()

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "warehouse_mtime": datetime.fromtimestamp(
            os.path.getmtime(warehouse_path()), tz=UTC
        ).isoformat(),
        "artifacts": artifacts,
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _sha_record(path: Path) -> dict[str, object]:
    """Return `{filename, bytes, sha256}` for one artifact."""
    data = path.read_bytes()
    return {
        "filename": path.name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("outputs/bulk"), help="Output directory.")
    args = parser.parse_args()
    manifest = export(args.out)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
