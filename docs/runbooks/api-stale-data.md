# Runbook: the public API is returning stale data

For the version of you who got an email at 6am saying "the registration numbers haven't changed in three weeks."

## What "stale" means here

The public API is served from a DuckDB file bundled into a Vercel deployment. "Fresh" means: the file in the running Vercel function is the one produced by the most recent successful ingest run. "Stale" means: the ingest ran, but the API is still serving an older file.

There are three places staleness can come from. Walk them in order — earlier causes mask later ones.

## Step 1: confirm staleness is real, not perceived

```bash
curl -s https://<api-host>/v1/health | python -m json.tool
```

Read the `warehouse_built_at` timestamp. If it is the timestamp you expected, the data is fresh and the report is wrong — go to step 4.

If it is older than the most recent ingest run, the API is genuinely stale. Continue.

## Step 2: did the ingest actually succeed?

```bash
# In the Prefect UI, find the most recent SEB or voter flow run.
# Or, from a terminal with Prefect access:
prefect flow-run ls --limit 5
```

Three failure modes to look for:

- **Flow failed.** The ingest blew up. The warehouse on disk is whatever the previous successful run produced. Fix the ingest first — see `docs/runbooks/seb-source-format-drift.md` if it's a YouTube/SOS source issue, or check the structured logs for the actual error. The flow run page shows the full stack trace.
- **Flow succeeded but skipped writes.** Rare; look for `Seed counts: {...}` and `Videos upserted: 0` log lines. If counts are zero across the board, the sources returned nothing. Confirm with a manual fetch before assuming the ingest is buggy.
- **Flow ran but didn't run today.** Prefect's schedule didn't fire. Check the deployment schedule and the last `Late` state in the UI.

If the ingest is healthy and recent, continue.

## Step 3: did the Vercel deploy update?

The API ships the DuckDB file inside the deploy bundle. If the ingest writes a new file but Vercel never rebuilt, the API still serves the old file.

```bash
vercel ls ga-watchdog-api
```

Look at the most recent deployment's `created` timestamp. If it predates the most recent successful ingest, the rebuild trigger didn't fire.

```bash
# Manual redeploy from the current main:
vercel --prod
```

Wait 30 seconds, then re-curl `/v1/health`. `warehouse_built_at` should now reflect the new file.

The long-term fix is the CI step that automatically redeploys on warehouse changes. If that step is broken, open an issue tagged `infra` and patch the workflow.

## Step 4: false alarm — investigating why someone thought it was stale

If `/v1/health` shows a fresh timestamp but the caller thinks the numbers haven't changed:

- **Is the caller hitting cached data?** Every `GET` returns `Cache-Control: public, max-age=3600`. A reverse proxy, a CDN, or even a browser may be holding a one-hour-old response. Ask them to send the response headers from a `curl -I` and check the `Age` header.
- **Are the numbers actually the same?** Voter registration changes are slow and the SEB doesn't meet every week. Three weeks of identical county totals is plausible. Sanity-check against the source workbook before declaring a bug.
- **Are they reading the wrong endpoint?** `/v1/voter/county-registration` is a snapshot, not a time series. If they expected a time series, they want `/v1/analytics/seb-voter-overlap` with a `year` filter.

## When to escalate

- Multiple ingest runs in a row have failed for unrelated reasons. That's a signal that something upstream of the pipeline changed — escalate to a deeper investigation.
- Vercel deploys are succeeding but the API is still serving old data after multiple redeploys. That's a build-cache or function-cache issue. Check `vercel inspect <deployment-id>` for the included files and confirm the DuckDB file in the bundle is the fresh one.
- The same query returns different results to different IPs. Indicates a partial deploy or a stuck function instance. Force a full redeploy and contact Vercel support if it persists.

## What this runbook does not cover

- The data is fresh but wrong. That's a correction, not a staleness problem. See `corrections.md`.
- The API is down entirely. That's a Vercel incident, not a data issue. Check status.vercel.com first.
