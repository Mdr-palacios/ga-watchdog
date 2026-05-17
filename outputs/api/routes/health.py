"""Liveness endpoint.

Returns the warehouse build timestamp so callers and caching layers
can detect when data has rotated. Reads from a metadata view if one
exists; otherwise returns the file's mtime as a fallback.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter

from .._db import connect, warehouse_path

router = APIRouter(tags=["health"])


@router.get("/v1/health")
def health() -> dict[str, str]:
    """Return service health and the warehouse build timestamp."""
    path = warehouse_path()
    if not path.exists():
        return {"status": "no-warehouse", "warehouse_built_at": ""}
    # Cheap probe: open and immediately close. If DuckDB can open the
    # file read-only, the API can serve from it.
    conn = connect()
    conn.close()
    mtime = os.path.getmtime(path)
    built_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    return {"status": "ok", "warehouse_built_at": built_at}
