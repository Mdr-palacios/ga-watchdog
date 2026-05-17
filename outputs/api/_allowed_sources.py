"""Public-API source allow-list.

This module is half of the two-layer enforcement described in ADR-0005,
decision 2. The SQL view chain (ADR-0004 + L09c) is the other half.

Every read in `outputs/api/routes/` MUST hit one of the fully-qualified
table or view names in `ALLOWED_PUBLIC_SOURCES`. Adding a name here is
itself the auditable event: a PR that touches this file is reviewed
against ADR-0005 and ADR-0004, and `test_allowed_sources_match_adr` in
`tests/test_api_allowed_sources.py` pins the list so silent additions
break the build.

Rules baked in below:

1. `voter.voters` is NOT here. Per ADR-0004 the per-voter table holds
   rows the public surface must not return. Public reads go through
   `voter.public_voters` or aggregates downstream of it.
2. `voter.suppressions` is NOT here. The audit log is internal-only.
   The public sees suppressions as missing rows, never as their fact.
3. `voter.precinct_registration_summary` is NOT here. Precinct + small
   county is a re-identification vector per ADR-0004 Rule 4. Precinct
   data is held; only county and statewide aggregates are published.
4. `seb.meeting_corrections` is NOT here. The corrections audit log
   is the same shape as suppressions and follows the same rule: the
   effect (a corrected value in `seb.meetings`) is public, the
   reasoning artifact is internal-only.
"""

from __future__ import annotations

# Fully-qualified `schema.name` strings. Sorted alphabetically because
# the diff is the point: when you add a row, the diff is one line and
# it lands at a predictable spot. Do not group by route or by pipeline
# — group by name so review is mechanical.
ALLOWED_PUBLIC_SOURCES: frozenset[str] = frozenset(
    {
        "analytics.seb_voter_overlap",
        "seb.controversies",
        "seb.meetings",
        "seb.sources",
        "seb.videos",
        "voter.county_registration_summary",
    }
)


# Sources that must NEVER be queried from `outputs/api/`. This is
# belt-and-suspenders next to the allow-list: a contributor who
# accidentally writes `FROM voter.voters` in a route handler hits two
# tests — the allow-list test (because the source isn't allowed) and
# this denial test (because the source is named explicitly). The two
# tests have different failure messages so the contributor sees both
# "you used an unallowed source" and "you used a source we have
# specifically forbidden, here is why."
EXPLICITLY_DENIED_SOURCES: frozenset[str] = frozenset(
    {
        "voter.voters",  # per-voter table; ADR-0004 Rule 1.
        "voter.suppressions",  # audit log; ADR-0005 §1 out-of-scope.
        "voter.active_suppressions",  # internal helper view over suppressions.
        "voter.precinct_registration_summary",  # re-id vector; ADR-0004 Rule 4.
        "seb.meeting_corrections",  # internal audit log; ADR-0005 §1.
    }
)


def is_allowed(source: str) -> bool:
    """Return True iff `source` is in the public allow-list.

    `source` should be the fully-qualified `schema.name` exactly as it
    appears in the SQL FROM clause. Case-sensitive — DuckDB is.
    """
    return source in ALLOWED_PUBLIC_SOURCES


def is_denied(source: str) -> bool:
    """Return True iff `source` is in the explicit denial list."""
    return source in EXPLICITLY_DENIED_SOURCES
