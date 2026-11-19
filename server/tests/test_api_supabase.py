"""The API endpoints running on a Supabase-backed household store.

This is the test that answers "does the app actually read Supabase?". It swaps the store
that ``app/main.py`` put on ``app.state`` for a ``SupabaseStore`` talking to the in-memory
PostgREST stand-in, then drives the real HTTP endpoints.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store_supabase import SupabaseStore
from tests.test_store_supabase import AC, FakePostgrest


@pytest.fixture
def fake() -> FakePostgrest:
    return FakePostgrest("current")


@pytest.fixture
def client(fake: FakePostgrest):
    """A TestClient whose household endpoints are served from the fake Supabase."""

    with TestClient(app) as test_client:
        original = app.state.store
        app.state.store = SupabaseStore(
            "https://demo.supabase.co",
            "test-key",
            transport=httpx.MockTransport(fake.handler),
        )
        try:
            yield test_client
        finally:
            app.state.store = original


class TestApiOnSupabase:
    def test_saving_an_appliance_writes_to_supabase(self, client, fake):
        response = client.post("/household/appliances", json={"appliance": AC})
        assert response.status_code == 201, response.text

        assert len(fake.rows) == 1, "the row must have gone to the store, not to SQLite"
        assert fake.rows[0]["name"] == "冷氣機"
        assert fake.rows[0]["power_watts"] == 900

        body = response.json()
        assert body["name"] == "冷氣機"
        assert body["id"] == 1

    def test_listing_reads_from_supabase(self, client, fake):
        fake.rows.append(
            {
                "id": 5,
                "name": "冰箱",
                "category": None,
                "power_watts": 130,
                "hours_per_day": 24,
                "days_per_month": 30,
                "quantity": 1,
                "voltage": 110,
                "power_factor": None,
            }
        )
        response = client.get("/household/appliances")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["appliances"][0]["name"] == "冰箱"
        # 130 W * 24 h * 30 d / 1000 = 93.6 kWh
        assert body["total_monthly_kwh"] == pytest.approx(93.6)

    def test_update_and_delete_round_trip(self, client, fake):
        created = client.post("/household/appliances", json={"appliance": AC}).json()

        updated = client.put(
            f"/household/appliances/{created['id']}", json={"hours_per_day": 2}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["hours_per_day"] == 2.0
        assert fake.rows[0]["hours_per_day"] == 2

        deleted = client.delete(f"/household/appliances/{created['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True, "appliance_id": created["id"]}
        assert fake.rows == []

    def test_save_all_replaces_the_household(self, client, fake):
        response = client.put(
            "/household/appliances",
            json={"appliances": [AC, {**AC, "name": "除濕機", "power_watts": 150}]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 2
        assert [row["name"] for row in fake.rows] == ["冷氣機", "除濕機"]

    def test_dashboard_uses_the_stored_household(self, client, fake):
        client.post("/household/appliances", json={"appliance": AC})
        response = client.post("/household/dashboard", json={"month": 8})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "saved", "the dashboard must read the saved household"
        # 900 W * 6 h * 30 d / 1000 = 162 kWh
        assert body["summary"]["total_monthly_kwh"] == pytest.approx(162.0)

    def test_health_reports_supabase(self, client):
        body = client.get("/health").json()
        assert body["storage"] == "supabase"

    def test_domain_validation_still_runs_before_writing(self, client, fake):
        """An impossible appliance must be rejected, not stored."""

        bad = {**AC, "power_watts": -5}
        response = client.post("/household/appliances", json={"appliance": bad})
        assert response.status_code == 422
        assert fake.rows == []

    def test_store_errors_become_storage_errors(self, client, fake):
        fake.force_status = (
            401,
            {"code": "42501", "message": "new row violates row-level security policy"},
        )
        response = client.get("/household/appliances")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "storage_error"
        assert "service_role" in body["message"]
