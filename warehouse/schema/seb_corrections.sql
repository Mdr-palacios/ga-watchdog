-- Corrections — the audit log for human overrides of warehouse data.
--
-- Why this exists
-- ---------------
-- Phase 1 establishes a precedence rule: the workbook is the human-curated
-- system of record, and ingestion never silently rewrites a value the
-- workbook supplied. But that rule on its own makes the warehouse stuck
-- with known-wrong data when the workbook itself has an error (see L07
-- in LESSONS.md — the May 14 video URL that actually points to the
-- April 22 meeting).
--
-- The corrections workflow is the *political* answer to that technical
-- problem. A correction is:
--   1. Authored by a human in a YAML file under `corrections/`
--   2. Reviewed in a normal PR (CODEOWNERS apply, branch protection
--      requires approval)
--   3. Applied by the ingest flow as the final step, with provenance
--      logged immutably in this table
--
-- This table is NEVER updated, only inserted into. Every override leaves
-- a trail. You can replay the trail to reconstruct the warehouse-as-of
-- any prior point in time.
--
-- Schema design notes
-- -------------------
-- - `target_table` and `target_column` are strings, not enums. A new
--   corrected column never requires a schema change here.
-- - `original_value` and `corrected_value` are TEXT — we cast on read.
--   This keeps the audit table type-agnostic and uniform across columns
--   of different types.
-- - `correction_id` is the natural primary key of a YAML correction file
--   entry, NOT a synthetic auto-increment. Authoring the ID by hand
--   forces the author to think about uniqueness and discoverability.

CREATE SCHEMA IF NOT EXISTS seb;

CREATE TABLE IF NOT EXISTS seb.meeting_corrections (
    correction_id     VARCHAR PRIMARY KEY,
    meeting_id        INTEGER NOT NULL REFERENCES seb.meetings(meeting_id),
    target_column     VARCHAR NOT NULL,
    original_value    TEXT,                  -- snapshot before correction; NULL allowed
    corrected_value   TEXT,                  -- new value; NULL means "delete this value"
    reason            TEXT    NOT NULL,
    evidence_url      VARCHAR,               -- source backing the correction, if any
    corrected_by      VARCHAR NOT NULL,      -- human handle / name
    corrected_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Re-applying the same correction is a no-op (PK conflict on
    -- correction_id). To revise an existing correction, supersede it
    -- with a new correction_id and a reason that references the prior.
    CONSTRAINT meeting_corrections_target_column_known
        CHECK (target_column IN (
            'video_url',
            'source_url',
            'meeting_format',
            'chair',
            'members_present',
            'quorum_met',
            'agenda_summary',
            'key_decisions',
            'compliance_status',
            'compliance_notes',
            'controversies',
            'hours_logged'
        ))
);

-- Convenience view: the latest correction for each (meeting_id, column).
-- The flow uses this to decide which value to write back to the meeting
-- row. Older corrections remain in the table for audit.
CREATE OR REPLACE VIEW seb.meeting_corrections_latest AS
SELECT
    meeting_id,
    target_column,
    LAST(correction_id ORDER BY corrected_at)   AS correction_id,
    LAST(corrected_value ORDER BY corrected_at) AS corrected_value,
    LAST(corrected_by ORDER BY corrected_at)    AS corrected_by,
    LAST(corrected_at ORDER BY corrected_at)    AS corrected_at,
    LAST(reason ORDER BY corrected_at)          AS reason,
    LAST(evidence_url ORDER BY corrected_at)    AS evidence_url
FROM seb.meeting_corrections
GROUP BY meeting_id, target_column;
