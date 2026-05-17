"""Pagination shared across list routes.

ADR-0005 decision 4: every list endpoint requires `limit` and `offset`,
with a default of 50 and a hard ceiling of 500. There is no
"return everything" path through the API; bulk data ships separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


@dataclass(frozen=True)
class Page:
    """A validated pagination request."""

    limit: int
    offset: int


def page_params(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> Page:
    """FastAPI dependency that validates and packages pagination params.

    The bounds (`ge=1, le=MAX_LIMIT`, `ge=0`) are enforced by FastAPI's
    query validation, which returns a 422 before the handler runs.
    A request for `limit=10000` does not reach the database — it fails
    at the edge with a structured error.
    """
    return Page(limit=limit, offset=offset)
