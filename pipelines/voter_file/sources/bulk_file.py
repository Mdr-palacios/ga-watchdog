"""Bulk SOS-file reader.

This module reads a Georgia Secretary of State statewide voter file from
the **local filesystem** and yields `Voter` records. It does not, and
will not, fetch the file over HTTP. The operator pays the $250 statutory
fee, the SOS delivers the file, and a human places it under
`data/voter_file/` on the production worker. See ADR-0004 Rule 3.

Three things this reader enforces, in addition to model validation:

1. **Statutorily-confidential columns must not appear.** If the file
   contains a column whose normalized name matches anything in
   `STATUTORY_CONFIDENTIAL_FIELDS`, parsing stops with a
   `ConfidentialColumnError` *before* a single row is constructed.
   The Voter model would refuse the row anyway via `extra="forbid"`,
   but failing at header time gives the operator a louder, earlier
   signal: "this file should not have been delivered to us."

2. **Year of birth, never full date.** If the file ships a full DOB
   column (`Date_of_Birth`, `DOB`, etc.), the reader treats that as a
   confidential column and refuses (#1 covers this). The expected
   column is `Year_of_Birth`, integer.

3. **Unknown columns pass through, silently ignored.** The real SOS
   file has dozens of district columns we don't currently consume.
   The reader maps the columns it knows about and discards the rest.
   This is the opposite of the model's `extra="forbid"` — the file
   surface is allowed to drift, only the *Voter shape* is locked.

Column mapping is anchored at the top of the file so the SOS-to-model
translation table is auditable in one place.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Iterator
from pathlib import Path

from pipelines.voter_file.transforms.models import (
    STATUTORY_CONFIDENTIAL_FIELDS,
    Voter,
    VoterStatus,
)

# ---------------------------------------------------------------------------
# Column mapping: SOS file header → Voter field name.
#
# Source for the SOS column names:
#   https://github.com/Voteshield/reggie/blob/main/reggie/configs/data/georgia.yaml
#
# Only the columns Voter consumes appear here. Everything else in the
# SOS file passes through the reader silently (see iter_voters).
# ---------------------------------------------------------------------------

SOS_TO_VOTER_FIELD: dict[str, str] = {
    "registration_number": "voter_id",
    "first_name": "first_name",
    "middle_maiden_name": "middle_name",
    "last_name": "last_name",
    "name_suffix": "name_suffix",
    "year_of_birth": "birth_year",
    "residence_house_number": "residence_house_number",
    "residence_street_name": "residence_street_name",
    "residence_apt_unit_nbr": "residence_apartment",
    "residence_city": "residence_city",
    "residence_zipcode": "residence_zip5",
    "race": "race",
    "gender": "gender",
    "registration_date": "registration_date",
    "date_last_voted": "last_voted_date",
    "voter_status": "_status_code",  # handled specially — see _to_voter_status
    "county_code": "_county_code",  # handled specially — see _county_lookup
    "county_precinct_id": "precinct",
}

# SOS ships `Residence_street_suffix` as a separate column. We append it
# onto `residence_street_name` rather than carrying a separate field,
# because the warehouse stores a single canonical street-name string.
SOS_STREET_SUFFIX_COLUMN = "residence_street_suffix"

# SOS uses single-letter status codes; we map to the friendlier enum.
_STATUS_CODE_MAP: dict[str, VoterStatus] = {
    "A": VoterStatus.ACTIVE,
    "I": VoterStatus.INACTIVE,
    "P": VoterStatus.PENDING,
    "C": VoterStatus.CANCELLED,
}

# SOS uses numeric county codes; the GA SOS publishes the lookup table.
# We carry the codes we use in the synthetic fixture; the production
# loader will extend this from the SOS reference list.
# Source: https://sos.ga.gov/ — county code list (county number ↔ name).
_COUNTY_CODE_MAP: dict[str, str] = {
    "11": "Bibb",
    "25": "Chatham",
    "29": "Clarke",
    "44": "DeKalb",
    "60": "Fulton",
    "106": "Muscogee",
    "121": "Richmond",
}


class BulkFileError(Exception):
    """Base for all reader-level errors."""


class ConfidentialColumnError(BulkFileError):
    """The file contains a column the statute makes confidential.

    Raised at header time, before any record is constructed. Stops the
    pipeline so a human can decide whether the file should be
    re-requested or returned to the SOS.
    """


class UnknownStatusCodeError(BulkFileError):
    """The file contains a voter_status code we don't know how to map."""


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def _normalize_header(name: str) -> str:
    """SOS headers have mixed case and one stray space (`Ward city council_code`).

    Normalize to lowercase, replace runs of whitespace + hyphens with
    underscores, so the mapping table can use a single canonical form.
    """
    return "_".join(name.lower().replace("-", " ").split())


def _check_no_confidential_columns(headers: list[str]) -> None:
    """Raise if any header matches the statute's confidential list."""
    seen = {_normalize_header(h) for h in headers}
    offenders = sorted(seen & STATUTORY_CONFIDENTIAL_FIELDS)
    if offenders:
        raise ConfidentialColumnError(
            f"Refusing to read voter file: contains statutorily-confidential "
            f"column(s) {offenders!r}. See ADR-0004 Rule 1."
        )


def _coerce_int(value: str) -> int | None:
    """Parse an int that may be blank. Returns None for empty/blank input."""
    value = value.strip()
    if not value:
        return None
    return int(value)


def _coerce_date(value: str) -> dt.date | None:
    """Parse a date in any of the SOS-shipped formats. Blank → None.

    The SOS YAML config lists three formats: '%Y%m%d', '%m/%d/%Y', '%Y'.
    We try each in order.
    """
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y%m%d", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"could not parse date from value {value!r}")


def _to_voter_status(code: str) -> VoterStatus:
    code = code.strip().upper()
    if code in _STATUS_CODE_MAP:
        return _STATUS_CODE_MAP[code]
    raise UnknownStatusCodeError(
        f"unknown voter_status code {code!r}; extend _STATUS_CODE_MAP in bulk_file.py"
    )


def _county_lookup(code: str) -> str | None:
    return _COUNTY_CODE_MAP.get(code.strip()) or None


def iter_voters(path: Path | str) -> Iterator[Voter]:
    """Yield `Voter` records from a SOS-format CSV at `path`.

    The reader:
      - Refuses files containing statutorily-confidential columns
        (raises `ConfidentialColumnError` before yielding any record).
      - Ignores columns it doesn't recognize.
      - Skips rows that fail Pydantic validation only if you wrap this
        iterator; by default, a bad row raises and stops the iterator.

    The default-strict behavior is intentional. If the SOS ships
    surprising data, we want a loud failure with the offending row, not
    silent partial loads.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise BulkFileError(f"voter file {p} appears to have no header row")

        normalized_headers = [_normalize_header(h) for h in reader.fieldnames]
        _check_no_confidential_columns(normalized_headers)

        for row_index, raw_row in enumerate(reader, start=2):  # start=2: row 1 is header
            # Re-key on normalized headers so the mapping table works.
            row = {_normalize_header(k): (v or "").strip() for k, v in raw_row.items()}

            kwargs: dict[str, object] = {}
            for sos_col, voter_field in SOS_TO_VOTER_FIELD.items():
                if sos_col not in row:
                    continue
                value = row[sos_col]

                # Special-case handlers come first.
                if voter_field == "_status_code":
                    kwargs["status"] = _to_voter_status(value) if value else VoterStatus.ACTIVE
                    continue
                if voter_field == "_county_code":
                    kwargs["county"] = _county_lookup(value)
                    continue

                # Generic coercions by field name.
                if voter_field == "voter_id":
                    kwargs["voter_id"] = _coerce_int(value)
                elif voter_field == "birth_year":
                    kwargs["birth_year"] = _coerce_int(value)
                elif voter_field == "registration_date":
                    kwargs["registration_date"] = _coerce_date(value)
                elif voter_field == "last_voted_date":
                    kwargs["last_voted_date"] = _coerce_date(value)
                elif voter_field == "residence_zip5":
                    # SOS ships zipcode as an int; pad to 5 digits.
                    kwargs["residence_zip5"] = value.zfill(5) if value else None
                else:
                    kwargs[voter_field] = value or None

            # Compose street name + suffix into one canonical field.
            suffix = row.get(SOS_STREET_SUFFIX_COLUMN, "")
            base = kwargs.get("residence_street_name")
            if base and suffix:
                kwargs["residence_street_name"] = f"{base} {suffix}".strip()
            elif suffix and not base:
                kwargs["residence_street_name"] = suffix

            try:
                yield Voter(**kwargs)
            except Exception as exc:
                raise BulkFileError(
                    f"voter file {p} row {row_index} failed validation: {exc}"
                ) from exc
