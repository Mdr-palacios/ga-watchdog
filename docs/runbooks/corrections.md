# Runbook — correcting a value in the warehouse

## When to write a correction

When the ingest sources (workbook, YouTube RSS, future sources) give you
a value that you know is wrong and have evidence to back the fix.

The pipeline never silently rewrites source data. Every override is a
correction, every correction is a PR, every correction lands in
`seb.meeting_corrections` immutably with provenance.

## When NOT to write a correction

- **The workbook is wrong but you don't have evidence.** Don't paper over
  it. Either find evidence, leave it, or open an issue to track.
- **The RSS source is missing a meeting.** That's a gap, not a wrong
  value. Phase 2 backfill, not a correction.
- **You want to change the schema or add a column.** That's an ADR, not
  a correction.

## How to write one

1. Pick a globally unique id. Convention:
   `<scope>-<meeting-id>-<short-slug>-<yyyy-mm-dd>`
   Example: `meeting-1-may-14-video-url-2026-05-16`

2. Add an entry to `corrections/seb_meetings.yaml`. Required fields:
   `id`, `meeting_id`, `column`, `new_value`, `reason`, `corrected_by`.
   Highly recommended: `evidence_url`.

3. Open a PR. CODEOWNERS will route it. Branch protection enforces
   review.

4. On merge, the next ingest run picks up the correction
   (`python -m pipelines.seb_meetings.flows.ingest`). The correction
   is applied exactly once. Re-runs are no-ops.

## Reverting a correction

Corrections are append-only. To undo a previous correction, write a
new entry with a new `id` that reverts the value, and reference the
prior id in the `reason`.

Example:

```yaml
- id: meeting-1-may-14-video-url-2026-06-01-revert
  meeting_id: 1
  column: video_url
  new_value: https://www.youtube.com/watch?v=h_0CXACXv9A
  reason: >-
    Revert meeting-1-may-14-video-url-2026-05-16 — see PR #42 discussion;
    the original workbook link was actually correct after all.
  corrected_by: anamcodigos
```

Both records remain in `seb.meeting_corrections` forever.

## Auditing

Pull the audit trail for any meeting at any time:

```sql
SELECT correction_id, target_column, original_value, corrected_value,
       reason, corrected_by, corrected_at
FROM seb.meeting_corrections
WHERE meeting_id = 1
ORDER BY corrected_at;
```

Or the current effective override for a column:

```sql
SELECT * FROM seb.meeting_corrections_latest
WHERE meeting_id = 1 AND target_column = 'video_url';
```
