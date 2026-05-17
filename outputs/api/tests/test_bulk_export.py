"""Bulk-export integration tests.

Exercises the same allow-list path as the API routes do — if the
export script ever tries to dump a non-allow-listed source, both the
runtime guard in `bulk_export.export` and the static test in
`test_api_allowed_sources.py` will fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from outputs.api import bulk_export


def test_export_writes_csv_parquet_and_manifest(tmp_path: Path, warehouse: Path) -> None:
    out_dir = tmp_path / "bulk"
    manifest = bulk_export.export(out_dir)

    expected_files = {
        "seb_meetings.csv",
        "seb_meetings.parquet",
        "voter_county_registration.csv",
        "voter_county_registration.parquet",
        "seb_voter_overlap.csv",
        "seb_voter_overlap.parquet",
        "MANIFEST.json",
    }
    actual = {p.name for p in out_dir.iterdir()}
    assert expected_files <= actual

    assert manifest["generated_at"]
    assert manifest["warehouse_mtime"]
    sources = {a["source"] for a in manifest["artifacts"]}  # type: ignore[index]
    assert sources == {
        "seb.meetings",
        "voter.county_registration_summary",
        "analytics.seb_voter_overlap",
    }


def test_manifest_records_sha256_per_artifact(tmp_path: Path, warehouse: Path) -> None:
    out_dir = tmp_path / "bulk"
    bulk_export.export(out_dir)
    manifest = json.loads((out_dir / "MANIFEST.json").read_text())
    for artifact in manifest["artifacts"]:
        for fmt in ("csv", "parquet"):
            assert "sha256" in artifact[fmt]
            assert "bytes" in artifact[fmt]
            assert "filename" in artifact[fmt]
