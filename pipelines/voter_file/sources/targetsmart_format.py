"""Reader for TargetSmart-shaped voter files (public-only subset).

TargetSmart is a commercial voter-file vendor. Some civic-tech partners
hold TargetSmart licenses and share files with us; this reader exists so
we can read those files when they're handed to us, without ever
ingesting TargetSmart's licensed, modeled, or commercially-enriched
columns.

Three independent boundaries are enforced at header time, before a
single row is constructed:

1. **Statutorily-confidential columns must not appear.** Same rule as
   the SOS reader. If `voterbase_dob`, `dob`, etc. appear, we raise
   `ConfidentialColumnError`. See ADR-0004 Rule 1.

2. **TargetSmart-licensed / modeled / enriched columns must not appear.**
   These are columns the data dictionary marks as derived from
   commercial sources, modeled, or as Democratic-party-aligned scores.
   Even though some of them (like age) might look innocent, ingesting
   them would either (a) leak DOB by reverse arithmetic, (b) launder
   commercial data into a tool we tell users is statute-only, or
   (c) carry vendor IP that the license forbids us from redistributing.
   We raise `LicensedColumnError` (distinct exception from
   `ConfidentialColumnError`) so the operator can tell at a glance
   which boundary tripped and decide whether to request a clean export
   from the partner.

3. **Unknown columns pass through, silently ignored.** Same posture as
   the SOS reader — the file surface is allowed to drift; only the
   Voter shape is locked.

Column mapping is anchored at the top of the file so the TargetSmart-
to-model translation table is auditable in one place. The mapped set is
deliberately a strict subset of the data dictionary — every column we
consume here maps cleanly back to information that
O.C.G.A. § 21-2-225(b) makes public on its own. If the dictionary adds
a new column we want to consume, the decision (public vs licensed) is
made *here*, not in the model.

NOTES ON SPECIFIC OMISSIONS
---------------------------

  - `voterbase_age`: the data dictionary marks this as derived from
    `voterbase_dob`, which is "multi-sourced from the voter file and
    commercial sources". Storing age effectively stores derivable DOB,
    which violates ADR-0004 Rule 2. **Refused.** Use the SOS file's
    `Year_of_Birth` column via the SOS reader if you need a birth-year
    field.
  - `voterbase_race`, `voterbase_gender`: dictionary says
    "multi-sourced (voter file, or commercially-appended)". The
    statutorily-public race and gender values are available directly
    from the SOS file; we do not accept the TargetSmart-blended
    versions. **Refused.**
  - `tsmart_partisan_score`, `tsmart_*_score`: these are TargetSmart's
    own models (Democratic-aligned vendor; the scores reflect a target
    audience definition we don't share). **Refused.**
  - `reg_latitude`, `reg_longitude`: geocoded residence. The street
    address is statutorily public; the geocode is a privacy
    intensifier and not necessary for our aggregation use cases.
    **Refused.**
  - `tsmart_*` cleaned-address variants (e.g. `tsmart_full_address`):
    duplicates of `vf_reg_address*`, with vendor IP layered in.
    **Refused.** We consume `vf_reg_address1` / `vf_reg_address2`
    directly.
  - `voterbase_phone_*` flags: commercial-enrichment indicators that
    say nothing public. **Refused.**

If you find this list incomplete, that's a real problem — *add the
missing column to `TARGETSMART_LICENSED_FIELDS` and write the test.*
The reader's contract is "we refuse all non-public columns we know
about"; a missed column undermines the entire premise.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from pipelines.voter_file.transforms.models import (
    STATUTORY_CONFIDENTIAL_FIELDS,
    Voter,
    VoterStatus,
)

# ---------------------------------------------------------------------------
# Boundary #2: TargetSmart-licensed / modeled / enriched columns.
#
# The reader refuses files that contain ANY of these column names. The
# list is intentionally explicit (no wildcards) so the boundary is
# auditable. Source: TargetSmart GA Data Dictionary (`ga_sample_data_
# dictionary_20230304.pdf`, attached during Phase 2.1b).
# ---------------------------------------------------------------------------

TARGETSMART_LICENSED_FIELDS: frozenset[str] = frozenset(
    {
        # Derived from DOB → would leak DOB. ADR-0004 Rule 2.
        "voterbase_age",
        "voterbase_dob",
        # Multi-sourced (voter file + commercial). Refuse the blended
        # version; we accept SOS-direct race/gender via the SOS reader.
        "voterbase_race",
        "voterbase_gender",
        # Commercial enrichment flags — say nothing public.
        "voterbase_phone",
        "voterbase_phone_presence_flag",
        "voterbase_phone_wireless_flag",
        "voterbase_email",
        "voterbase_email_presence_flag",
        # TargetSmart-proprietary modeled scores. Democratic-aligned
        # vendor; storing these would launder vendor IP into a tool
        # we tell users is statute-only.
        "tsmart_partisan_score",
        "tsmart_presidential_general_turnout_score",
        "tsmart_midterm_general_turnout_score",
        "tsmart_local_voter_score",
        "tsmart_path_to_progressive_score",
        "tsmart_trump_resistance_score",
        # Geocoded residence — privacy intensifier beyond the public
        # street address.
        "reg_latitude",
        "reg_longitude",
        "tsmart_latitude",
        "tsmart_longitude",
        # tsmart_* cleaned-address variants. The vf_reg_address* fields
        # carry the same information; the tsmart_* versions have vendor
        # IP (CASS-certification-derived corrections) layered in.
        "tsmart_full_address",
        "tsmart_address1",
        "tsmart_address2",
        "tsmart_city",
        "tsmart_state",
        "tsmart_zip",
        "tsmart_zip4",
    }
)


# ---------------------------------------------------------------------------
# Column mapping: TargetSmart file header → Voter field name.
#
# Only the columns Voter consumes appear here. Everything else in the
# TargetSmart file that ISN'T on the licensed-refusal list passes
# through the reader silently (see iter_voters).
# ---------------------------------------------------------------------------

TS_TO_VOTER_FIELD: dict[str, str] = {
    "voterbase_id": "_voterbase_id",  # special: parsed to int
    "tsmart_first_name": "first_name",
    "tsmart_middle_name": "middle_name",
    "tsmart_last_name": "last_name",
    "vf_reg_address1": "_composed_address1",  # split into house# / street
    "vf_reg_address2": "residence_apartment",
    "vf_reg_city": "residence_city",
    "vf_reg_zip": "residence_zip5",
    "vf_county_name": "county",
    "vf_precinct_name": "precinct",
    "vf_voter_status": "_status_label",
}

# TargetSmart's voter_status labels are friendlier than the SOS's
# single-letter codes; map directly to the model enum.
_STATUS_LABEL_MAP: dict[str, VoterStatus] = {
    "ACTIVE": VoterStatus.ACTIVE,
    "INACTIVE": VoterStatus.INACTIVE,
    "PENDING": VoterStatus.PENDING,
    "PURGED": VoterStatus.CANCELLED,  # TargetSmart calls it PURGED; we map.
    "CANCELLED": VoterStatus.CANCELLED,
}


class TargetSmartFileError(Exception):
    """Base for all TargetSmart reader errors."""


class ConfidentialColumnError(TargetSmartFileError):
    """The file contains a column the statute makes confidential."""


class LicensedColumnError(TargetSmartFileError):
    """The file contains a TargetSmart-licensed / modeled / enriched column.

    Refused at header time. The operator should request a clean export
    from the partner that strips these columns before retrying.
    """


class UnknownStatusLabelError(TargetSmartFileError):
    """The file contains a vf_voter_status value we don't know how to map."""


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def _normalize_header(name: str) -> str:
    """TargetSmart headers are already lowercase + underscore-separated.

    Still, normalize defensively so a casing change in a future export
    doesn't bypass the refusal lists.
    """
    return "_".join(name.lower().replace("-", " ").split())


def _check_no_confidential_columns(headers: list[str]) -> None:
    """Raise if any header matches the statute's confidential list."""
    seen = {_normalize_header(h) for h in headers}
    offenders = sorted(seen & STATUTORY_CONFIDENTIAL_FIELDS)
    if offenders:
        raise ConfidentialColumnError(
            f"Refusing to read TargetSmart file: contains statutorily-"
            f"confidential column(s) {offenders!r}. See ADR-0004 Rule 1."
        )


def _check_no_licensed_columns(headers: list[str]) -> None:
    """Raise if any header matches the TargetSmart-licensed refusal list."""
    seen = {_normalize_header(h) for h in headers}
    offenders = sorted(seen & TARGETSMART_LICENSED_FIELDS)
    if offenders:
        raise LicensedColumnError(
            f"Refusing to read TargetSmart file: contains licensed / "
            f"modeled / commercially-enriched column(s) {offenders!r}. "
            f"Request a clean export with only statutorily-public "
            f"columns from your TargetSmart-licensed partner. See "
            f"pipelines/voter_file/sources/targetsmart_format.py and "
            f"ADR-0004."
        )


def _parse_voterbase_id(value: str) -> int:
    """Parse a synthetic-fixture voterbase_id like 'TS009000000' to int.

    Real TargetSmart voterbase_ids are 32-char hex; for the synthetic
    fixture we use the 'TS' prefix + a digit suffix that we strip.
    Production use against a real TargetSmart file would either
    (a) change the Voter model's voter_id type, or (b) hash the
    voterbase_id to an int. We defer that decision until we actually
    have a real file in hand.
    """
    value = value.strip()
    if value.upper().startswith("TS") and value[2:].isdigit():
        return int(value[2:])
    if value.isdigit():
        return int(value)
    raise TargetSmartFileError(
        f"voterbase_id {value!r} not in supported synthetic-fixture form "
        "(expected 'TS' + digits, or all digits)"
    )


def _split_address1(line: str) -> tuple[str | None, str | None]:
    """Split a TargetSmart `vf_reg_address1` line into (house_number, street).

    The dictionary documents the line as `<house_number> <street_name>
    <suffix>`. We split on the first whitespace; the street side keeps
    name + suffix together (matching how the SOS reader composes them).
    Blanks → (None, None).
    """
    line = line.strip()
    if not line:
        return None, None
    parts = line.split(maxsplit=1)
    if len(parts) == 1:
        # No house number — just a street name.
        return None, parts[0]
    house, rest = parts
    if not house.isdigit():
        # First token isn't a number → treat the whole line as street.
        return None, line
    return house, rest


def _to_voter_status(label: str) -> VoterStatus:
    label = label.strip().upper()
    if not label:
        return VoterStatus.ACTIVE
    if label in _STATUS_LABEL_MAP:
        return _STATUS_LABEL_MAP[label]
    raise UnknownStatusLabelError(
        f"unknown vf_voter_status label {label!r}; "
        "extend _STATUS_LABEL_MAP in targetsmart_format.py"
    )


def iter_voters(path: Path | str) -> Iterator[Voter]:
    """Yield `Voter` records from a TargetSmart-shaped CSV at `path`.

    The reader:
      - Refuses files containing statutorily-confidential columns
        (`ConfidentialColumnError`).
      - Refuses files containing TargetSmart-licensed / modeled /
        enriched columns (`LicensedColumnError`).
      - Ignores unknown columns silently.
      - Raises on any row that fails Pydantic validation.

    Default-strict behavior matches the SOS reader: if anything
    surprising appears, fail loudly with the offending row visible.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise TargetSmartFileError(f"TargetSmart file {p} appears to have no header row")

        normalized_headers = [_normalize_header(h) for h in reader.fieldnames]
        _check_no_confidential_columns(normalized_headers)
        _check_no_licensed_columns(normalized_headers)

        for row_index, raw_row in enumerate(reader, start=2):  # row 1 is header
            row = {_normalize_header(k): (v or "").strip() for k, v in raw_row.items()}

            kwargs: dict[str, object] = {}
            for ts_col, voter_field in TS_TO_VOTER_FIELD.items():
                if ts_col not in row:
                    continue
                value = row[ts_col]

                if voter_field == "_voterbase_id":
                    kwargs["voter_id"] = _parse_voterbase_id(value)
                    continue
                if voter_field == "_composed_address1":
                    house, street = _split_address1(value)
                    if house is not None:
                        kwargs["residence_house_number"] = house
                    if street is not None:
                        kwargs["residence_street_name"] = street
                    continue
                if voter_field == "_status_label":
                    kwargs["status"] = _to_voter_status(value)
                    continue

                # Generic by field name.
                if voter_field == "residence_zip5":
                    kwargs["residence_zip5"] = value.zfill(5) if value else None
                elif voter_field == "county":
                    # TargetSmart ships county name in ALL CAPS; the SOS
                    # reader produces title-case (mapped from a numeric
                    # code). Normalize for downstream consistency.
                    kwargs["county"] = value.title() if value else None
                else:
                    kwargs[voter_field] = value or None

            try:
                yield Voter(**kwargs)
            except Exception as exc:
                raise TargetSmartFileError(
                    f"TargetSmart file {p} row {row_index} failed validation: {exc}"
                ) from exc
