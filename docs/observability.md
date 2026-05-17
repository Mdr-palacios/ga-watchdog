# Observability conventions

Lightweight observability conventions for a repo that does not run an observability platform. The goal: enough signal to answer "what is the pipeline doing right now" and "what was it doing when it broke" using only structured logs, Prefect's flow-run UI, and the warehouse itself.

If you find yourself wanting Datadog or Sentry, read this first. The conventions below are deliberately the smallest set that lets you stop wanting them.

## Why this is in the repo

L11 (see `docs/teaching/LESSONS.md`) is the lesson form of this doc. This file is the reference; L11 is the reasoning. Read both together.

## What we log, and what we don't

### Every flow logs

- Flow-run boundaries: start, end, summary counts.
- Per-step transitions: schema applied, sources fetched, transforms run, warehouse written, corrections applied, suppressions applied.
- Counts at each step (rows in, rows out, rows skipped).
- Exceptions, with the field name when validation fails (Pydantic gives this for free).

### The public API logs

- Every request: route, method, status, latency_ms, response_bytes, ip_hash.
- 429s, with the rate-limit window and the requested route.
- DuckDB connection failures.

### What we do not log, ever

- Raw IPs. The API uses a per-day-salted SHA-256 prefix (see `outputs/api/_logging.py` and ADR-0005 §10). The salt rotates at UTC midnight so same-IP requests across days do not link.
- Query parameters that could contain voter identifiers. Even though the API doesn't accept them today, the log function's signature does not take query params at all — adding a route that takes a voter ID cannot silently make it loggable.
- Raw row content. Pipeline logs report counts and field names; they do not echo the value that failed validation, because that value is sometimes the data we promised to protect.
- Stack traces in production response bodies. Stack traces go to logs; the response says "internal error" with a request id the caller can quote in a bug report.

## Format: structured everywhere, no exceptions

All logs are structlog-formatted JSON. One event per line. Keys are stable so a `jq` pipeline written today still works in six months.

```python
# Good
log.info("videos_upserted", count=video_count, source="youtube_rss")

# Bad (do not do this)
log.info("Videos upserted: %d from %s", video_count, "youtube_rss")
```

The bad form happens to be common in the codebase today; see the `Known drift` section below.

### Required keys

Every log line includes:

- `event` — a snake_case verb or noun (`schema_applied`, `videos_upserted`, `request`, `correction_applied`).
- `level` — INFO, WARN, ERROR. Structlog handles this automatically.
- `timestamp` — UTC ISO-8601. Structlog handles this automatically.

### Conventional keys

When relevant, use these keys consistently:

- `flow_run_id` — Prefect flow run id.
- `meeting_id`, `voter_id` (count only; never as a primary key in a log line that includes per-voter data — and per-voter data is never logged).
- `count` — for any rollup. Pair with a `unit` if the unit isn't obvious from the event name.
- `source` — one of `youtube_rss`, `sos_website`, `bulk_voter_file`, `workbook`, `corrections_yaml`, `suppressions_yaml`.
- `duration_ms` — float, milliseconds elapsed.
- `error_type` — exception class name when logging an error.
- `error_message` — the exception message. Sanitize if it could contain row content.

If you find yourself wanting a new conventional key, add it here in the same PR that adds the first usage. Conventions only work if they are written down.

## Severity rules

- **INFO**: expected events. Flow start, step transitions, counts, request logs. Most lines.
- **WARN**: something unusual happened but the system handled it. A correction overrode a sourced value (per L07 we want this visible). A source returned an empty result when we expected non-empty. A retry succeeded.
- **ERROR**: something failed. An exception was raised. Validation refused a row. A SQL constraint was violated. ERROR lines should be rare; if you see ten in a healthy week, the threshold is wrong.

Never use ERROR for events that are part of normal operation. A 404 from `GET /v1/seb/meetings/9999` is INFO, not ERROR — it's a caller error, not a system error.

## Where logs live

- **Local development**: stdout. Pretty-printed by structlog's `ConsoleRenderer` if a TTY is attached, JSON otherwise.
- **Prefect flow runs**: Prefect captures stdout and attaches it to the flow run. The Prefect UI is the operator's primary view.
- **Vercel API**: stdout. Vercel's log dashboard ingests it. For ad-hoc investigation:

  ```bash
  vercel logs ga-watchdog-api --since 1h | jq 'select(.event == "request" and .status >= 500)'
  ```

## Counting things without a metrics platform

We do not run Prometheus. We do not run a TSDB. The two questions metrics platforms answer ("what is the rate of X" and "what is the trend of Y") are answered here by:

1. **Rate**: grep the structured logs over a time window. For the API: `vercel logs --since 1h | grep '"event":"request"' | wc -l`.
2. **Trend**: the warehouse itself. Every ingest run inserts to `seb.meetings`, `voter.voters`, and an internal `pipeline_runs` table (TODO: add this — tracked in [#13](https://github.com/Mdr-palacios/ga-watchdog/issues/13)). A SQL query against the run table answers "how many meetings did we ingest per week for the last quarter" directly.

This is intentional. Adding a metrics platform is a real maintenance commitment; we delay it until the questions we cannot answer with logs and SQL are concrete and frequent.

## Tracing

We do not run distributed tracing. The pipelines are short and linear; the API is one process. If a request needs more debugging than its log line provides, add a `request_id` (generated at the middleware layer, propagated as a header) and log it on every line in that request's lifecycle. We don't have this today; tracked in [#14](https://github.com/Mdr-palacios/ga-watchdog/issues/14).

## When to add an alert

We do not run alerting today. The closest thing is the Prefect UI showing failed flow runs.

If you find yourself adding an alert, ask first:

1. Is there a runbook for the alert? If not, the alert is noise — write the runbook first.
2. Does the alert fire on a condition a human can act on within the next 24 hours? If not, it's a report, not an alert. Make it a weekly digest instead.
3. Will the alert fire because of a transient upstream issue? If yes, add retries first and alert only on retry exhaustion.

Three runbooks exist today: `api-stale-data.md`, `rate-limit-firing.md`, `warehouse-rebuild-failure.md`. Those are the conditions that have earned an alert.

## Known drift (TODO list)

Honest accounting of where the current codebase doesn't match this doc. Each item is a filed issue — see `gh issue list --label area:observability`.

- [ ] `pipelines/seb_meetings/flows/ingest.py` uses `prefect_log.info("Seed counts: %s", seed_counts)` style. Should be `log.info("seed_complete", counts=seed_counts)`. [#11](https://github.com/Mdr-palacios/ga-watchdog/issues/11)
- [ ] `pipelines/voter_file/flows/apply_suppressions.py` has the same drift. [#12](https://github.com/Mdr-palacios/ga-watchdog/issues/12)
- [ ] No `pipeline_runs` table yet. Trend queries against ingest history are not possible until this lands. [#13](https://github.com/Mdr-palacios/ga-watchdog/issues/13)
- [ ] No `request_id` propagation in the API. [#14](https://github.com/Mdr-palacios/ga-watchdog/issues/14)

None of these block correctness; all of them block this doc from being fully true. The discipline of writing each one down as both a doc bullet *and* a tracked issue is itself a lesson — see [L12](teaching/LESSONS.md).
