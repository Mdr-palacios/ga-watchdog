"""Corrections workflow — read YAML, write audited overrides to DuckDB.

A correction is the only sanctioned way to change a value the workbook
or RSS source supplied. Every correction is:

  - Authored as a YAML entry in `corrections/*.yaml`
  - Reviewed in a PR (CODEOWNERS + branch protection)
  - Logged immutably in `seb.meeting_corrections` on apply
  - Then projected into `seb.meetings` so reads see corrected values

YAML schema
-----------
Each file is a mapping with a `corrections:` list. Every list item is a
dict with these keys (all required unless marked optional):

    id:              kebab-case-string-stable-across-runs
    meeting_id:      integer matching seb.meetings.meeting_id
    column:          one of the columns whitelisted in
                     warehouse/schema/seb_corrections.sql
    new_value:       string, integer, float, or null
    reason:          single line explanation
    evidence_url:    optional URL backing the correction
    corrected_by:    GitHub handle of the author
    corrected_at:    optional ISO timestamp (default: file's last commit)

Re-applying is a no-op (`INSERT OR IGNORE` on `id`). To supersede an
earlier correction, write a new entry with a new `id` and reference the
previous id in `reason`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import yaml

from warehouse import loader as warehouse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORRECTIONS_DIR = REPO_ROOT / "corrections"

ALLOWED_COLUMNS = {
    "video_url",
    "source_url",
    "meeting_format",
    "chair",
    "members_present",
    "quorum_met",
    "agenda_summary",
    "key_decisions",
    "compliance_status",
    "compliance_notes",
    "controversies",
    "hours_logged",
}


@dataclass(frozen=True)
class Correction:
    """One parsed correction record. Immutable on purpose."""

    id: str
    meeting_id: int
    column: str
    new_value: object  # str | int | float | None
    reason: str
    corrected_by: str
    evidence_url: str | None = None
    corrected_at: dt.datetime | None = None


def load_corrections_file(path: Path) -> list[Correction]:
    """Parse one corrections YAML file. Validates structure; raises on bad shape."""
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict) or "corrections" not in data:
        raise ValueError(
            f"{path}: missing top-level 'corrections:' list. "
            f"See docs/runbooks/corrections.md for the file format."
        )
    raw = data["corrections"] or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: 'corrections' must be a list, got {type(raw).__name__}")

    out: list[Correction] = []
    seen: set[str] = set()
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: entry #{idx} is not a mapping")
        missing = {"id", "meeting_id", "column", "reason", "corrected_by"} - entry.keys()
        if missing:
            raise ValueError(f"{path}: entry #{idx} missing required keys: {sorted(missing)}")
        cid = str(entry["id"]).strip()
        if not cid:
            raise ValueError(f"{path}: entry #{idx} has an empty id")
        if cid in seen:
            raise ValueError(f"{path}: duplicate correction id {cid!r} in same file")
        seen.add(cid)

        column = str(entry["column"]).strip()
        if column not in ALLOWED_COLUMNS:
            raise ValueError(
                f"{path}: entry {cid!r} targets column {column!r} which is not "
                f"in the allow-list. Add it to ALLOWED_COLUMNS and the SQL "
                f"CHECK constraint together, then file an ADR."
            )

        corrected_at = entry.get("corrected_at")
        if isinstance(corrected_at, str):
            corrected_at = dt.datetime.fromisoformat(corrected_at)
        elif corrected_at is not None and not isinstance(corrected_at, dt.datetime):
            raise ValueError(f"{path}: entry {cid!r} corrected_at must be ISO string or datetime")

        out.append(
            Correction(
                id=cid,
                meeting_id=int(entry["meeting_id"]),
                column=column,
                new_value=entry.get("new_value"),
                reason=str(entry["reason"]).strip(),
                corrected_by=str(entry["corrected_by"]).strip(),
                evidence_url=entry.get("evidence_url"),
                corrected_at=corrected_at,
            )
        )
    return out


def load_all_corrections(directory: Path = DEFAULT_CORRECTIONS_DIR) -> list[Correction]:
    """Load every `.yaml` file under `corrections/`, in lexical filename order."""
    if not directory.exists():
        return []
    rows: list[Correction] = []
    for path in sorted(directory.glob("*.yaml")):
        rows.extend(load_corrections_file(path))
    # Cross-file duplicate-id check.
    seen: set[str] = set()
    for c in rows:
        if c.id in seen:
            raise ValueError(
                f"Duplicate correction id across files: {c.id!r}. Ids must be globally unique."
            )
        seen.add(c.id)
    return rows


def _read_original_value(conn: duckdb.DuckDBPyConnection, meeting_id: int, column: str) -> object:
    """Snapshot the current value of `column` for `meeting_id` before overwrite."""
    # Column name is validated against ALLOWED_COLUMNS above; safe to interpolate.
    row = conn.execute(
        f"SELECT {column} FROM seb.meetings WHERE meeting_id = ?",  # noqa: S608
        (meeting_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"correction targets meeting_id={meeting_id} which does not exist "
            f"in seb.meetings. Did the seed step skip it?"
        )
    return row[0]


def apply_corrections(
    conn: duckdb.DuckDBPyConnection,
    corrections: list[Correction],
) -> dict[str, int]:
    """Log + apply corrections. Returns counts for logged/applied/skipped.

    `logged`   — first-time corrections inserted into seb.meeting_corrections
    `applied`  — UPDATE statements run on seb.meetings
    `skipped`  — already-logged corrections (idempotent re-runs)
    """
    logged = applied = skipped = 0
    for c in corrections:
        # Insert into the audit log; PK conflict means we've seen this id.
        cur = conn.execute(
            "SELECT 1 FROM seb.meeting_corrections WHERE correction_id = ?",
            (c.id,),
        ).fetchone()
        already_logged = cur is not None

        if already_logged:
            skipped += 1
            continue

        original = _read_original_value(conn, c.meeting_id, c.column)
        conn.execute(
            "INSERT INTO seb.meeting_corrections "
            "(correction_id, meeting_id, target_column, original_value, "
            " corrected_value, reason, evidence_url, corrected_by, corrected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c.id,
                c.meeting_id,
                c.column,
                None if original is None else str(original),
                None if c.new_value is None else str(c.new_value),
                c.reason,
                c.evidence_url,
                c.corrected_by,
                c.corrected_at or dt.datetime.now(dt.UTC),
            ),
        )
        logged += 1

        # Apply to the meeting row. Column whitelisted above; safe to interpolate.
        conn.execute(
            f"UPDATE seb.meetings SET {c.column} = ? WHERE meeting_id = ?",  # noqa: S608
            (c.new_value, c.meeting_id),
        )
        applied += 1

    return {"logged": logged, "applied": applied, "skipped": skipped}


def run(
    db_path: Path | None = None,
    corrections_dir: Path = DEFAULT_CORRECTIONS_DIR,
) -> dict[str, int]:
    """End-to-end: read YAML, apply against the warehouse. Used by Prefect."""
    corrections = load_all_corrections(corrections_dir)
    if not corrections:
        return {"logged": 0, "applied": 0, "skipped": 0}
    with warehouse.connect(db_path) as conn:
        return apply_corrections(conn, corrections)
