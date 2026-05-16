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
