"""Build the synthetic SOS-format voter-file fixture.

Run this script to regenerate `synthetic_voter_file.csv`. The output file
is checked in; this script is checked in alongside it so anyone can see
exactly how the synthetic data was constructed.

No real voter data appears here. Every name is composed from two word
lists that read as obviously fictional. Every street address is a
synthetic combination. Every voter_id is in the 9_000_000+ range, well
clear of any plausible real SOS-issued identifier.

The column names match the Georgia SOS bulk file format as documented
in https://github.com/Voteshield/reggie/blob/main/reggie/configs/data/
georgia.yaml. This fixture exercises a *subset* of those columns — the
ones that map to fields on the `Voter` model. Columns that the SOS
ships but our model does not consume (e.g. `Land_district`, the many
district columns) are intentionally omitted; the bulk-file reader must
tolerate that.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).parent / "synthetic_voter_file.csv"

# Two-syllable word lists picked to be obviously fictional when combined.
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
    ("Imaginary", "St"),
    ("Fictional", "Ave"),
    ("Placeholder", "Rd"),
    ("Example", "Blvd"),
    ("Synthetic", "Way"),
    ("Mockup", "Ln"),
    ("Specimen", "Ct"),
    ("Testing", "Dr"),
]
CITIES = ["Atlanta", "Savannah", "Augusta", "Macon", "Columbus", "Athens", "Decatur"]
COUNTIES_BY_CITY = {
    "Atlanta": ("Fulton", 60),
    "Savannah": ("Chatham", 25),
    "Augusta": ("Richmond", 121),
    "Macon": ("Bibb", 11),
    "Columbus": ("Muscogee", 106),
    "Athens": ("Clarke", 29),
    "Decatur": ("DeKalb", 44),
}
RACES = ["WH", "BH", "HP", "AP", "AI", "OT", "U"]
GENDERS = ["M", "F", "U"]
STATUSES = [("A", "Active"), ("I", "Inactive")]

# SOS column order, as in the reggie config. We're emitting the subset the
# reader cares about + a few "noise" columns so we exercise the
# tolerate-unknown-columns path.
COLUMNS = [
    "County_code",
    "Registration_Number",
    "Voter_status",
    "Last_name",
    "First_name",
    "Middle_maiden_name",
    "Name_suffix",
    "Residence_house_number",
    "Residence_street_name",
    "Residence_street_suffix",
    "Residence_apt_unit_nbr",
    "Residence_city",
    "Residence_zipcode",
    "Year_of_Birth",
    "Registration_date",
    "Race",
    "Gender",
    "County_precinct_id",
    "Date_last_voted",
    # Noise column the reader must tolerate (present in real file, ignored by us):
    "Land_district",
    # Another ignored column:
    "Congressional_district",
]


def main() -> None:
    rng = random.Random(20260516)  # deterministic
    rows = []
    for i in range(50):
        city = rng.choice(CITIES)
        county_name, county_code = COUNTIES_BY_CITY[city]
        street_name, street_suffix = rng.choice(STREETS)
        status_code, _status_label = rng.choice(STATUSES)
        zip5 = f"30{rng.randint(100, 999):03d}"
        voter_id = 9_000_000 + i

        # Apartment only some of the time.
        apt = f"Apt {rng.randint(1, 50)}" if rng.random() < 0.3 else ""

        # Year of birth: 1940–2005, integer (NEVER a full date).
        yob = rng.randint(1940, 2005)
        reg_date = f"{rng.randint(1990, 2025)}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
        last_voted = f"{rng.randint(2018, 2025)}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"

        rows.append(
            {
                "County_code": county_code,
                "Registration_Number": voter_id,
                "Voter_status": status_code,
                "Last_name": rng.choice(LAST_NAMES),
                "First_name": rng.choice(FIRST_NAMES),
                "Middle_maiden_name": "" if rng.random() < 0.4 else "Q.",
                "Name_suffix": "" if rng.random() < 0.85 else rng.choice(["Jr", "Sr", "II"]),
                "Residence_house_number": rng.randint(1, 9999),
                "Residence_street_name": street_name,
                "Residence_street_suffix": street_suffix,
                "Residence_apt_unit_nbr": apt,
                "Residence_city": city,
                "Residence_zipcode": zip5,
                "Year_of_Birth": yob,
                "Registration_date": reg_date,
                "Race": rng.choice(RACES),
                "Gender": rng.choice(GENDERS),
                "County_precinct_id": f"{county_name[:3].upper()}-{rng.randint(1, 200):03d}",
                "Date_last_voted": last_voted if rng.random() < 0.7 else "",
                "Land_district": rng.randint(1, 30),
                "Congressional_district": rng.randint(1, 14),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic rows to {OUT}")


if __name__ == "__main__":
    main()
