# Runbook: the warehouse rebuild failed

For when the scheduled Prefect flow that rebuilds the warehouse from sources errors out, and the next person on the rotation needs to figure out whether to retry, patch, or escalate.

## What "rebuild" means

The ingest flow (`pipelines/seb_meetings/flows/ingest.py` and `pipelines/voter_file/flows/apply_suppressions.py`) does these things in order:

1. Apply the SQL schema (idempotent — safe to re-run).
2. Pull sources (YouTube RSS, SOS pages, voter bulk file).
3. Transform and validate via Pydantic models.
4. Insert/upsert into DuckDB.
5. Apply corrections from `corrections/*.yaml`.
6. Apply suppressions from `suppressions/*.yaml`.
7. Emit a summary log line.

"Failed" means any of those steps raised, OR the flow ran but step 7's summary shows zeros where there should be data.

## Step 1: identify the failing step

Pull the Prefect flow run page or the structured logs:

```bash
prefect flow-run inspect <flow-run-id>
# or:
vercel logs ga-watchdog-api --since 6h | grep flow_run_id=<id>
```

Look for the last successful log line and the first exception. Match against the seven steps above. The fix path branches sharply on which step failed.

## Step 2: branch by failing step

### Step 1 (schema) failed

This almost never happens — `CREATE TABLE IF NOT EXISTS` and `CREATE OR REPLACE VIEW` are idempotent. If it does fail, the most likely cause is a recently-merged warehouse SQL change with a syntax error or a view referencing a column that doesn't exist yet.

Confirm:

```bash
duckdb /tmp/probe.duckdb < warehouse/schema/voter.sql
duckdb /tmp/probe.duckdb < warehouse/queries/seb_voter_overlap.sql
```

If those error, revert the offending SQL PR and run the ingest again. Open a follow-up PR to fix the SQL properly.

### Step 2 (sources) failed

The most common failure. Three sub-cases:

- **Upstream format drift.** YouTube changed its RSS shape, the SOS page added a column, the bulk file has a new header order. See `docs/runbooks/seb-source-format-drift.md` (when written) for the SEB side; for voter, check the bulk-file source's `pyproject.toml`-pinned format version.
- **Upstream is down.** YouTube was 503ing. Check by hand:

  ```bash
  curl -I https://www.youtube.com/feeds/videos.xml?channel_id=<id>
  ```

  If it's a transient 5xx, retry the flow. Prefect's default retry policy may have already done so.
- **Network from the runner.** If you're running ingest on Prefect Cloud and they're having issues, status.prefect.io. If on a self-hosted worker, check the worker's egress.

### Step 3 (validate) failed

A source returned a row that didn't fit the Pydantic model. This is by design — `extra="forbid"` raises rather than silently dropping columns (see L05, L06).

The exception message will name the field. Two paths:

- **A new column upstream.** The source added a column we don't yet model. Decide whether to model it (add to the Pydantic class + warehouse schema + tests, in one PR) or to filter it out at the source layer. Default to modeling unless the column is clearly transient.
- **A value violates a constraint.** E.g., `hours_logged=99` failing the `<= 24` check. Either the data is wrong (open a correction) or the constraint is wrong (open an ADR-shaped discussion before relaxing it).

Do NOT widen the schema reflexively to make the error go away.

### Step 4 (insert) failed

Usually a UNIQUE or CHECK constraint violation in DuckDB. The error message will name the constraint. Three causes in descending order:

- **Idempotency bug in the source.** The same row was processed twice in one run. The source's upsert logic needs review.
- **Schema and Pydantic drifted.** Pydantic says the value is fine, SQL says no. Both layers enforce the same invariant per L06; if they disagree, one is wrong. Read both and fix.
- **The data is genuinely violating an invariant the schema encodes.** Treat as step-3 failure above.

### Step 5 (corrections) failed

The corrections workflow validates against `ALLOWED_COLUMNS` (Python) and `CHECK (target_column IN (...))` (SQL). A correction targeting a not-yet-allowed column will fail.

- **Bad correction YAML.** Fix the YAML in a new PR.
- **Allow-list missing the column.** Update `ALLOWED_COLUMNS` AND the SQL CHECK in one PR (per L09). Tests will fail if you update only one.

### Step 6 (suppressions) failed

Per L09c, suppressions are read-only operations against `voter.voters`; the failure mode is usually a missing `voter_id`. The YAML references a voter who isn't in the warehouse — typically because the warehouse hasn't been rebuilt with the most recent voter file.

Run the voter ingest first, then re-run apply_suppressions.

### Step 7 (summary) shows zeros

The flow technically succeeded but ingested nothing. Either sources returned empty (treat as step 2) or a quiet exception was swallowed somewhere (open an issue and audit).

## Step 3: retry, patch, or escalate

After identifying the cause:

- **Transient (upstream 5xx, network blip)**: retry. Prefect's UI has a "Restart" button on failed runs.
- **Patchable in code (format drift, new column, bad YAML)**: write a PR, get it reviewed, merge, retry. Do not patch the warehouse by hand.
- **Patchable in data (the source is wrong)**: write a correction (`docs/runbooks/corrections.md`), merge, retry.
- **None of the above**: escalate. Open an issue with the flow run ID, the last successful log line, the first exception, and your reading of which of the seven steps failed.

## What this runbook does not cover

- The API is returning stale data. See `api-stale-data.md`.
- The warehouse rebuilt successfully but the numbers look wrong. That's a data-quality investigation, not a rebuild failure. Start with `corrections.md` and the source's history.
