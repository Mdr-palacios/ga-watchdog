"""Property + unit tests for `transforms/address.py`.

Most of this file is property tests via Hypothesis. The reason — and
the reason this is the file that lands LESSONS L13 — is that the
universe of valid (house_number, street_name, street_suffix, apt,
city, zip5) tuples is too big to enumerate as fixtures. The invariants
that matter (round-trip on the composed surface, idempotence of
normalization helpers, safety on incoherent inputs) hold across that
whole universe, so testing on shaped random inputs gives stronger
guarantees than handpicked examples.

Where Hypothesis adds nothing — verifying specific normalization
mappings like "STREET → St" — we use plain parametrized tests. The
goal is not to use Hypothesis everywhere; it's to use it where the
space is bigger than human imagination.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pipelines.voter_file.transforms.address import (
    _SUFFIX_MAP,
    AddressCompositionError,
    ResidenceParts,
    compose_residence_line,
    normalize_city,
    normalize_street_suffix,
    normalize_whitespace,
    split_residence_line,
)

# ---------------------------------------------------------------------------
# Hypothesis strategies that produce inputs in the surface we care about.
#
# These deliberately keep the alphabet narrow (ASCII letters + digits +
# space). The SOS file is ASCII; we don't claim to support Unicode here,
# and a property-tester that wanders into Unicode quickly stops testing
# the thing the code actually does.
# ---------------------------------------------------------------------------

_TOKEN_ALPHABET = string.ascii_uppercase + string.ascii_lowercase

st_token = st.text(alphabet=_TOKEN_ALPHABET, min_size=1, max_size=10)
st_multitoken = st.lists(st_token, min_size=1, max_size=3).map(" ".join)
st_house_number = st.integers(min_value=1, max_value=99999).map(str)
st_suffix = st.sampled_from(sorted(set(_SUFFIX_MAP.values())))
st_city = st.lists(st_token, min_size=1, max_size=2).map(lambda parts: " ".join(parts))
st_zip5 = st.integers(min_value=30000, max_value=39999).map(str)
st_apartment = st.one_of(
    st.none(),
    st.tuples(st.sampled_from(["Apt", "Unit", "#"]), st.integers(min_value=1, max_value=999)).map(
        lambda t: f"{t[0]} {t[1]}"
    ),
)


@st.composite
def st_parts_full(draw: st.DrawFn) -> ResidenceParts:
    """Fully-populated parts: every field non-empty. Easiest round-trip case."""
    return ResidenceParts(
        house_number=draw(st_house_number),
        street_name=draw(st_multitoken),
        street_suffix=draw(st_suffix),
        apartment=draw(st_apartment),
        city=draw(st_city),
        zip5=draw(st_zip5),
    )


@st.composite
def st_parts_partial(draw: st.DrawFn) -> ResidenceParts:
    """Some fields may be None, *except* that house_number requires street_name.

    This mirrors the coherence rule that `compose_residence_line` enforces.
    """
    sn = draw(st.one_of(st.none(), st_multitoken))
    return ResidenceParts(
        house_number=draw(st.one_of(st.none(), st_house_number)) if sn else None,
        street_name=sn,
        street_suffix=draw(st.one_of(st.none(), st_suffix)),
        apartment=draw(st_apartment),
        city=draw(st.one_of(st.none(), st_city)),
        zip5=draw(st.one_of(st.none(), st_zip5)),
    )


# ---------------------------------------------------------------------------
# Property 1 — round-trip on the composed surface.
# ---------------------------------------------------------------------------


@given(st_parts_full())
def test_round_trip_full_parts(parts: ResidenceParts) -> None:
    """compose ∘ split is identity on the fully-populated parts.

    Modulo two normalization rules the composer applies:
      - city is title-cased
      - suffix is canonicalized via _SUFFIX_MAP

    The strategies above already produce title-cased cities and
    canonical suffixes, so equality is exact for those fields.
    """
    line = compose_residence_line(parts)
    re_parsed = split_residence_line(line)

    assert re_parsed.house_number == parts.house_number
    assert re_parsed.street_name == normalize_whitespace(parts.street_name)
    assert re_parsed.street_suffix == normalize_street_suffix(parts.street_suffix)
    assert re_parsed.apartment == normalize_whitespace(parts.apartment)
    assert re_parsed.city == normalize_city(parts.city)
    assert re_parsed.zip5 == parts.zip5


@given(st_parts_partial())
def test_round_trip_partial_parts_preserves_zip(parts: ResidenceParts) -> None:
    """Whatever else gets lost in partial cases, the ZIP must survive.

    ZIP is the most aggregation-critical field for downstream rollups,
    so we pin its round-trip independently.
    """
    line = compose_residence_line(parts)
    re_parsed = split_residence_line(line)
    assert re_parsed.zip5 == parts.zip5


# ---------------------------------------------------------------------------
# Property 2 — idempotence of normalization helpers.
# ---------------------------------------------------------------------------


@given(st.text())
def test_normalize_whitespace_idempotent(s: str) -> None:
    once = normalize_whitespace(s)
    twice = normalize_whitespace(once or "")
    # Compare on the "or empty" normalization both ways.
    assert once == (twice if twice is not None else None)


@given(st.text())
def test_normalize_city_idempotent(s: str) -> None:
    once = normalize_city(s)
    twice = normalize_city(once or "")
    assert once == (twice if twice is not None else None)


@given(st.text())
def test_normalize_street_suffix_idempotent(s: str) -> None:
    once = normalize_street_suffix(s)
    twice = normalize_street_suffix(once or "")
    assert once == (twice if twice is not None else None)


# ---------------------------------------------------------------------------
# Property 3 — safety: incoherent inputs raise, never produce garbage.
# ---------------------------------------------------------------------------


@given(st_house_number)
def test_house_number_without_street_raises(hn: str) -> None:
    """House number with no street name must raise, not produce ' 1234, City'."""
    parts = ResidenceParts(
        house_number=hn,
        street_name=None,
        street_suffix=None,
        apartment=None,
        city="Atlanta",
        zip5="30303",
    )
    with pytest.raises(AddressCompositionError):
        compose_residence_line(parts)


def test_all_none_parts_render_empty_string() -> None:
    """The only legal empty output: every field None → ""."""
    empty = ResidenceParts(None, None, None, None, None, None)
    assert compose_residence_line(empty) == ""


# ---------------------------------------------------------------------------
# Unit tests for the suffix and city normalizers — Hypothesis is overkill
# for asserting a finite lookup table.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ST", "St"),
        ("st", "St"),
        ("St.", "St"),
        ("STREET", "St"),
        ("street", "St"),
        ("AVE", "Ave"),
        ("Avenue", "Ave"),
        ("BLVD", "Blvd"),
        ("boulevard", "Blvd"),
        ("Way", "Way"),
        ("HIGHWAY", "Hwy"),
        ("hwy", "Hwy"),
    ],
)
def test_suffix_map_canonical(raw: str, expected: str) -> None:
    assert normalize_street_suffix(raw) == expected


def test_unknown_suffix_passes_through_title_cased() -> None:
    """Unknown suffix isn't an error — just title-case it."""
    assert normalize_street_suffix("RANDOM") == "Random"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("atlanta", "Atlanta"),
        ("ATLANTA", "Atlanta"),
        ("  Atlanta  ", "Atlanta"),
        ("east point", "East Point"),
        ("EAST  POINT", "East Point"),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_city_examples(raw: str, expected: str | None) -> None:
    assert normalize_city(raw) == expected


# ---------------------------------------------------------------------------
# A concrete end-to-end example that doubles as documentation.
# ---------------------------------------------------------------------------


def test_compose_canonical_example() -> None:
    parts = ResidenceParts(
        house_number="123",
        street_name="Fictional",
        street_suffix="Ave",
        apartment="Apt 4",
        city="atlanta",
        zip5="30303",
    )
    line = compose_residence_line(parts)
    assert line == "123 Fictional Ave, Apt 4, Atlanta, GA 30303"


def test_split_canonical_example() -> None:
    line = "123 Fictional Ave, Apt 4, Atlanta, GA 30303"
    parts = split_residence_line(line)
    assert parts.house_number == "123"
    assert parts.street_name == "Fictional"
    assert parts.street_suffix == "Ave"
    assert parts.apartment == "Apt 4"
    assert parts.city == "Atlanta"
    assert parts.zip5 == "30303"
