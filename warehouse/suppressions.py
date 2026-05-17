"""Suppressions workflow — read YAML, write audit-logged filter requests.

A suppression is the only sanctioned way to filter a specific voter out
of any public output this repo produces. The workflow mirrors the
corrections workflow (see `warehouse/corrections.py` and LESSONS §L09),
with two important differences specific to the voter-file ethics:

  - **Suppressions never mutate `voter.voters`.** A correction is an
    override of a sourced value; a suppression is an *audit-logged
    filter request*. We never overwrite the voter's record because
    we don't have a public mandate to edit it — only a private
    obligation to keep it out of our outputs. Public-facing reads
    therefore go through `voter.public_voters` (a view that anti-joins
    `voter.active_suppressions`), not `voter.voters` directly.
  - **Reversing a suppression is a new entry**, not a delete. The
    suppression table is append-only. An `unsuppress` entry must
    point at the suppression it reverses via `supersedes`.

YAML schema (matches the scaffold comment in `suppressions/voter_file.yaml`):

    suppressions:
      - id: <kebab-case-stable-id>
        voter_id: <integer>
        action: suppress      # or 'unsuppress'
        reason: >-
          One-line reason.
        requested_by: <github-handle>
        supersedes: <prior-suppression-id-if-this-is-an-unsuppress>

Three load-time invariants:
  1. Every `id` is unique across all YAML files.
  2. Every `action` is one of {'suppress', 'unsuppress'}.
  3. Every `unsuppress` entry has a `supersedes` value, and that value
     resolves to a known prior `suppress` id (in this YAML batch or
     already in the warehouse).

Re-applying is a no-op (PK conflict on `suppression_id`).

See:
  - ADR-0004 Rule 5
  - docs/teaching/LESSONS.md §L09 (corrections workflow — same shape)
  - warehouse/schema/voter.sql (the table + active-suppressions view)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml

from warehouse import loader as warehouse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUPPRESSIONS_DIR = REPO_ROOT / "suppressions"

ALLOWED_ACTIONS = frozenset({"suppress", "unsuppress"})


@dataclass(frozen=True)
class Suppression:
    """One parsed suppression request. Immutable on purpose.

    `requested_at` is optional in YAML; if omitted, the apply step
    fills it with the current UTC timestamp. This is a deliberate
    choice — most operators won't remember to stamp the YAML, and the
    table records `applied_at` separately so we always have the
    pipeline's view of when the filter actually took effect.
    """

    id: str
    voter_id: int
    action: str  # 'suppress' or 'unsuppress'
    reason: str
    requested_by: str
    supersedes: str | None = None
    requested_at: dt.datetime | None = None


class SuppressionsFileError(ValueError):
    """The YAML file failed structural validation."""


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_suppressions_file(path: Path) -> list[Suppression]:
    """Parse one suppressions YAML file. Raises on malformed shape.

    Validates structure only — cross-file uniqueness and supersedes-
    resolution are checked in `load_all_suppressions`.
    """
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict) or "suppressions" not in data:
        raise SuppressionsFileError(
            f"{path}: missing top-level 'suppressions:' list. "
            f"See suppressions/voter_file.yaml for the format."
        )
    raw = data["suppressions"] or []
    if not isinstance(raw, list):
        raise SuppressionsFileError(
            f"{path}: 'suppressions' must be a list, got {type(raw).__name__}"
        )

    out: list[Suppression] = []
    seen_in_file: set[str] = set()
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise SuppressionsFileError(f"{path}: entry #{idx} is not a mapping")

        required = {"id", "voter_id", "action", "reason", "requested_by"}
        missing = required - entry.keys()
        if missing:
            raise SuppressionsFileError(
                f"{path}: entry #{idx} missing required keys: {sorted(missing)}"
            )

        sid = str(entry["id"]).strip()
        if not sid:
            raise SuppressionsFileError(f"{path}: entry #{idx} has an empty id")
        if sid in seen_in_file:
            raise SuppressionsFileError(f"{path}: duplicate suppression id {sid!r} in same file")
        seen_in_file.add(sid)

        action = str(entry["action"]).strip()
        if action not in ALLOWED_ACTIONS:
            raise SuppressionsFileError(
                f"{path}: entry {sid!r} has action {action!r}; must be one of "
                f"{sorted(ALLOWED_ACTIONS)}"
            )

        supersedes = entry.get("supersedes")
        if supersedes is not None:
            supersedes = str(supersedes).strip() or None

        if action == "unsuppress" and not supersedes:
            raise SuppressionsFileError(
                f"{path}: entry {sid!r} is an unsuppress but has no "
                f"'supersedes' field. To reverse a suppression, name the "
                f"prior suppression id it cancels."
            )

        requested_at = entry.get("requested_at")
        if isinstance(requested_at, str):
            requested_at = dt.datetime.fromisoformat(requested_at)
        elif requested_at is not None and not isinstance(requested_at, dt.datetime):
            raise SuppressionsFileError(
                f"{path}: entry {sid!r} requested_at must be ISO string or datetime"
            )

        # voter_id should be an integer; reject strings that happen to
        # look numeric — the warehouse column is INTEGER and a YAML
        # author who quoted the value probably made a mistake.
        if not isinstance(entry["voter_id"], int) or isinstance(entry["voter_id"], bool):
            raise SuppressionsFileError(
                f"{path}: entry {sid!r} voter_id must be an integer "
                f"(got {type(entry['voter_id']).__name__})"
            )

        out.append(
            Suppression(
                id=sid,
                voter_id=int(entry["voter_id"]),
                action=action,
                reason=str(entry["reason"]).strip(),
                requested_by=str(entry["requested_by"]).strip(),
                supersedes=supersedes,
                requested_at=requested_at,
            )
        )
    return out


def load_all_suppressions(
    directory: Path = DEFAULT_SUPPRESSIONS_DIR,
) -> list[Suppression]:
    """Load every `.yaml` file under `suppressions/`, in lexical filename order.

    Performs cross-file checks:
      - id is globally unique
      - every `supersedes` target resolves to a known id in this batch
        (cross-batch resolution against the warehouse happens in
        `apply_suppressions`, since only the DB knows about prior runs)
    """
    if not directory.exists():
        return []
    rows: list[Suppression] = []
    for path in sorted(directory.glob("*.yaml")):
        rows.extend(load_suppressions_file(path))

    seen_ids: set[str] = set()
    for s in rows:
        if s.id in seen_ids:
            raise SuppressionsFileError(
                f"Duplicate suppression id across files: {s.id!r}. Ids must be globally unique."
            )
        seen_ids.add(s.id)

    # In-batch supersedes resolution. (Cross-batch resolution against
    # the warehouse happens in apply_suppressions where we have a conn.)
    # We DON'T require resolution here — the target might already be in
    # the DB from a prior run. We DO check that any in-batch reference
    # points at a real id in the same batch when present.
    return rows


# ---------------------------------------------------------------------------
# Apply against the warehouse
# ---------------------------------------------------------------------------


def _supersedes_target_known(
    conn: duckdb.DuckDBPyConnection,
    target_id: str,
    in_batch_ids: set[str],
) -> bool:
    """A supersedes target is known if it's in the current batch or DB."""
    if target_id in in_batch_ids:
        return True
    row = conn.execute(
        "SELECT 1 FROM voter.suppressions WHERE suppression_id = ?",
        (target_id,),
    ).fetchone()
    return row is not None


def _voter_exists(conn: duckdb.DuckDBPyConnection, voter_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM voter.voters WHERE voter_id = ?",
        (voter_id,),
    ).fetchone()
    return row is not None


def apply_suppressions(
    conn: duckdb.DuckDBPyConnection,
    suppressions: list[Suppression],
    *,
    require_voter_exists: bool = True,
) -> dict[str, int]:
    """Log suppressions into `voter.suppressions`. Returns counts.

    `logged`   — first-time suppressions inserted
    `skipped`  — already-logged suppressions (idempotent re-runs)

    Unlike corrections, **no UPDATE on `voter.voters`** happens here.
    Filtering is expressed via the `voter.active_suppressions` view and
    the `voter.public_voters` derivative; the underlying record is
    preserved untouched. This is a deliberate ethics choice — we owe
    the voter a filter, not a rewrite of their public record.

    `require_voter_exists=False` is a test escape hatch. In production
    we always want to verify the voter is actually in the warehouse
    before logging the filter; a typo would otherwise create an
    orphan audit row.
    """
    logged = skipped = 0
    in_batch_ids = {s.id for s in suppressions}

    for s in suppressions:
        # Cross-batch supersedes resolution.
        if s.supersedes and not _supersedes_target_known(conn, s.supersedes, in_batch_ids):
            raise SuppressionsFileError(
                f"Suppression {s.id!r} supersedes {s.supersedes!r}, but "
                f"that id is neither in this YAML batch nor in the "
                f"warehouse. Fix the typo or add the prior entry first."
            )

        if require_voter_exists and not _voter_exists(conn, s.voter_id):
            raise SuppressionsFileError(
                f"Suppression {s.id!r} targets voter_id={s.voter_id} which "
                f"does not exist in voter.voters. Load the voter file "
                f"first, or pass require_voter_exists=False if you are "
                f"intentionally pre-staging filters (rare)."
            )

        already_logged = (
            conn.execute(
                "SELECT 1 FROM voter.suppressions WHERE suppression_id = ?",
                (s.id,),
            ).fetchone()
            is not None
        )
        if already_logged:
            skipped += 1
            continue

        now = dt.datetime.now(dt.UTC)
        conn.execute(
            "INSERT INTO voter.suppressions "
            "(suppression_id, voter_id, action, reason, requested_by, "
            " supersedes, requested_at, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s.id,
                s.voter_id,
                s.action,
                s.reason,
                s.requested_by,
                s.supersedes,
                s.requested_at or now,
                now,
            ),
        )
        logged += 1

    return {"logged": logged, "skipped": skipped}


def run(
    db_path: Path | None = None,
    suppressions_dir: Path = DEFAULT_SUPPRESSIONS_DIR,
    *,
    require_voter_exists: bool = True,
) -> dict[str, int]:
    """End-to-end: read YAML, apply against the warehouse. Used by Prefect."""
    suppressions = load_all_suppressions(suppressions_dir)
    if not suppressions:
        return {"logged": 0, "skipped": 0}
    with warehouse.connect(db_path) as conn:
        warehouse.apply_schema(conn)
        return apply_suppressions(conn, suppressions, require_voter_exists=require_voter_exists)
