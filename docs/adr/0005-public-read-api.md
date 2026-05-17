# ADR-0005: Public read API surface

**Status:** Accepted
**Date:** 2026-05-17
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-0001 (architecture), ADR-0004 (voter ethics), L09c (filter vs rewrite), L09d (cross-pipeline shape)

## Context

Phases 1 and 2 built a warehouse. Phase 2.4 makes some of that warehouse readable from the public internet. That is the first moment the project actually exposes any data to anyone outside the maintainer, and the first moment the careful invariants built into the schema (ADR-0004), the suppression view chain (L09c), and the cross-pipeline view (L09d) have to survive contact with HTTP.

The question is not "should we ship an API." It is "what shape of API preserves every promise the warehouse already makes, and which promises does the API itself need to add."

## Decision

### 1. The API is read-only and curated, not generic

We do **not** ship a generic SQL endpoint or a Datasette surface that auto-exposes every table. We ship FastAPI with explicit, named endpoints, one per warehouse surface we are willing to publish. The route list is itself the privacy contract: if it isn't routed, it isn't public.

Endpoints in scope for v1:

- `GET /v1/seb/meetings` — paginated list of `seb.meetings` rows
- `GET /v1/seb/meetings/{meeting_id}` — one meeting plus its videos, controversies, sources
- `GET /v1/voter/county-registration` — rows from `voter.county_registration_summary`
- `GET /v1/analytics/seb-voter-overlap` — rows from `analytics.seb_voter_overlap`
- `GET /v1/health` — liveness, returns the warehouse build timestamp

Endpoints explicitly **out of scope**:

- Anything that hits `voter.voters` directly. Public reads go through `voter.public_voters` or aggregates only. Per L09c the underlying table contains rows the public surface must not return; the API enforces this by not having a route to the underlying table.
- Anything that returns `voter.suppressions`. The audit log is internal-only; the public sees the *effect* of suppressions (rows missing), never the *fact* of them (which would re-identify the people who filed them).
- Anything that returns precinct-level voter data. Precinct + small county is a re-identification vector per ADR-0004 Rule 4.
- A free-text SQL endpoint. The warehouse is DuckDB, the temptation to expose `?sql=` is real, the answer is no.

### 2. Every route reads from a view, never a base table

The FastAPI handlers `SELECT` from `voter.public_voters`, `voter.county_registration_summary`, `analytics.seb_voter_overlap`, and the SEB tables which are already public-safe. They do **not** `SELECT` from `voter.voters` or `voter.suppressions`. This is enforced two ways:

- **Code review.** A grep for `FROM voter.voters` or `FROM voter.suppressions` in `outputs/api/` is a blocking review failure, codified in `CODEOWNERS` and a CI check.
- **Tests.** `test_no_route_reads_base_voter_table` parses every handler's SQL and asserts the FROM-clause hits an allow-listed view name. The list is in `outputs/api/_allowed_sources.py`; changing it requires touching that file in the same PR, which surfaces in review.

### 3. The DuckDB connection is opened read-only

The API process opens DuckDB with `read_only=True`. A bug, a typo, or a creative URL parameter cannot cause a write. The warehouse is rebuilt by the ingest flow and shipped to the API as an immutable artifact; the API never mutates its own data store.

### 4. Pagination is mandatory and bounded

Every list endpoint requires `limit` (default 50, max 500) and `offset`. There is no "return everything" path. This is partly a resource concern and mostly a re-identification concern: combining a full dump of `voter.county_registration_summary` with an external dataset is a different threat than combining 50 rows. Bulk data has a separate, documented release path (see decision 7).

### 5. Rate limiting is per-IP and visible

100 requests per minute per IP, returning `429` with a `Retry-After` header. The limit is generous on purpose: researchers and journalists should not need to ask permission. It exists to make sustained extraction obvious in logs, not to gate access.

### 6. Caching is HTTP-native

`Cache-Control: public, max-age=3600` on every read response, with `ETag` derived from the warehouse build timestamp. The warehouse is rebuilt on a fixed cadence; within a build, every response is byte-identical, so caching at the edge (Vercel) is free correctness rather than a tradeoff.

### 7. Bulk data has a separate, slower path

Researchers who want the full `voter.county_registration_summary` table do not get it from the API. They get it from a published CSV/Parquet artifact, regenerated per warehouse build, with the same column allow-list as the API, served from object storage with its own URL. The split serves two purposes: (1) the API is for interactive, paginated reads, not data dumps; (2) the bulk artifact is a deliberate publication event that can be versioned, hash-pinned, and listed on a page that says "here is what we published, here is when, here is what's in it." See L09e (the lesson this ADR writes).

### 8. The API ships behind a versioned prefix

Every route lives under `/v1/`. When a breaking change is needed, we ship `/v2/` alongside and deprecate `/v1/` on a published timeline. Breaking change is defined as: column removed, column type changed, route removed, semantics altered. Adding columns or routes is not breaking.

### 9. Hosting: Vercel serverless

The repo deploys to Vercel via the existing `vercel` integration. The DuckDB file is bundled into the deployment as a read-only asset. Rebuilds of the warehouse trigger a redeploy. This trades some per-request latency (cold starts hit the file system) for zero infrastructure: no Fly machines to keep alive, no S3 reads on the hot path, no Docker image to maintain.

The alternative (Fly.io with a long-running Python process) is documented and rejected for this phase on operational grounds: Vercel is already in the maintainer's toolchain, the API does not need long-lived connections, and DuckDB cold-opens fast enough to fit in a serverless cold-start budget. If sustained traffic ever justifies a warm process, we revisit.

### 10. Observability: structured logs, no PII

Every request logs: timestamp, route, status, latency, IP-hash (SHA-256 with a rotating salt, not the IP itself), response byte count. No query parameters with voter identifiers are ever logged. The salt rotates daily so the same researcher cannot be re-identified across days from logs alone. This is observability-grade auditing, not surveillance-grade.

## Consequences

**Good:**

- The API surface is small, named, and reviewable. A new contributor can audit "what does this project publish" in 30 seconds by reading the route table.
- The two-layer enforcement (view-chain in SQL + allow-list in Python) means a single mistake at one layer cannot leak. This mirrors the schema-level enforcement in ADR-0004.
- Versioning, caching, rate-limiting, and pagination are decided once and apply uniformly. We are not negotiating each tradeoff per endpoint.
- The bulk-data split keeps the API honest. Anyone who wants more than 500 rows at a time is, by design, downloading a documented artifact rather than scripting against a paginated endpoint.

**Hard:**

- A FastAPI app is more code than a Datasette deployment. We are betting that the code is itself part of the teaching surface — the endpoint list, the allow-list module, the "no FROM voter.voters" CI check.
- Bundling DuckDB into the Vercel deployment caps the warehouse size to what fits in a Vercel function's bundle. When that breaks, we move DuckDB to object storage and read on-demand, which is a documented future state, not a current one.
- Vercel serverless cold starts will add latency on the long tail. Acceptable for civic-tech read traffic; not acceptable forever.

**Open:**

- Authentication. v1 is fully public. If a future surface needs auth (e.g., the bulk artifact for a partner who needs row-level data the public version suppresses), that is a separate ADR.
- CORS. v1 allows any origin. If the eventual consumer surface is `ga-redistricting-hub` only, we lock CORS down then; until then, an open API is the point.

## Lesson

This ADR writes **L09e — Distribution ethics: what we publish vs. what we hold.** The lesson is recorded in `docs/teaching/LESSONS.md` and points at this ADR, the route list in `outputs/api/`, the allow-list module, and the bulk-vs-API split.
