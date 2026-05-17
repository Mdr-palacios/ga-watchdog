"""Tests for the suppressions workflow.

A suppression is a YAML-authored, audit-logged "filter this voter
from public outputs" request. These tests pin the contracts that make
the workflow safe enough to be the *only* sanctioned filter path:

  1. YAML structure is validated (missing keys, bad shape, duplicate
     ids, bad action values, malformed voter_id).
  2. `unsuppress` requires a `supersedes` that resolves (in-batch OR
     in the warehouse from a prior run).
  3. Re-applying the same suppression is a no-op (idempotency).
  4. The audit log is append-only; underlying `voter.voters` rows are
     never UPDATEd.
  5. The `voter.public_voters` view excludes currently-suppressed
     voters and includes previously-unsuppressed ones.
  6. The Prefect flow wires everything together and emits the right
     counts.
  7. The checked-in `suppressions/voter_file.yaml` parses cleanly
     (empty by design; this just guards against later edits breaking
     the schema).
"""

from __future__ import annotations

import datetime as dt
import textwrap
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
yaml = pytest.importorskip("yaml")

from warehouse import loader as warehouse  # noqa: E402
from warehouse import suppressions as suppressions_module  # noqa: E402
from warehouse.suppressions import (  # noqa: E402
    Suppression,
    SuppressionsFileError,
    apply_suppressions,
    load_all_suppressions,
    load_suppressions_file,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_SUPPRESSIONS_DIR = REPO_ROOT / "suppressions"


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body))
    return path


# ---------------------------------------------------------------------------
# YAML parsing — happy path
# ---------------------------------------------------------------------------


def test_load_suppressions_file_parses_a_well_formed_entry(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "ok.yaml",
        """\
        suppressions:
          - id: example-1
            voter_id: 9000001
            action: suppress
            reason: Requested by voter under VA program
            requested_by: rosario
        """,
    )
    [s] = load_suppressions_file(path)
    assert s.id == "example-1"
    assert s.voter_id == 9_000_001
    assert s.action == "suppress"
    assert s.supersedes is None


def test_load_suppressions_file_handles_empty_list(tmp_path: Path):
    """Empty `suppressions: []` is valid \u2014 the checked-in scaffold uses this."""
    path = _write_yaml(tmp_path / "empty.yaml", "suppressions: []\n")
    assert load_suppressions_file(path) == []


def test_load_suppressions_file_accepts_unsuppress_with_supersedes(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "unsuppress.yaml",
        """\
        suppressions:
          - id: example-1-unsuppress
            voter_id: 9000001
            action: unsuppress
            reason: Voter withdrew the request
            requested_by: rosario
            supersedes: example-1
        """,
    )
    [s] = load_suppressions_file(path)
    assert s.action == "unsuppress"
    assert s.supersedes == "example-1"


def test_real_suppressions_yaml_parses() -> None:
    """The checked-in scaffold yaml must round-trip through the loader."""
    rows = load_all_suppressions(REAL_SUPPRESSIONS_DIR)
    assert rows == []  # scaffold ships empty on purpose


# ---------------------------------------------------------------------------
# YAML parsing — error paths
# ---------------------------------------------------------------------------


def test_missing_top_level_key_is_rejected(tmp_path: Path):
    path = _write_yaml(tmp_path / "bad.yaml", "not_suppressions: []\n")
    with pytest.raises(SuppressionsFileError, match="missing top-level"):
        load_suppressions_file(path)


def test_suppressions_must_be_a_list(tmp_path: Path):
    path = _write_yaml(tmp_path / "bad.yaml", "suppressions: not-a-list\n")
    with pytest.raises(SuppressionsFileError, match="must be a list"):
        load_suppressions_file(path)


def test_entry_must_be_a_mapping(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        suppressions:
          - just-a-string
        """,
    )
    with pytest.raises(SuppressionsFileError, match="not a mapping"):
        load_suppressions_file(path)


@pytest.mark.parametrize("missing_key", ["id", "voter_id", "action", "reason", "requested_by"])
def test_missing_required_key_is_rejected(tmp_path: Path, missing_key: str):
    entry = {
        "id": "s1",
        "voter_id": 9000001,
        "action": "suppress",
        "reason": "test",
        "requested_by": "rosario",
    }
    del entry[missing_key]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({"suppressions": [entry]}))
    with pytest.raises(SuppressionsFileError, match=missing_key):
        load_suppressions_file(path)


def test_duplicate_id_in_same_file_is_rejected(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "dup.yaml",
        """\
        suppressions:
          - id: same-id
            voter_id: 9000001
            action: suppress
            reason: r1
            requested_by: rosario
          - id: same-id
            voter_id: 9000002
            action: suppress
            reason: r2
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="duplicate"):
        load_suppressions_file(path)


def test_bad_action_value_is_rejected(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        suppressions:
          - id: s1
            voter_id: 9000001
            action: delete-the-voter
            reason: nope
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="action"):
        load_suppressions_file(path)


def test_unsuppress_without_supersedes_is_rejected(tmp_path: Path):
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        suppressions:
          - id: bogus-unsuppress
            voter_id: 9000001
            action: unsuppress
            reason: vibes
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="supersedes"):
        load_suppressions_file(path)


def test_string_voter_id_is_rejected(tmp_path: Path):
    """voter_id must be an int; a quoted-numeric YAML value is a mistake."""
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        suppressions:
          - id: s1
            voter_id: "9000001"
            action: suppress
            reason: test
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="voter_id"):
        load_suppressions_file(path)


def test_boolean_voter_id_is_rejected(tmp_path: Path):
    """Python booleans subclass int; reject them explicitly so a stray
    `true` in YAML doesn't get cast to voter_id=1.
    """
    path = _write_yaml(
        tmp_path / "bad.yaml",
        """\
        suppressions:
          - id: s1
            voter_id: true
            action: suppress
            reason: test
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="voter_id"):
        load_suppressions_file(path)


# ---------------------------------------------------------------------------
# Cross-file checks
# ---------------------------------------------------------------------------


def test_duplicate_id_across_files_is_rejected(tmp_path: Path):
    _write_yaml(
        tmp_path / "a.yaml",
        """\
        suppressions:
          - id: shared
            voter_id: 9000001
            action: suppress
            reason: a
            requested_by: rosario
        """,
    )
    _write_yaml(
        tmp_path / "b.yaml",
        """\
        suppressions:
          - id: shared
            voter_id: 9000002
            action: suppress
            reason: b
            requested_by: rosario
        """,
    )
    with pytest.raises(SuppressionsFileError, match="Duplicate"):
        load_all_suppressions(tmp_path)


# ---------------------------------------------------------------------------
# Apply against the warehouse
# ---------------------------------------------------------------------------


def _connect_with_schema(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db_path = tmp_path / "ga.duckdb"
    conn = duckdb.connect(str(db_path))
    warehouse.apply_schema(conn)
    return conn


def _insert_test_voter(conn: duckdb.DuckDBPyConnection, voter_id: int) -> None:
    conn.execute(
        "INSERT INTO voter.voters (voter_id, first_name, last_name) "
        "VALUES (?, 'Synthetic', 'TestRecord')",
        (voter_id,),
    )


def test_apply_logs_a_new_suppression(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    counts = apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="Requested by voter",
                requested_by="rosario",
            )
        ],
    )
    assert counts == {"logged": 1, "skipped": 0}

    rows = conn.execute("SELECT suppression_id, action FROM voter.suppressions").fetchall()
    assert rows == [("s1", "suppress")]


def test_apply_is_idempotent(tmp_path: Path):
    """Re-running the same suppression is a no-op."""
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    s = Suppression(
        id="s1",
        voter_id=9_000_001,
        action="suppress",
        reason="test",
        requested_by="rosario",
    )
    apply_suppressions(conn, [s])
    counts = apply_suppressions(conn, [s])
    assert counts == {"logged": 0, "skipped": 1}

    count = conn.execute("SELECT COUNT(*) FROM voter.suppressions").fetchone()[0]
    assert count == 1


def test_apply_rejects_unknown_voter(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    with pytest.raises(SuppressionsFileError, match="does not exist"):
        apply_suppressions(
            conn,
            [
                Suppression(
                    id="s1",
                    voter_id=9_999_999,
                    action="suppress",
                    reason="test",
                    requested_by="rosario",
                )
            ],
        )


def test_apply_supersedes_resolves_in_batch(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="initial",
                requested_by="rosario",
            ),
            Suppression(
                id="s1-undo",
                voter_id=9_000_001,
                action="unsuppress",
                reason="reversed",
                requested_by="rosario",
                supersedes="s1",
            ),
        ],
    )
    rows = conn.execute(
        "SELECT suppression_id, action, supersedes FROM voter.suppressions ORDER BY applied_at"
    ).fetchall()
    assert rows == [("s1", "suppress", None), ("s1-undo", "unsuppress", "s1")]


def test_apply_supersedes_resolves_across_runs(tmp_path: Path):
    """An unsuppress in a second batch can reference a suppression from
    the first batch \u2014 supersedes resolution must consult the DB."""
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="initial",
                requested_by="rosario",
            )
        ],
    )
    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1-undo",
                voter_id=9_000_001,
                action="unsuppress",
                reason="reversed in a later PR",
                requested_by="rosario",
                supersedes="s1",
            )
        ],
    )
    rows = conn.execute(
        "SELECT suppression_id, action FROM voter.suppressions ORDER BY applied_at"
    ).fetchall()
    assert rows == [("s1", "suppress"), ("s1-undo", "unsuppress")]


def test_apply_rejects_unresolved_supersedes(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    with pytest.raises(SuppressionsFileError, match="neither in this YAML batch"):
        apply_suppressions(
            conn,
            [
                Suppression(
                    id="orphan-unsuppress",
                    voter_id=9_000_001,
                    action="unsuppress",
                    reason="references a typo",
                    requested_by="rosario",
                    supersedes="never-existed",
                )
            ],
        )


def test_apply_never_mutates_voter_record(tmp_path: Path):
    """Suppressions are filters, not rewrites. The underlying voter row
    must be byte-identical before and after a suppress.
    """
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)
    before = conn.execute("SELECT * FROM voter.voters WHERE voter_id = 9000001").fetchone()

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="test",
                requested_by="rosario",
            )
        ],
    )
    after = conn.execute("SELECT * FROM voter.voters WHERE voter_id = 9000001").fetchone()
    assert before == after


# ---------------------------------------------------------------------------
# Views: active_suppressions and public_voters
# ---------------------------------------------------------------------------


def test_public_voters_view_excludes_suppressed(tmp_path: Path):
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)
    _insert_test_voter(conn, 9_000_002)

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="test",
                requested_by="rosario",
            )
        ],
    )
    visible = conn.execute("SELECT voter_id FROM voter.public_voters ORDER BY voter_id").fetchall()
    assert visible == [(9_000_002,)]


def test_public_voters_view_includes_unsuppressed_voter(tmp_path: Path):
    """After an unsuppress, the voter re-appears in public_voters.

    This pins the contract that the audit log is the source of truth
    and the view does the filtering \u2014 no separate "active flag" column
    to drift out of sync.
    """
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="initial",
                requested_by="rosario",
                requested_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            )
        ],
    )
    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1-undo",
                voter_id=9_000_001,
                action="unsuppress",
                reason="reversed",
                requested_by="rosario",
                supersedes="s1",
                requested_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            )
        ],
    )

    visible = conn.execute("SELECT voter_id FROM voter.public_voters").fetchall()
    assert visible == [(9_000_001,)]

    active = conn.execute("SELECT voter_id FROM voter.active_suppressions").fetchall()
    assert active == []


def test_audit_log_is_append_only(tmp_path: Path):
    """An unsuppress adds a row; it does NOT delete the original.

    The append-only property is what makes the audit log a contract.
    """
    conn = _connect_with_schema(tmp_path)
    _insert_test_voter(conn, 9_000_001)

    apply_suppressions(
        conn,
        [
            Suppression(
                id="s1",
                voter_id=9_000_001,
                action="suppress",
                reason="initial",
                requested_by="rosario",
            ),
            Suppression(
                id="s1-undo",
                voter_id=9_000_001,
                action="unsuppress",
                reason="reversed",
                requested_by="rosario",
                supersedes="s1",
            ),
        ],
    )
    count = conn.execute("SELECT COUNT(*) FROM voter.suppressions").fetchone()[0]
    assert count == 2  # both rows preserved


# ---------------------------------------------------------------------------
# Flow integration
# ---------------------------------------------------------------------------


def test_flow_runs_against_empty_scaffold(tmp_path: Path):
    """The full flow runs cleanly against the checked-in (empty) YAML."""
    from pipelines.voter_file.flows.apply_suppressions import voter_file_apply_suppressions

    db_path = tmp_path / "ga.duckdb"
    result = voter_file_apply_suppressions(db_path=db_path)
    assert result["counts"] == {"logged": 0, "skipped": 0}
    assert "voter.sql" in result["schema_files"]


def test_flow_applies_supplied_yaml_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The flow honors a directory of YAML files via the module-level constant.

    We monkeypatch DEFAULT_SUPPRESSIONS_DIR for the duration of the test
    so the flow reads from our temp directory.
    """
    from pipelines.voter_file.flows.apply_suppressions import voter_file_apply_suppressions

    # Stage a voter so require_voter_exists check passes.
    db_path = tmp_path / "ga.duckdb"
    with warehouse.connect(db_path) as conn:
        warehouse.apply_schema(conn)
        _insert_test_voter(conn, 9_000_001)

    yaml_dir = tmp_path / "yamls"
    yaml_dir.mkdir()
    _write_yaml(
        yaml_dir / "one.yaml",
        """\
        suppressions:
          - id: flow-s1
            voter_id: 9000001
            action: suppress
            reason: flow test
            requested_by: rosario
        """,
    )
    monkeypatch.setattr(suppressions_module, "DEFAULT_SUPPRESSIONS_DIR", yaml_dir)

    result = voter_file_apply_suppressions(db_path=db_path)
    assert result["counts"] == {"logged": 1, "skipped": 0}
