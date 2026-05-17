"""Address normalization for voter records.

The Georgia SOS bulk file ships residence addresses *pre-parsed* into
separate columns: house number, street name, street suffix, apt/unit,
city, ZIP. We keep them stored that way (see `Voter.residence_*` and
`warehouse/schema/voter.sql`) because aggregations to precinct/ZIP
don't need to re-parse a free-text string.

What this module does
---------------------
This module is the inverse: it composes the pre-parsed parts back into
a canonical single-line display string when the public output surface
needs one (e.g. "show me a redacted-address turnout-by-block view"). It
is **not** a free-text address parser — Georgia gave us a parsed file,
we're not going to throw that away and re-guess.

The two operations are:

- `compose_residence_line(parts)` — parts dict → display string.
  Round-trippable for the parts that survive: re-splitting via
  `split_residence_line` gives back the parts (modulo whitespace
  normalization and case folding of the suffix).
- `split_residence_line(line)` — display string → parts dict. Lossy
  by design for arbitrary input. Property-tested *only* on the output
  of `compose_residence_line` — we don't claim to parse the universe
  of real-world address strings.

Why these are property-tested
-----------------------------
The universe of valid (house_number, street_name, street_suffix, apt,
city, zip) tuples is too big to enumerate as fixtures. The invariants
that matter are:

  1. **Round-trip on the composed surface.** compose ∘ split is
     identity on the parts (after the normalization rules below).
  2. **Idempotence.** compose(compose(x)) is impossible to call
     directly, but `normalize_*` helpers must be idempotent:
     `normalize_city(normalize_city(x)) == normalize_city(x)`.
  3. **Safety.** compose() never silently emits a value that hides
     missing parts — e.g. an empty street with a non-empty house
     number must raise, not produce "1234 ,  Atlanta GA".

Anything beyond these invariants — handling real-world typos, multiple
suffix conventions, mailing-address vs. residence quirks — is out of
scope for Phase 2.1. See LESSONS §L13 for why this scoping is the
whole point of property testing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResidenceParts:
    """The shape this module operates on.

    Mirrors the residence-address fields of `Voter`, minus pipeline
    metadata. ZIP is the 5-digit form; ZIP+4 is not in scope.
    """

    house_number: str | None
    street_name: str | None
    street_suffix: str | None  # "St", "Ave", "Blvd", etc. May be None.
    apartment: str | None
    city: str | None
    zip5: str | None


def normalize_whitespace(value: str | None) -> str | None:
    """Collapse runs of whitespace and trim. None passes through.

    Idempotent: `normalize_whitespace(normalize_whitespace(x))` equals
    `normalize_whitespace(x)`.
    """
    if value is None:
        return None
    return " ".join(value.split()) or None


def normalize_city(value: str | None) -> str | None:
    """Title-case city name, whitespace-normalized.

    SOS ships cities in mixed case; we standardize to title case so
    aggregates by city are not split by capitalization. Idempotent.
    """
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return None
    return cleaned.title()


def normalize_street_suffix(value: str | None) -> str | None:
    """Standardize the suffix to its USPS-style short form, title-cased.

    The mapping covers the common Georgia residence suffixes — extend
    as needed. Unknown suffixes pass through (whitespace-normalized).
    Idempotent.
    """
    cleaned = normalize_whitespace(value)
    if cleaned is None:
        return None
    canonical = _SUFFIX_MAP.get(cleaned.upper().rstrip("."))
    return canonical if canonical else cleaned.title()


_SUFFIX_MAP: dict[str, str] = {
    "ST": "St",
    "STREET": "St",
    "AVE": "Ave",
    "AVENUE": "Ave",
    "BLVD": "Blvd",
    "BOULEVARD": "Blvd",
    "RD": "Rd",
    "ROAD": "Rd",
    "DR": "Dr",
    "DRIVE": "Dr",
    "LN": "Ln",
    "LANE": "Ln",
    "WAY": "Way",
    "CT": "Ct",
    "COURT": "Ct",
    "CIR": "Cir",
    "CIRCLE": "Cir",
    "PKWY": "Pkwy",
    "PARKWAY": "Pkwy",
    "PL": "Pl",
    "PLACE": "Pl",
    "TER": "Ter",
    "TERRACE": "Ter",
    "HWY": "Hwy",
    "HIGHWAY": "Hwy",
}


class AddressCompositionError(ValueError):
    """Raised when parts cannot be composed into a coherent line.

    Example: a non-empty house_number with an empty street_name. We
    refuse to silently produce '1234  Atlanta' — that's a data-quality
    bug we want to see, not paper over.
    """


def compose_residence_line(parts: ResidenceParts) -> str:
    """Render parts as a single canonical line. Empty parts → empty string.

    Format: "<house> <street> <suffix>[, <apt>], <city>[, GA] <zip>"

    Rules:
      - All fields None / empty → "" (the only legal "empty" output).
      - house_number requires street_name. Other partial combinations
        are tolerated (e.g. city + zip only).
      - State is always "GA" — this is the Georgia voter file, the
        column doesn't exist in the SOS bulk file's residence block.
    """
    hn = normalize_whitespace(parts.house_number)
    sn = normalize_whitespace(parts.street_name)
    sf = normalize_street_suffix(parts.street_suffix)
    apt = normalize_whitespace(parts.apartment)
    city = normalize_city(parts.city)
    zip5 = normalize_whitespace(parts.zip5)

    if all(p is None for p in (hn, sn, sf, apt, city, zip5)):
        return ""

    if hn and not sn:
        raise AddressCompositionError(
            f"house_number={hn!r} present but street_name is empty; "
            "cannot compose a coherent address line"
        )

    street_parts = [p for p in (hn, sn, sf) if p]
    street = " ".join(street_parts)

    segments: list[str] = []
    if street:
        segments.append(street)
    if apt:
        segments.append(apt)

    tail_parts: list[str] = []
    if city:
        tail_parts.append(city)
    if zip5:
        # State sits with the ZIP in conventional US form: "Atlanta, GA 30303"
        tail_parts.append(f"GA {zip5}" if city else f"GA {zip5}")
    if tail_parts:
        segments.append(", ".join(tail_parts) if len(tail_parts) > 1 else tail_parts[0])

    return ", ".join(segments)


# ---------------------------------------------------------------------------
# Splitter: the inverse, restricted to the surface compose() emits.
# ---------------------------------------------------------------------------


def split_residence_line(line: str) -> ResidenceParts:
    """Inverse of `compose_residence_line` *on its own output*.

    This is deliberately narrow. It is NOT a general US address parser.
    Property tests assert round-trip only on lines produced by
    `compose_residence_line`. Calling this on arbitrary free-text input
    will return parts that may not match the source — and that's fine,
    because we never accept free-text addresses anywhere upstream.
    """
    cleaned = normalize_whitespace(line) or ""
    if not cleaned:
        return ResidenceParts(None, None, None, None, None, None)

    # Segments separated by ", ".
    segments = [s.strip() for s in cleaned.split(",")]

    house_number: str | None = None
    street_name: str | None = None
    street_suffix: str | None = None
    apartment: str | None = None
    city: str | None = None
    zip5: str | None = None

    # Last segment is always "GA <zip5>" if there's a zip; just before
    # that is the city (own segment). The street is segment[0]. An
    # apartment, if present, is the segment between street and city.

    # Pull the trailing "GA <zip5>" if present.
    tail = segments[-1] if segments else ""
    if tail.startswith("GA "):
        zip5 = tail.removeprefix("GA ").strip() or None
        segments = segments[:-1]

    # The new last segment (if any) is the city.
    if segments and len(segments) > 1:
        city_candidate = segments[-1]
        # Heuristic: if it has no digits and isn't an apartment marker,
        # treat as city. This is sufficient for compose()'s output.
        if not any(ch.isdigit() for ch in city_candidate):
            city = normalize_city(city_candidate)
            segments = segments[:-1]
    elif segments and len(segments) == 1 and zip5 and not any(ch.isdigit() for ch in segments[0]):
        # Single segment + zip: assume it's the city.
        city = normalize_city(segments[0])
        segments = []

    # Now: segments may contain [street] or [street, apt].
    if segments:
        if len(segments) >= 2:
            apartment = segments[-1] or None
            street_segment = segments[0]
        else:
            street_segment = segments[0]

        # Split street_segment into number + name + suffix.
        tokens = street_segment.split()
        if tokens and tokens[0].isdigit():
            house_number = tokens[0]
            tokens = tokens[1:]
        if tokens:
            # Last token, if in the known suffix map, is the suffix.
            last = tokens[-1]
            if last.upper().rstrip(".") in _SUFFIX_MAP or last in _SUFFIX_MAP.values():
                street_suffix = normalize_street_suffix(last)
                tokens = tokens[:-1]
            if tokens:
                street_name = " ".join(tokens)

    return ResidenceParts(
        house_number=house_number,
        street_name=street_name,
        street_suffix=street_suffix,
        apartment=apartment,
        city=city,
        zip5=zip5,
    )
