# Runbook: the rate limit is firing for legitimate traffic

For when a researcher, journalist, or coalition partner says "your API keeps giving me 429."

## What the rate limit does

100 requests per minute per IP. After the 100th request in a 60-second window, every additional request returns `429` with a `Retry-After` header.

The limit is intentionally generous so researchers don't need to ask permission. It exists to make sustained automated extraction visible in logs, not to gate access.

## Step 1: is the caller actually over the limit?

Ask for two things:

- A `curl -i` of the failing request (so you see the response headers including `Retry-After`).
- Roughly how many requests per minute their script is sending.

If they're sending 50/minute they aren't over the limit — go to step 4.

If they're sending 200/minute they are over the limit. Continue.

## Step 2: is this one caller or many?

The rate limit is per-IP. Use the structured logs to confirm whether one source is driving the 429s or whether many sources are independently hitting it.

```bash
# Vercel logs for the last hour:
vercel logs ga-watchdog-api --since 1h | grep '"status":429'
```

The log lines include `ip_hash` (a daily-rotating 16-char hash, not the IP). Count unique hashes:

```bash
vercel logs ga-watchdog-api --since 1h | \
  grep '"status":429' | \
  jq -r '.ip_hash' | sort -u | wc -l
```

- **One hash**: one caller is exceeding the limit. Continue to step 3.
- **Many hashes**: the limit is generally too low, OR you're seeing distributed traffic from a partner that shares CGNAT. Different problem — go to step 5.

## Step 3: legitimate one-caller bulk extraction

Three options, in order of preference:

1. **Point them at the bulk artifacts.** If they want the full table, the API is the wrong tool. `outputs/bulk/` ships CSV and Parquet snapshots of every public view, regenerated per warehouse build, with `MANIFEST.json` listing `sha256` per file. The download is one HTTP request per file. Send them the URL.

2. **Suggest pagination at a polite pace.** The API supports `limit=500` (the max). At 100 requests per minute with 500-row pages, they can pull 50,000 rows per minute without ever tripping the limit. That's enough for most county-level analysis.

3. **If neither fits, the API surface is wrong, not the limit.** Open an issue describing the use case. The fix is usually a new endpoint or a new bulk artifact, not raising the limit.

Do NOT raise the limit for one caller. The rate limit is per-IP code, not per-user; "raising it for them" means raising it for everyone, and that defeats the visibility purpose.

## Step 4: false alarm — they aren't actually over the limit

A few real causes:

- **They're behind a NAT or shared egress IP.** Office networks, university VPNs, mobile carriers — many users can share one egress IP, and their combined traffic trips the limit even though no single user is being heavy. Look at the `ip_hash` in the failing request's log line; if you see a high request count from one hash, that's the shared egress.
- **They're hitting from a serverless function or Lambda.** Cloud platforms recycle IPs across customers; the limit might be firing because of another tenant. Check the hash against other 429s in the same minute.
- **They got a 429 on a single request.** A 429 in isolation can be a race against the window boundary — they were at request 100, the second hand ticked, the window reset, and they got allowed on retry. Tell them to honor `Retry-After` and move on.

## Step 5: the limit is generally too low

If multiple unrelated callers are hitting 429s across normal-pace usage, the limit is wrong. Don't bump the number reflexively.

First check whether the issue is the **window**, not the **ceiling**:

- A fixed-window rate limit has a known "spike" problem: 100 requests in the last second of one window plus 100 in the first second of the next means 200 in 2 seconds, even though both windows are nominally compliant. If callers are reporting bursty 429s, the fix is a sliding-window or token-bucket implementation, not a higher number.

If the ceiling is genuinely too low, raise it via PR:

```python
# outputs/api/_rate_limit.py
MAX_REQUESTS_PER_WINDOW = 200  # was 100
```

`test_check_allows_under_limit` and `test_check_denies_over_limit_with_retry_after` will pick up the change automatically — no test edits needed.

Update ADR-0005 §5 in the same PR so the documented decision matches the code.

## When to escalate

- 429s are firing but the logs show no high-volume single hash. Likely a bug — investigate.
- After bumping the ceiling, the same callers still hit the limit. Either the window math is wrong, or they aren't using bulk artifacts when they should be.
- A 429 returns without a `Retry-After` header. That's a middleware bug — every 429 path in `outputs/api/app.py` sets it.

## What this runbook does not cover

- Rate limit on the bulk artifact URLs themselves. Those are served from object storage, not the API; they have their own throttles.
- The pre-deploy local rate-limit tests in `test_rate_limit.py` — those test the code in isolation, not the production limit.
