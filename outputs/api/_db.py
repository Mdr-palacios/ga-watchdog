"""Read-only DuckDB connection helper.

ADR-0005 decision 3: the API process opens DuckDB with `read_only=True`.
A bug, a typo, or a creative URL parameter cannot cause a write because
the connection itself refuses writes.

The path is resolved from the environment:

- `GA_WATCHDOG_WAREHOUSE_PATH` — explicit override, used in tests.
- otherwise, `warehouse/warehouse.duckdb` relative to the repo root.

The connection is opened per-request on Vercel serverless (cold-start
cost is the tradeoff documented in ADR-0005 decision 9). For local
development and tests, callers can hold onto the connection longer.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_WAREHOUSE = _REPO_ROOT / "warehouse" / "warehouse.duckdb"


def warehouse_path() -> Path:
    """Resolve the warehouse file path.

    `GA_WATCHDOG_WAREHOUSE_PATH` overrides for tests and for the Vercel
    bundle (where the file ships at a deployment-specific location).
    """
    env = os.environ.get("GA_WATCHDOG_WAREHOUSE_PATH")
    if env:
        return Path(env)
    return _DEFAULT_WAREHOUSE


def connect() -> duckdb.DuckDBPyConnection:
    """Open a read-only connection to the warehouse.

    Raises `FileNotFoundError` if the warehouse hasn't been built —
    that's deliberate. A 500 with a clear message on a missing file is
    better than a silent empty-results response that looks like
    "nothing happened in Georgia this quarter."
    """
    path = warehouse_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Warehouse file not found at {path}. "
            "Run the ingest flow or set GA_WATCHDOG_WAREHOUSE_PATH."
        )
    return duckdb.connect(str(path), read_only=True)
