"""Shared test configuration: import path + event-loop policy."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os

import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://f1intel:f1intel_dev@localhost:5432/f1intel",
)


@pytest_asyncio.fixture
async def pg_pool():
    """A real, migrated Postgres pool. Skips (does not fail) the test when
    no database is reachable at TEST_DATABASE_URL - persistence correctness
    genuinely needs a real Postgres, not a mock, but CI/dev environments
    without one shouldn't break the rest of the suite over it."""
    from app.storage.db import apply_migrations, connect

    try:
        pool = await connect(TEST_DATABASE_URL)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no test database reachable at {TEST_DATABASE_URL}: {exc}")
    await apply_migrations(pool)
    yield pool
    await pool.close()
