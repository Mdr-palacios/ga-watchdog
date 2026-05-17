-- Cross-pipeline analytic view: SEB meetings ⋈ voter aggregates.
--
-- This is the surface ADR-0001 was written for: "what did the SEB
-- decide, and what changed on the ground after." It puts the two
-- pipelines next to each other in a single view so a civic researcher
-- can read SEB activity against the registered-voter landscape it
-- governs, without either pipeline having to know about the other.
--
-- Architectural rules (read these before editing):
--
-- 1. This file lives in `warehouse/queries/`, not `warehouse/schema/`.
--    See `warehouse/schema/seb.sql` line 4 and `warehouse/loader.py`
--    docstring on `apply_schema` for why. Schema files define one
--    pipeline's tables; this file composes views across pipelines.
--
-- 2. The join is *temporal + geographic*, never topical. SEB meetings
--    have free-text `key_decisions` and `controversies` columns — the
--    pipeline does not claim to know which county a specific decision
--    affected. So this view bins SEB activity by calendar quarter and
--    pairs every meeting-quarter row with every county's
--    registered-voter snapshot for that quarter. The researcher then
--    layers their own topical judgment on top.
--
-- 3. The voter side reads `voter.county_registration_summary`, which
--    in turn reads `voter.public_voters`. Per ADR-0004 Rule 4 we never
--    join on per-voter identifiers across pipelines — only on
--    aggregates. And because the chain bottoms out at `public_voters`,
--    suppressions cascade automatically: a voter who has filed a
--    suppression drops out of every cell in this view.
--
-- 4. The view ABSOLUTELY MAY NOT include any column that could be
--    used to re-identify an individual voter — no zip5, no birth_year
--    granular enough to combine with a small county, no precinct.
--    County and quarter are the geographic and temporal floor.
--
-- The view is read-only by construction (it's a view, not a table)
-- and is the canonical surface that Phase 2.4's public read API will
-- expose.

CREATE SCHEMA IF NOT EXISTS analytics;

-- Per-quarter SEB meeting rollup: counts of meetings by compliance
-- status. The bin is calendar quarter (e.g. '2024-Q1') because SEB
-- meets monthly and a quarter is a small enough window for a
-- researcher to read alongside a voter-registration snapshot without
-- the day-level noise of a single missed quorum.
CREATE OR REPLACE VIEW analytics.seb_meeting_quarter AS
SELECT
    year(meeting_date)                                              AS year,
    quarter(meeting_date)                                           AS quarter,
    compliance_status,
    COUNT(*)                                                        AS meeting_count,
    SUM(CASE WHEN quorum_met = 'Yes' THEN 1 ELSE 0 END)             AS quorum_met_count,
    SUM(CASE WHEN controversies IS NOT NULL
                  AND TRIM(controversies) <> ''
                  AND TRIM(controversies) <> 'None'
             THEN 1 ELSE 0 END)                                     AS controversy_meeting_count
FROM seb.meetings
GROUP BY year, quarter, compliance_status;

-- Cross-pipeline view: for every (year, quarter, county) cell, surface
-- SEB activity that quarter and the voter-registration shape of that
-- county.
--
-- This is intentionally a denormalized cross-join: meeting activity is
-- statewide (the SEB governs all 159 counties), so every county-quarter
-- row pairs with every SEB compliance-status bucket for that quarter.
-- The result is a long table a researcher can filter on
-- `compliance_status <> 'Clean'` to read which counties had what
-- registration shape during a quarter the board flagged something.
--
-- Causality is not claimed here. The two columns sit next to each
-- other; the researcher is responsible for the inference.
CREATE OR REPLACE VIEW analytics.seb_voter_overlap AS
WITH voter_q AS (
    -- Voter aggregates are point-in-time (a registration snapshot has
    -- no quarter of its own), so we attach the SAME aggregate to every
    -- quarter where SEB activity exists. A future iteration could
    -- snapshot the voter file quarterly; for now the registration side
    -- is a single point and the meetings side is the time series.
    SELECT
        county,
        status,
        voter_count,
        distinct_zip5_count
    FROM voter.county_registration_summary
),
seb_q AS (
    SELECT
        year,
        quarter,
        compliance_status,
        meeting_count,
        quorum_met_count,
        controversy_meeting_count
    FROM analytics.seb_meeting_quarter
)
SELECT
    s.year,
    s.quarter,
    v.county,
    v.status                      AS voter_status,
    v.voter_count,
    v.distinct_zip5_count,
    s.compliance_status,
    s.meeting_count,
    s.quorum_met_count,
    s.controversy_meeting_count
FROM seb_q s
CROSS JOIN voter_q v;
