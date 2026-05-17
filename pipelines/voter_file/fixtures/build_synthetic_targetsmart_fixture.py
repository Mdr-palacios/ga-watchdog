"""Build the synthetic TargetSmart-shaped voter-file fixture.

Run this script to regenerate `synthetic_targetsmart_voter_file.csv`. The
output file is checked in; this script is checked in alongside it so the
construction is fully auditable.

WHY THIS FIXTURE EXISTS
-----------------------

TargetSmart is a commercial vendor that distributes a Georgia voter file
with its own column naming convention (`voterbase_id`, `vf_*`,
`tsmart_*`). Civic-tech operators sometimes receive TargetSmart-format
files from partner orgs that hold a license. We want the pipeline to be
able to read those files **without** ever ingesting TargetSmart's
licensed / modeled / commercially-enriched fields — only the columns
that map cleanly back to information that O.C.G.A. § 21-2-225(b) makes
public on its own.

So this fixture is **shape-compatible with TargetSmart's GA file, but**:

  - Every value is synthetic. The `voterbase_id`s sit in the `TS9000000+`
    range, well clear of any plausible real TargetSmart identifier.
  - Every name is composed from two obviously-fictional word lists.
  - No licensed columns appear at all (`voterbase_age`, `voterbase_race`,
    `voterbase_gender`, `tsmart_partisan_score`,
    `tsmart_midterm_general_turnout_score`, `reg_latitude`,
    `reg_longitude`, the `tsmart_*` cleaned-address duplicates, the
    `voterbase_phone_*` enrichment flags, etc.). See
    `targetsmart_format.py` for the explicit licensed-column refusal
    list and the rationale.

What's left is a strict subset of TargetSmart's columns that all map to
fields the statute already makes public — name, address, county,
year-of-birth-equivalents (we don't even include year-of-birth here
because TargetSmart's `voterbase_age` is "derived from DOB" and is
itself listed as licensed in the data dictionary).

See:
  - ADR-0004 (the five-rule charter)
  - `pipelines/voter_file/fixtures/README.md` (why the shape matters)
  - `pipelines/voter_file/sources/targetsmart_format.py` (the reader)

No real voter data appears anywhere in this file's output.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).parent / "synthetic_targetsmart_voter_file.csv"

# Two-syllable word lists picked to be obviously fictional when combined.
# These match the SOS-format fixture's word lists for visual consistency.
FIRST_NAMES = [
    "Synthetic",
    "Fixture",
    "Placeholder",
    "Specimen",
    "Sample",
    "Testing",
    "Example",
    "Mockup",
    "Stand-In",
    "Dummy",
]
MIDDLE_NAMES = ["", "Q.", "X.", "Z.", "T."]
LAST_NAMES = [
    "TestRecord",
    "FakeRow",
    "NotReal",
    "DoNotShip",
    "Synthetic",
    "Fixture",
    "Example",
    "Placeholder",
    "Generator",
    "Output",
]
STREETS = [
    ("Imaginary", "ST"),
    ("Fictional", "AVE"),
    ("Placeholder", "RD"),
    ("Example", "BLVD"),
    ("Synthetic", "WAY"),
    ("Mockup", "LN"),
    ("Specimen", "CT"),
    ("Testing", "DR"),
]
# Mirror the SOS fixture's seven counties so reader tests can rely on
# the same county set across both fixtures.
COUNTIES_BY_CITY = {
    "ATLANTA": ("Fulton", "13121"),  # FIPS county code, GA = 13
    "SAVANNAH": ("Chatham", "13051"),
    "AUGUSTA": ("Richmond", "13245"),
    "MACON": ("Bibb", "13021"),
    "COLUMBUS": ("Muscogee", "13215"),
    "ATHENS": ("Clarke", "13059"),
    "DECATUR": ("DeKalb", "13089"),
}
# vf_voter_status uses TargetSmart's labels. The data dictionary
# enumerates ACTIVE / INACTIVE / PURGED / OTHER; we only emit the two
# common ones so the mapping logic is exercised.
STATUSES = ["ACTIVE", "INACTIVE"]
# vf_early_voter_status: shipped as 1 / 0 / blank in the dictionary; we
# use a string here because that's what CSV produces anyway.
EARLY_VOTER_VALUES = ["1", "0", ""]
# vf_g2020, vf_g2018: general-election participation flags. The
# dictionary enumerates Y / N / blank; we honor that exactly.
PARTICIPATION_VALUES = ["Y", "N", ""]
# Congressional districts 1-14 (Georgia has 14 districts; the dictionary
# stores them as zero-padded two-digit strings, e.g. "07").
CD_VALUES = [f"{i:02d}" for i in range(1, 15)]

# Column order matches a tight subset of the TargetSmart GA columns,
# in roughly the order they appear in the data dictionary. EVERY column
# emitted here is one that maps to information the statute already makes
# public. Licensed / modeled / commercial-enrichment columns are
# intentionally absent — the reader refuses files that contain them.
COLUMNS = [
    "voterbase_id",
    "vf_reg_state",
    "vf_county_name",
    "vf_county_code",
    "vf_reg_zip",
    "vf_reg_city",
    "vf_reg_address1",  # composed street line (number + name + suffix)
    "vf_reg_address2",  # apt/unit (optional)
    "vf_cd",  # congressional district
    "vf_voter_status",
    "tsmart_first_name",
    "tsmart_middle_name",
    "tsmart_last_name",
    "vf_g2018",
    "vf_g2020",
    "vf_early_voter_status",
    # Two "noise" columns the reader must tolerate. These are real
    # TargetSmart column names that map back to public information but
    # we choose not to consume yet — the reader should silently ignore
    # them, exactly as it does for unknown columns in the SOS reader.
    "vf_reg_cass_state",
    "vf_precinct_name",
]


def main() -> None:
    rng = random.Random(20260516)  # deterministic; same seed as SOS fixture
    rows = []
    for i in range(50):
        city = rng.choice(list(COUNTIES_BY_CITY.keys()))
        county_name, county_fips = COUNTIES_BY_CITY[city]
        street_name, street_suffix = rng.choice(STREETS)
        house_number = rng.randint(1, 9999)
        composed_street = f"{house_number} {street_name.upper()} {street_suffix}"

        apt = f"APT {rng.randint(1, 50)}" if rng.random() < 0.3 else ""
        zip5 = f"30{rng.randint(100, 999):03d}"

        # voterbase_id: TargetSmart issues a 32-char hex-ish identifier
        # in production. We use a clearly-synthetic "TS9000000XX" string
        # so anyone glancing at a row knows it isn't real.
        voterbase_id = f"TS{9_000_000 + i:09d}"

        rows.append(
            {
                "voterbase_id": voterbase_id,
                "vf_reg_state": "GA",
                "vf_county_name": county_name.upper(),
                "vf_county_code": county_fips,
                "vf_reg_zip": zip5,
                "vf_reg_city": city,
                "vf_reg_address1": composed_street,
                "vf_reg_address2": apt,
                "vf_cd": rng.choice(CD_VALUES),
                "vf_voter_status": rng.choice(STATUSES),
                "tsmart_first_name": rng.choice(FIRST_NAMES).upper(),
                "tsmart_middle_name": rng.choice(MIDDLE_NAMES).upper(),
                "tsmart_last_name": rng.choice(LAST_NAMES).upper(),
                "vf_g2018": rng.choice(PARTICIPATION_VALUES),
                "vf_g2020": rng.choice(PARTICIPATION_VALUES),
                "vf_early_voter_status": rng.choice(EARLY_VOTER_VALUES),
                "vf_reg_cass_state": "GA",
                "vf_precinct_name": f"{county_name[:3].upper()}-{rng.randint(1, 200):03d}",
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic TargetSmart-shaped rows to {OUT}")


if __name__ == "__main__":
    main()
