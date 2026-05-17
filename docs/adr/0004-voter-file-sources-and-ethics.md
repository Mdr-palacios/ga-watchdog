# ADR-0004 — Voter file: data sources, redaction, and distribution ethics

**Status:** Accepted
**Date:** 2026-05-16
**Decision owner:** Rosario Palacios

## Context

The second pipeline in this repo is a Georgia voter file watcher. Unlike the SEB meetings pipeline — where the inputs are public meetings, public PDFs, and public videos — the voter file is a dataset of ~7M+ identified people. The same technical patterns apply (Pydantic models, DuckDB warehouse, dlt + Prefect, corrections workflow), but the *political and legal* stakes are different by an order of magnitude. The architecture has to encode that.

Two things make this urgent rather than theoretical:

1. **The statute is specific.** [O.C.G.A. § 21-2-225](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/) names exactly which fields are public and which are confidential, names the no-commercial-use restriction, and authorizes the Secretary of State to set the fee.
2. **The threat model is current.** In late January 2026, [the FBI raided Fulton County's elections office](https://www.pbs.org/newshour/show/fbi-raids-georgia-elections-office-as-trump-administration-seeks-voter-data-from-states) and seized voter rolls. The [NAACP](https://naacp.org/articles/naacp-files-court-order-protect-georgia-voters-after-department-justice-seizes-election) and [ACLU](https://www.aclu.org/press-releases/nonpartisan-group-urges-court-to-protect-georgians-private-voter-data-seized-in-fbi-raid) filed for court protection in February. The data we are about to ingest is data that hostile actors are actively trying to get unredacted copies of. "We're a small nonprofit, no one will notice us" is not a viable security posture.

This ADR establishes the rules of engagement before any voter-file code lands.

## Decision

**Five rules, encoded in code, not in a Slack message.**

### Rule 1 — Only ingest what the statute makes public

[O.C.G.A. § 21-2-225(b)](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/) names the confidential fields explicitly:

| Field | Status under § 21-2-225(b) |
| --- | --- |
| Month and day of birth | **Confidential** (year of birth is public) |
| Social Security Number | **Confidential** |
| Driver's license number | **Confidential** |
| Email address | **Confidential** |
| Location where the elector applied to register | **Confidential** |
| Bank statements submitted under § 21-2-220(c) / § 21-2-417(c) | **Confidential** |

The Pydantic `Voter` model in [`pipelines/voter_file/transforms/models.py`](../../pipelines/voter_file/transforms/models.py) does not declare any of these fields. There is no `ssn`, no `dl_number`, no `email`, no `birth_month`, no `birth_day` field. If a source ever delivers them — by mistake or by a Secretary of State who changes their mind about what they ship — the ingestion fails Pydantic validation (`extra="forbid"`) at the record boundary, before anything lands in DuckDB.

This is the same pattern as L06 in `LESSONS.md`: enforce the same invariant at every layer it can be enforced at. Here the invariant is **statutory**, so the schema layer is the right place to make it permanent.

### Rule 2 — Year of birth, not date of birth, in the warehouse

The statute explicitly allows year of birth. We store *only* year of birth, as an `INTEGER`, never a full date. The transform that reads the SOS file pulls the year off whatever date format the source uses and discards the rest before the record is constructed. The audit log of how that transform works lives next to the transform itself, with a test that proves the month and day are gone before a `Voter` instance exists.

Why this matters: a single point of statutory compliance is easier to audit than "we promise we always strip it before write." A field that doesn't exist in the model cannot leak.

### Rule 3 — Default source is the paid statewide list. Free alternatives are watch-only.

There are three plausible source paths for Phase 2:

| Source | Cost | Bulk download? | What's in it |
| --- | --- | --- | --- |
| **Statewide voter registration list** ([SOS](https://georgiasecretaryofstate.net/), [authority](https://firstamendment.law.uga.edu/wp-content/uploads/2024/05/FINAL-Election-Records-Resource.pdf)) | $250 flat fee, [O.C.G.A. § 21-2-225(c)](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/) | Yes, electronic media | Name, address, race, gender, registration date, last voting date, year of birth (per [Ballotpedia](https://ballotpedia.org/Availability_of_state_voter_files) and the [EAC summary](https://www.eac.gov/sites/default/files/voters/Available_Voter_File_Information.pdf)) |
| **County or precinct list** ([SOS product page](https://georgiasecretaryofstate.net/products/county-or-municipal-district-or-precinct-voter-list)) | $50 per entity | Yes, electronic | Same fields, scoped to one jurisdiction |
| **My Voter Page** ([mvp.sos.ga.gov](https://mvp.sos.ga.gov/s/)) | Free | No — individual lookup only | Registration status, polling place, ballot status |

The paid statewide list is **the** source for warehouse population. Phase 2 ingestion is offline-only against a file the operator (not the pipeline) acquired from the SOS. The pipeline never tries to fetch the file over the network. There is no `requests.get("https://sos.ga.gov/voter-file.csv")` in this repo — by design.

My Voter Page is *watch-only*: it can be referenced from the warehouse (e.g., as a citation URL on a voter-status page), but the pipeline does not iterate over voters and call MVP for each, because (a) that's a different ethical question than ingesting the bulk file, and (b) it's the exact pattern a hostile actor would use to enumerate the file at no cost.

Pablo Barberá's [voter-files repo](https://github.com/pablobarbera/voter-files/blob/master/README.md) notes that Georgia delivers the file on physical media. We treat the file as opaque input: the operator hands the pipeline a path, the pipeline reads it.

### Rule 4 — The output API surface is statute-aware, not field-by-field opt-in

[§ 21-2-225(c)](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/) reads:

> Such data may not be used by any person for commercial purposes.

This pipeline's outputs do not get exposed via a paid API, a paid product, or a paid newsletter. The corresponding ADR for the public API surface (forthcoming) will state this affirmatively and the deploy config will enforce it (no payment integration in the API service).

Beyond the commercial-use prohibition, we also do not expose:

- Per-voter pages or per-voter API endpoints. The pipeline aggregates upward (precinct-level, county-level, turnout-trend-level), and that's what the public surface serves.
- Bulk downloads of any view that materializes a per-voter row. If you want the bulk data, the SOS sells it; we are not a redistribution channel.
- Joinable identifiers across pipelines that would let a third party re-identify voters by combining our outputs with another dataset.

These are not legal requirements — they are policy choices about what *kind* of civic-tech tool this is. The lesson (`L09b` in `LESSONS.md`, coming with the API surface): legality is the floor, not the ceiling.

### Rule 5 — Every redaction is auditable, every audit is documented

The Phase 1 corrections workflow ([ADR/PR #2](https://github.com/Mdr-palacios/ga-watchdog/pull/2)) already establishes the pattern: every override is a YAML file, every override is logged in an append-only audit table. Phase 2 extends this to **suppressions**:

- A voter or their representative may request that their record be suppressed from any public output we produce. This is broader than the statute requires; we're choosing to support it.
- A suppression is a YAML entry under `suppressions/voter_file.yaml` with a `voter_id`, `reason`, `requested_by`, and `requested_at`. The file is committed and reviewed under CODEOWNERS like a correction.
- Suppressed records remain in the warehouse (we cannot lie to ourselves about coverage), but are filtered out of every output. The filter is a SQL `WHERE NOT EXISTS (SELECT 1 FROM voter.suppressions WHERE ...)` clause, applied centrally, not in every query.
- The suppressions table is append-only, like corrections. Un-suppressing is a new entry that references the prior id.

This rule is what L09b in `LESSONS.md` will land on, in full, when the public API surface ships.

## Alternatives considered

**"Just don't build it. The data is too dangerous."** This is a real position. The reason we're building it anyway: the people who decide what happens to Georgia voters — legislators, advocacy orgs, election officials, journalists — already use this data, with worse tooling than what's in this repo, with no audit trail and no redaction discipline. A well-designed nonprofit-stewarded version with explicit rules is a better state of the world than refusing to engage and ceding the field to actors with fewer constraints.

**"Ingest everything the SOS sends, redact at read time."** Cheaper to write, much harder to audit. If the warehouse contains the SSN, "we promise we filter it out on read" is a security claim that depends on every query getting it right. A field that doesn't exist in the schema is one we can never accidentally select.

**"Free-only sources to avoid paying the SOS."** The free path (My Voter Page) is individual-lookup only and would require iterating ~7M lookups, which is both technically wrong (the page isn't an API) and ethically wrong (it's the enumeration pattern hostile actors use). Pay the $250 and ingest the official bulk file once.

**"Skip the suppressions workflow until someone asks."** A suppression workflow that doesn't exist yet, when the first request lands, becomes an ad-hoc DELETE statement on the warehouse — exactly the kind of "edit DuckDB by hand" move that L09 was designed to make impossible. Build the audit-logged version first; let the first request be a YAML file in a PR.

## Consequences

**Positive.** The Pydantic + DuckDB schemas encode the statute. Every ingestion run that mistakenly includes a confidential field fails loudly. Every suppression has a paper trail. The boundary between "what we ingest" and "what we publish" is two different tables, not a hopeful WHERE clause.

**Negative.** Some legitimate research questions need a date of birth, not a year. We will turn down those requests, or pay the SOS for a separate copy of the file with the requestor's name on the receipt — not from this warehouse.

**Operational.** Phase 2's first PR is a scaffold (this ADR + an empty pipeline directory + the model with no confidential fields + a schema file + a fixture-only test). No real voter data lives in the repo or in CI fixtures. When we do receive the file, it lives in `data/voter_file/` (gitignored) on the operator's laptop and on the production worker, nowhere else.

**Teaching.** This ADR is the long-form answer to "what's actually different about a civic-tech pipeline vs. a normal one." The answer isn't the tools — it's that the schema is partly *law*, the publication surface is partly *policy*, and the redaction model is partly *contract with the people in the dataset*. Most pipelines don't have those constraints. Most don't need to.

## Related

- [ADR-0001 — Architecture overview](0001-architecture-overview.md)
- [ADR-0002 — DuckDB as the warehouse](0002-duckdb-warehouse.md)
- [ADR-0003 — dlt for ingestion, Prefect for orchestration](0003-dlt-and-prefect.md)
- Forthcoming: ADR-0005 — Public API surface and the commercial-use prohibition
- [L09 — Who can change the warehouse](../teaching/LESSONS.md) (corrections workflow, the pattern this ADR extends)

## Sources

- Georgia Code § 21-2-225 — [Justia](https://law.justia.com/codes/georgia/title-21/chapter-2/article-6/section-21-2-225/)
- Georgia SOS County or Municipal District or Precinct Voter List — [product page](https://georgiasecretaryofstate.net/products/county-or-municipal-district-or-precinct-voter-list)
- UGA First Amendment Clinic, *Guide to Accessing Election Records in Georgia* (May 2024) — [PDF](https://firstamendment.law.uga.edu/wp-content/uploads/2024/05/FINAL-Election-Records-Resource.pdf)
- US Election Assistance Commission, *Availability of State Voter File and Confidential Information* — [PDF](https://www.eac.gov/sites/default/files/voters/Available_Voter_File_Information.pdf)
- Ballotpedia, *Availability of state voter files* — [overview](https://ballotpedia.org/Availability_of_state_voter_files)
- ACLU, *Nonpartisan Group Urges Court to Protect Georgians' Private Voter Data Seized in FBI Raid* (Feb 2026) — [press release](https://www.aclu.org/press-releases/nonpartisan-group-urges-court-to-protect-georgians-private-voter-data-seized-in-fbi-raid)
- NAACP, *NAACP Files Court Order to Protect Georgia Voters After Department of Justice Seizes Election Data* (Feb 2026) — [release](https://naacp.org/articles/naacp-files-court-order-protect-georgia-voters-after-department-justice-seizes-election)
- PBS NewsHour, *FBI raids Georgia elections office as Trump administration seeks voter data from states* (Jan 2026) — [coverage](https://www.pbs.org/newshour/show/fbi-raids-georgia-elections-office-as-trump-administration-seeks-voter-data-from-states)
