"""Canonical model for a single voter-file record.

The shape of this file is deliberately constrained by Georgia law, not
just by engineering taste. Read ADR-0004 before changing it.

Two invariants, both enforced here at the model layer because the
schema layer is the right place to make statutory promises:

1. **Confidential fields do not exist on this model.**
   O.C.G.A. § 21-2-225(b) names month + day of birth, SSN, driver's
   license number, email address, and registration location as
   confidential. None of those fields exist on `Voter`. If a source
   ever delivers a record containing them, `extra="forbid"` raises
   ValidationError at the record boundary, *before* the record can
   land in DuckDB.

2. **Year of birth, not date of birth.**
   The statute makes year of birth public and month + day confidential.
   `Voter` exposes `birth_year` as an int — there is no `birth_date`
   field. The bulk-file reader is responsible for pulling the year off
   the source's date column and discarding the rest before it
   constructs a `Voter`.

The qualitative columns the SEB pipeline uses (controversies, key
decisions, compliance notes) do not apply here — a voter file row is
factual, not editorial. The judgment layer in this pipeline lives
elsewhere: in the suppressions workflow (Rule 5) and the public output
surface (Rule 4), not in fields on this model.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# The statute's confidential-field list, kept here as code so the test
# suite can iterate it and prove that no Voter instance can be
# constructed with any of these names.
#
# Order matches the order in O.C.G.A. § 21-2-225(b). If the statute
# changes, this list is the single point of update.
STATUTORY_CONFIDENTIAL_FIELDS: frozenset[str] = frozenset(
    {
        "birth_month",
        "birth_day",
        "birth_date",  # full date is *implicitly* confidential; year only is allowed
        "date_of_birth",  # common alias seen in upstream files
        "dob",  # common alias
        "ssn",
        "social_security_number",
        "dl_number",
        "drivers_license",
        "drivers_license_number",
        "email",
        "email_address",
        "registration_location",  # "the locations at which the electors applied to register"
    }
)


class VoterStatus(StrEnum):
    """Registration status — values mirror what the SOS bulk file ships.

    The exact label set will be finalized when the bulk-file reader
    lands. Treat this enum as a placeholder anchored in the known
    common values; new values trigger an explicit decision (and ADR
    amendment if the meaning changes).
    """

    ACTIVE = "Active"
    INACTIVE = "Inactive"
    PENDING = "Pending"
    CANCELLED = "Cancelled"


class Voter(BaseModel):
    """One voter record, as it lands in the warehouse.

    Schema is intentionally narrow. Every field here is either:
      (a) made public by O.C.G.A. § 21-2-225(b), or
      (b) a pipeline-metadata field (`source`, `loaded_at`) generated
          on our side, not from the voter record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    voter_id: int = Field(
        ...,
        description=(
            "Stable identifier from the SOS bulk file. We don't generate "
            "this — we adopt whatever the SOS uses, so cross-referencing "
            "with other public datasets (election history, etc.) works."
        ),
    )
    first_name: str
    middle_name: str | None = None
    last_name: str
    name_suffix: str | None = None

    # Year of birth ONLY. The bulk-file reader strips month + day before
    # constructing a Voter. See models.STATUTORY_CONFIDENTIAL_FIELDS and
    # ADR-0004 Rule 2.
    birth_year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Year of birth. Month and day are statutorily confidential and not stored.",
    )

    # Address — public under the statute. Stored as parts, not a single
    # string, so the warehouse can aggregate to precinct/zip without
    # needing to re-parse.
    residence_house_number: str | None = None
    residence_street_name: str | None = None
    residence_apartment: str | None = None
    residence_city: str | None = None
    residence_zip5: str | None = Field(default=None, pattern=r"^\d{5}$")

    # Demographics — public under the statute. Race and gender labels
    # follow the SOS's own enumeration; we do not relabel.
    race: str | None = None
    gender: str | None = None

    # Registration + voting history surface that the SOS ships.
    registration_date: date | None = None
    last_voted_date: date | None = None
    status: VoterStatus = VoterStatus.ACTIVE

    # Geography — public.
    county: str | None = None
    precinct: str | None = None

    @classmethod
    def confidential_field_names(cls) -> frozenset[str]:
        """The statute's confidential-field list. Public for tests."""
        return STATUTORY_CONFIDENTIAL_FIELDS
