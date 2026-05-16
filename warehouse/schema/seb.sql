-- SEB warehouse schema
--
-- One file = one pipeline's slice of the warehouse. Cross-pipeline
-- joins live in `warehouse/queries/`, never inside a schema file.
--
-- Idempotent on purpose. The ingest flow applies this on every run.

CREATE SCHEMA IF NOT EXISTS seb;

-- Canonical meeting records. Mirrors `transforms/models.Meeting`.
-- If you change one, change both, and add an ADR if the change is
-- breaking (column removed, type changed, semantics flipped).
CREATE TABLE IF NOT EXISTS seb.meetings (
    meeting_id        INTEGER PRIMARY KEY,
    meeting_date      DATE        NOT NULL,
    day_of_week       VARCHAR(3)  NOT NULL,
    meeting_type      VARCHAR     NOT NULL,
    meeting_format    VARCHAR     NOT NULL,
    chair             VARCHAR     NOT NULL,
    members_present   VARCHAR     NOT NULL,
    quorum_met        VARCHAR     NOT NULL,
    agenda_summary    TEXT,
    key_decisions     TEXT,
    video_url         VARCHAR,
    source_url        VARCHAR,
    compliance_status VARCHAR     NOT NULL DEFAULT 'Unreviewed',
    compliance_notes  TEXT,
    controversies     TEXT,
    hours_logged      DOUBLE
        CHECK (hours_logged IS NULL OR (hours_logged >= 0 AND hours_logged <= 24)),
    -- pipeline metadata
    loaded_at         TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source            VARCHAR     NOT NULL DEFAULT 'manual'
);

-- Video records — many videos may attach to one meeting (Day 1, Day 2,
-- separate executive session). Kept distinct so we can store transcripts
-- and per-video metadata without polluting the meeting record.
CREATE TABLE IF NOT EXISTS seb.videos (
    video_id          VARCHAR PRIMARY KEY,
    meeting_id        INTEGER REFERENCES seb.meetings(meeting_id),
    video_url         VARCHAR NOT NULL,
    title             VARCHAR NOT NULL,
    published_date    DATE,
    description       TEXT,
    transcript        TEXT,
    transcript_source VARCHAR,
    loaded_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Controversies — many-to-many with meetings via a free-text field in
-- `seb.meetings` for now (Phase 1 keeps qualitative data simple). When
-- we promote controversies to a typed model, this table gets a join
-- table and the meeting-level `controversies` column gets deprecated.
CREATE TABLE IF NOT EXISTS seb.controversies (
    controversy_id    INTEGER PRIMARY KEY,
    title             VARCHAR NOT NULL,
    first_seen_date   DATE,
    status            VARCHAR NOT NULL,  -- 'Active' | 'Resolved' | 'Monitoring'
    description       TEXT,
    latest_action     TEXT,
    primary_source    VARCHAR,
    loaded_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Sources — citation register. Stable surface for the digest emitter
-- to render "according to {source}" footnotes.
CREATE TABLE IF NOT EXISTS seb.sources (
    source_id         INTEGER PRIMARY KEY,
    name              VARCHAR NOT NULL,
    source_type       VARCHAR NOT NULL,  -- 'Primary' | 'Watchdog' | 'Civil Rights' | 'News' | 'Statute'
    url               VARCHAR NOT NULL,
    notes             TEXT
);
