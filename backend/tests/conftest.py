"""Shared pytest fixtures and path setup.

The calculation modules are imported as ``app.*`` just like in production, so the
package root (``backend/``) is added to ``sys.path`` here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Keep the tests away from the real user-profile database: point the store at a scratch
# file inside the project, and reset it between tests so saved-household tests are
# independent of each other.
TEST_DB = BACKEND_ROOT / ".test-data" / "test.db"


def pytest_configure(config: pytest.Config) -> None:
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    os.environ["VOLTSPACE_DB"] = str(TEST_DB)

    # Tests must never touch a real Supabase project. Without this, a developer who has
    # VOLTSPACE_SUPABASE_* exported would make every TestClient startup attempt a network
    # call (and only fall back to the local store after a slow failure). Tests that need
    # Supabase set these themselves with monkeypatch.
    for name in (
        "VOLTSPACE_SUPABASE_URL",
        "VOLTSPACE_SUPABASE_KEY",
        "VOLTSPACE_SUPABASE_SERVICE_KEY",
        "VOLTSPACE_HOUSEHOLD_ID",
    ):
        os.environ.pop(name, None)
    os.environ["VOLTSPACE_STORAGE"] = "local"


@pytest.fixture(autouse=True)
def clean_household() -> None:
    """Start every test with an empty saved household."""

    from app.store import ApplianceStore

    ApplianceStore(TEST_DB).clear()
    yield


@pytest.fixture
def store():
    from app.store import ApplianceStore

    return ApplianceStore(TEST_DB)


@pytest.fixture
def student_room() -> list[dict]:
    """A realistic set of appliances for an NTHU off-campus rented room."""

    return [
        {
            "appliance_id": "a1",
            "name": "Air conditioner",
            "category": "cooling",
            "power_watts": 900,
            "hours_per_day": 6,
            "days_per_month": 30,
            "voltage": 220,
        },
        {
            "appliance_id": "a2",
            "name": "Refrigerator",
            "category": "cooling",
            "power_watts": 130,
            "hours_per_day": 24,
            "days_per_month": 30,
            "voltage": 110,
        },
        {
            "appliance_id": "a3",
            "name": "Desktop computer",
            "category": "electronics",
            "power_watts": 250,
            "hours_per_day": 6,
            "days_per_month": 30,
            "voltage": 110,
        },
    ]


@pytest.fixture
def ac_only() -> list[dict]:
    return [
        {
            "appliance_id": "a1",
            "name": "冷氣機",
            "power_watts": 900,
            "hours_per_day": 6,
            "days_per_month": 30,
            "voltage": 220,
        }
    ]
