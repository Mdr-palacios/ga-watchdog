-- Voter file warehouse schema (Phase 2 scaffold).
--
-- This schema is constrained by O.C.G.A. § 21-2-225, not just by
-- engineering taste. Read docs/adr/0004-voter-file-sources-and-ethics.md
-- before changing any column here.
--
-- Two invariants, enforced at this layer because SQL is the right place
-- to make statutory promises:
--
-- 1. Confidential fields named in § 21-2-225(b) DO NOT EXIST in this
--    schema. No SSN column. No driver's-license column. No email
--    column. No month/day of birth column. No registration-location
--    column. A column that does not exist cannot be accidentally
--    SELECTed by a buggy public endpoint.
--
-- 2. `birth_year` is INTEGER, not part of a DATE. The bulk-file source
--    pulls the year off the source's date-of-birth column and discards
--    the rest before any record reaches the warehouse.
--
-- The structure mirrors `pipelines/voter_file/transforms/models.Voter`.
-- If you change one, change both, and add an ADR if the change is
-- breaking.

CREATE SCHEMA IF NOT EXISTS voter;

-- Per-voter records, with statutorily-public fields only.
CREATE TABLE IF NOT EXISTS voter.voters (
    voter_id              INTEGER PRIMARY KEY,
    first_name            VARCHAR NOT NULL,
    middle_name           VARCHAR,
    last_name             VARCHAR NOT NULL,
    name_suffix           VARCHAR,

    -- Year only. Month and day are confidential under § 21-2-225(b).
    birth_year            INTEGER
        CHECK (birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100)),

    -- Residence address (public under the statute). Stored as parts so
    -- aggregations to precinct/zip don't require re-parsing.
    residence_house_number VARCHAR,
    residence_street_name  VARCHAR,
    residence_apartment    VARCHAR,
    residence_city         VARCHAR,
    residence_zip5         VARCHAR
        CHECK (residence_zip5 IS NULL OR length(residence_zip5) = 5),

    -- Demographics (public). Labels are whatever the SOS ships; we do
    -- not relabel.
    race                  VARCHAR,
    gender                VARCHAR,

    -- Registration + voting history surface that the SOS ships.
    registration_date     DATE,
    last_voted_date       DATE,
    status                VARCHAR NOT NULL DEFAULT 'Active',

    -- Geography (public).
    county                VARCHAR,
    precinct              VARCHAR,

    -- Pipeline metadata. `source` is the named acquisition channel
    -- (e.g. 'sos_statewide_2026q2'), not a URL — see ADR-0004 Rule 3.
    loaded_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source                VARCHAR   NOT NULL DEFAULT 'unknown'
);

-- Suppressions — append-only audit log of "filter this voter from
-- public outputs" requests. Same shape as seb.meeting_corrections
-- (see L09): a request is YAML, reviewed in a PR, logged here on
-- apply, never UPDATEd or DELETEd. To reverse a suppression, write a
-- new entry with action='unsuppress' that references the prior id.
CREATE TABLE IF NOT EXISTS voter.suppressions (
    suppression_id   VARCHAR PRIMARY KEY,
    voter_id         INTEGER NOT NULL REFERENCES voter.voters(voter_id),
    action           VARCHAR NOT NULL,
    reason           TEXT    NOT NULL,
    requested_by     VARCHAR NOT NULL,
    supersedes       VARCHAR REFERENCES voter.suppressions(suppression_id),
    requested_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT voter_suppressions_action_known
        CHECK (action IN ('suppress', 'unsuppress'))
);

-- Convenience view: the currently-effective suppression set. A voter
-- is filtered out of public outputs iff their most recent suppressions
-- row has action='suppress'.
CREATE OR REPLACE VIEW voter.active_suppressions AS
SELECT
    voter_id,
    LAST(suppression_id ORDER BY requested_at) AS suppression_id,
    LAST(action ORDER BY requested_at)         AS action,
    LAST(requested_at ORDER BY requested_at)   AS requested_at
FROM voter.suppressions
GROUP BY voter_id
HAVING LAST(action ORDER BY requested_at) = 'suppress';

-- Public-safe surface: every voter NOT currently suppressed.
--
-- THIS is the view any public output, public endpoint, or
-- cross-pipeline join must read from. Reading `voter.voters` directly
-- in a public context is a bug — it bypasses the filter the voter
-- explicitly requested. Phase 2.4's public read API will be wired
-- against this view, not the underlying table.
--
-- The underlying record stays intact in `voter.voters`: we owe the
-- voter a filter, not a rewrite of their record. The suppressions
-- audit log is the contract.
CREATE OR REPLACE VIEW voter.public_voters AS
SELECT v.*
FROM voter.voters v
WHERE NOT EXISTS (
    SELECT 1
    FROM voter.active_suppressions s
    WHERE s.voter_id = v.voter_id
);

-- ------------------------------------------------------------------
-- Aggregate views: the only surfaces a public output should read.
--
-- These are the views ADR-0004 Rule 4 says we publish (county-level,
-- precinct-level, status-level rollups), as opposed to per-voter rows.
-- Cross-pipeline analytic views in `warehouse/queries/` must compose
-- THESE views, never `voter.voters` directly — that keeps suppressions
-- cascading and keeps the join key away from per-voter granularity.
--
-- All aggregate views read from `voter.public_voters` (NOT
-- `voter.voters`) so any voter who has filed a suppression drops out
-- of every count automatically.
-- ------------------------------------------------------------------

-- County-level registration summary, broken out by status.
-- Counts of GA counties are in the millions, so per-county counts do
-- not raise re-identification concerns even at fine status splits.
CREATE OR REPLACE VIEW voter.county_registration_summary AS
SELECT
    county,
    status,
    COUNT(*)                            AS voter_count,
    COUNT(DISTINCT residence_zip5)      AS distinct_zip5_count,
    MIN(birth_year)                     AS earliest_birth_year,
    MAX(birth_year)                     AS latest_birth_year
FROM voter.public_voters
WHERE county IS NOT NULL
GROUP BY county, status;

-- Precinct-level registration summary, with minimum-cell-size
-- suppression. The smallest GA precincts have well under 100
-- registered voters; an unguarded per-precinct, per-status count would
-- give a third party a small enough cohort to deanonymize against
-- another dataset. ADR-0004 Rule 4 forbids that.
--
-- Cells with fewer than the threshold are kept in the view (so totals
-- still balance) but voter_count is NULL and `suppressed_for_size` is
-- TRUE. The threshold lives here and is referenced by the test suite;
-- changing it requires changing both, which forces an explicit code
-- review of the privacy posture.
CREATE OR REPLACE VIEW voter.precinct_registration_summary AS
WITH raw AS (
    SELECT
        county,
        precinct,
        status,
        COUNT(*) AS raw_count
    FROM voter.public_voters
    WHERE precinct IS NOT NULL
    GROUP BY county, precinct, status
)
SELECT
    county,
    precinct,
    status,
    CASE WHEN raw_count < 25 THEN NULL ELSE raw_count END AS voter_count,
    raw_count < 25                                        AS suppressed_for_size
FROM raw;
