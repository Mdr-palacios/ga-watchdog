"""Tests for the corrections workflow.

A correction is a YAML-authored, audit-logged override of a value the
workbook (or RSS) supplied. These tests pin the contracts that make the
workflow safe enough to be the *only* sanctioned write path on top of
seed data:

  1. YAML structure is validated (missing keys, bad shape, duplicate ids).
  2. Only whitelisted columns can be targeted.
  3. Re-applying the same correction is a no-op (idempotency).
  4. The audit log is append-only — every override leaves a trail.
  5. A revert is itself a new correction, not a delete.
  6. The flow's final step actually rewrites the May 14 video URL.
"""

from __future__ import annotations

import datetime as dt
import textwrap
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
yaml = pytest.importorskip("yaml")

from pipelines.seb_meetings.flows.ingest import ingest_seb_meetings  # noqa: E402
from warehouse import corrections as corrections_module  # noqa: E402
from warehouse import loader as warehouse  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CORRECTIONS_DIR = REPO_ROOT / "corrections"


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    return path


def test_load_corrections_file_parses_a_well_formed_entry(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "ok.yaml",
        """\
        corrections:
          - id: example-1
            meeting_id: 1
            column: video_url
            new_value: https://example.com/v
            reason: testing
            corrected_by: tester
            evidence_url: https://example.com/proof
            corrected_at: 2026-05-16T12:00:00+00:00
        """,
    )
    [c] = corrections_module.load_corrections_file(path)
    assert c.id == "example-1"
    assert c.meeting_id == 1
    assert c.column == "video_url"
    assert c.new_value == "https://example.com/v"
    assert c.corrected_by == "tester"
    assert c.evidence_url == "https://example.com/proof"
    assert c.corrected_at == dt.datetime(2026, 5, 16, 12, 0, tzinfo=dt.UTC)


def test_load_corrections_file_rejects_missing_top_level_key(tmp_path: Path):
    path = _write_yaml(tmp_path / "bad.yaml", "not_corrections: []\n")
    with pytest.raises(ValueError, match="missing top-level 'corrections:'"):
        corrections_module.load_corrections_file(path)


def test_load_corrections_file_rejects_missing_required_fields(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        corrections:
          - id: missing-fields
            meeting_id: 1
            column: video_url
            # reason + corrected_by intentionally missing
        """,
    )
    with pytest.raises(ValueError, match="missing required keys"):
        corrections_module.load_corrections_file(path)


def test_load_corrections_file_rejects_non_whitelisted_column(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        corrections:
          - id: bad-column
            meeting_id: 1
            column: meeting_date   # not in ALLOWED_COLUMNS
            new_value: 2026-05-15
            reason: this should fail
            corrected_by: tester
        """,
    )
    with pytest.raises(ValueError, match="not in the allow-list"):
        corrections_module.load_corrections_file(path)


def test_load_corrections_file_rejects_duplicate_ids_in_same_file(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "dupe.yaml",
        """\
        corrections:
          - id: same-id
            meeting_id: 1
            column: video_url
            new_value: a
            reason: first
            corrected_by: tester
          - id: same-id
            meeting_id: 1
            column: video_url
            new_value: b
            reason: second
            corrected_by: tester
        """,
    )
    with pytest.raises(ValueError, match="duplicate correction id"):
        corrections_module.load_corrections_file(path)


def test_load_all_corrections_rejects_duplicate_ids_across_files(tmp_path: Path):
    _write_yaml(
        tmp_path / "a.yaml",
        """\
        corrections:
          - id: shared
            meeting_id: 1
            column: video_url
            new_value: a
            reason: from a
            corrected_by: tester
        """,
    )
    _write_yaml(
        tmp_path / "b.yaml",
        """\
        corrections:
          - id: shared
            meeting_id: 1
            column: video_url
            new_value: b
            reason: from b
            corrected_by: tester
        """,
    )
    with pytest.raises(ValueError, match="Duplicate correction id across files"):
        corrections_module.load_all_corrections(tmp_path)


def test_load_all_corrections_returns_empty_when_directory_missing(tmp_path: Path):
    assert corrections_module.load_all_corrections(tmp_path / "does-not-exist") == []


# ---------------------------------------------------------------------------
# Apply behavior — idempotency, audit log, allow-list at SQL layer
# ---------------------------------------------------------------------------


def _seed_warehouse(tmp_path: Path) -> Path:
    """Run the seed-only flow against a fresh DB and return its path."""
    db_path = tmp_path / "test.duckdb"
    ingest_seb_meetings(db_path=db_path, skip_network=True)
    return db_path


def test_apply_corrections_overwrites_target_column_and_logs_audit_row(tmp_path: Path):
    db_path = _seed_warehouse(tmp_path)
    correction = corrections_module.Correction(
        id="t-video-url-1",
        meeting_id=1,
        column="video_url",
        new_value="https://www.youtube.com/watch?v=NEWVIDEO",
        reason="test",
        corrected_by="tester",
        evidence_url="https://example.com/evidence",
    )
    with warehouse.connect(db_path) as conn:
        before = conn.execute("SELECT video_url FROM seb.meetings WHERE meeting_id = 1").fetchone()[
            0
        ]
        assert before != correction.new_value

        result = corrections_module.apply_corrections(conn, [correction])
        assert result == {"logged": 1, "applied": 1, "skipped": 0}

        after = conn.execute("SELECT video_url FROM seb.meetings WHERE meeting_id = 1").fetchone()[
            0
        ]
        assert after == correction.new_value

        log = conn.execute(
            "SELECT correction_id, meeting_id, target_column, "
            "       original_value, corrected_value, reason, corrected_by "
            "FROM seb.meeting_corrections WHERE correction_id = ?",
            (correction.id,),
        ).fetchone()
        assert log == (
            "t-video-url-1",
            1,
            "video_url",
            before,
            correction.new_value,
            "test",
            "tester",
        )


def test_apply_corrections_is_idempotent_on_repeat(tmp_path: Path):
    db_path = _seed_warehouse(tmp_path)
    correction = corrections_module.Correction(
        id="t-idempotent",
        meeting_id=1,
        column="video_url",
        new_value="https://example.com/v",
        reason="idempotent test",
        corrected_by="tester",
    )
    with warehouse.connect(db_path) as conn:
        first = corrections_module.apply_corrections(conn, [correction])
        second = corrections_module.apply_corrections(conn, [correction])
        third = corrections_module.apply_corrections(conn, [correction])

        assert first == {"logged": 1, "applied": 1, "skipped": 0}
        assert second == {"logged": 0, "applied": 0, "skipped": 1}
        assert third == {"logged": 0, "applied": 0, "skipped": 1}

        # Exactly one audit row, despite three applies.
        count = conn.execute(
            "SELECT COUNT(*) FROM seb.meeting_corrections WHERE correction_id = ?",
            (correction.id,),
        ).fetchone()[0]
        assert count == 1


def test_apply_corrections_supports_revert_via_superseding_correction(tmp_path: Path):
    """A revert is its own correction with a new id. Audit log keeps both."""
    db_path = _seed_warehouse(tmp_path)
    original_url = None
    with warehouse.connect(db_path) as conn:
        original_url = conn.execute(
            "SELECT video_url FROM seb.meetings WHERE meeting_id = 1"
        ).fetchone()[0]

        first = corrections_module.Correction(
            id="rev-1-override",
            meeting_id=1,
            column="video_url",
            new_value="https://example.com/wrong",
            reason="override",
            corrected_by="tester",
            corrected_at=dt.datetime(2026, 5, 16, 12, 0, tzinfo=dt.UTC),
        )
        revert = corrections_module.Correction(
            id="rev-2-undo",
            meeting_id=1,
            column="video_url",
            new_value=original_url,
            reason="reverts rev-1-override",
            corrected_by="tester",
            corrected_at=dt.datetime(2026, 5, 16, 13, 0, tzinfo=dt.UTC),
        )
        corrections_module.apply_corrections(conn, [first, revert])

        # Final value matches the revert target.
        final = conn.execute("SELECT video_url FROM seb.meetings WHERE meeting_id = 1").fetchone()[
            0
        ]
        assert final == original_url

        # Both audit rows present, in time order. (The seed flow also
        # logs the real May 14 correction against meeting 1; we filter
        # to just the override + revert pair authored above.)
        rows = conn.execute(
            "SELECT correction_id FROM seb.meeting_corrections "
            "WHERE meeting_id = 1 AND correction_id LIKE 'rev-%' "
            "ORDER BY corrected_at"
        ).fetchall()
        assert rows == [("rev-1-override",), ("rev-2-undo",)]


def test_audit_table_check_constraint_blocks_non_whitelisted_column(tmp_path: Path):
    """The SQL CHECK constraint is the second line of defense if Python ever drifts."""
    db_path = _seed_warehouse(tmp_path)
    with warehouse.connect(db_path) as conn, pytest.raises(duckdb.ConstraintException):
        conn.execute(
            "INSERT INTO seb.meeting_corrections "
            "(correction_id, meeting_id, target_column, original_value, "
            " corrected_value, reason, corrected_by) "
            "VALUES ('x', 1, 'meeting_date', 'a', 'b', 'r', 'who')"
        )


def test_apply_corrections_raises_on_unknown_meeting_id(tmp_path: Path):
    db_path = _seed_warehouse(tmp_path)
    correction = corrections_module.Correction(
        id="missing-meeting",
        meeting_id=99999,
        column="video_url",
        new_value="https://example.com/v",
        reason="bad target",
        corrected_by="tester",
    )
    with warehouse.connect(db_path) as conn, pytest.raises(ValueError, match="does not exist"):
        corrections_module.apply_corrections(conn, [correction])


# ---------------------------------------------------------------------------
# Real-file integration — the May 14 video fix
# ---------------------------------------------------------------------------


def test_real_corrections_yaml_parses_cleanly():
    """The committed corrections file must always be syntactically valid.

    Treat this as the syntactic gate: every correction author runs the
    tests, and a malformed YAML fails CI before review even starts.
    """
    rows = corrections_module.load_all_corrections(REAL_CORRECTIONS_DIR)
    assert rows, "corrections/ should ship with at least the May 14 fix"
    ids = [r.id for r in rows]
    assert "meeting-1-may-14-video-url-2026-05-16" in ids


def test_full_flow_rewrites_may_14_video_url(tmp_path: Path):
    """End-to-end: the flow's final correction step must change meeting 1's URL."""
    db_path = tmp_path / "test.duckdb"
    summary = ingest_seb_meetings(db_path=db_path, skip_network=True)

    assert summary["corrections"]["logged"] == 1
    assert summary["corrections"]["applied"] == 1
    assert summary["corrections"]["skipped"] == 0

    with warehouse.connect(db_path) as conn:
        url = conn.execute("SELECT video_url FROM seb.meetings WHERE meeting_id = 1").fetchone()[0]
        assert "uGWdZ-DmGDA" in url, f"expected corrected video id in {url!r}"

        # Audit row exists, with the workbook's wrong URL preserved as original_value.
        original, evidence = conn.execute(
            "SELECT original_value, evidence_url "
            "FROM seb.meeting_corrections "
            "WHERE correction_id = 'meeting-1-may-14-video-url-2026-05-16'"
        ).fetchone()
        assert "h_0CXACXv9A" in (original or "")
        assert evidence and evidence.startswith("https://")


def test_full_flow_is_idempotent_through_corrections(tmp_path: Path):
    db_path = tmp_path / "test.duckdb"
    ingest_seb_meetings(db_path=db_path, skip_network=True)
    summary = ingest_seb_meetings(db_path=db_path, skip_network=True)
    # Second run: every correction already logged.
    assert summary["corrections"]["logged"] == 0
    assert summary["corrections"]["applied"] == 0
    assert summary["corrections"]["skipped"] >= 1
