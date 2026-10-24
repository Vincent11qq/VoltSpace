"""Tests for the persistence endpoints and the dashboard aggregate.

These cover the integration layer added so the Flet/web frontend never has to
re-implement a formula or hard-code a tariff.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

AC = {
    "name": "冷氣機",
    "category": "cooling",
    "power_watts": 900,
    "hours_per_day": 6,
    "days_per_month": 30,
    "voltage": 220,
}
FRIDGE = {
    "name": "冰箱",
    "category": "cooling",
    "power_watts": 130,
    "hours_per_day": 24,
    "days_per_month": 30,
    "voltage": 110,
}


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


class TestPresets:
    def test_presets_endpoint(self, client):
        body = client.get("/appliances/presets").json()
        assert len(body["presets"]) == 12
        assert body["default_circuit_amps"] == 15
        assert body["default_voltage"] == 110

    def test_circuit_ceiling_is_derived_from_amps_and_volts(self, client):
        """The prototype hard-coded 1650 W; it must come from the circuit definition."""

        body = client.get("/appliances/presets").json()
        for circuit in body["circuits"]:
            assert circuit["max_watts"] == pytest.approx(circuit["amps"] * circuit["voltage"])

    def test_room_socket_is_the_common_taiwan_rating(self, client):
        body = client.get("/appliances/presets").json()
        room = body["circuits"][0]
        assert (room["amps"], room["voltage"], room["max_watts"]) == (15, 110.0, 1650.0)

    def test_reference_rate_comes_from_the_tariff_table(self, client):
        from app.calculators.electricity_bill import calculate_bill

        body = client.get("/appliances/presets").json()
        expected = calculate_bill(1.0, plan_id=body["default_plan_id"])["total_amount"]
        assert body["reference_rate_per_kwh"] == pytest.approx(expected, abs=1e-4)

    def test_presets_carry_usable_defaults(self, client):
        body = client.get("/appliances/presets").json()
        for preset in body["presets"]:
            assert preset["power_watts"] > 0
            assert 0 < preset["hours_per_day"] <= 24
            assert 1 <= preset["days_per_month"] <= 31
            assert preset["voltage"] in (110, 220)

    def test_air_conditioner_is_first(self, client):
        body = client.get("/appliances/presets").json()
        assert body["presets"][0]["key"] == "air_conditioner"


class TestHouseholdCrud:
    def test_starts_empty(self, client):
        body = client.get("/household/appliances").json()
        assert body["count"] == 0
        assert body["total_monthly_kwh"] == 0
        assert body["appliances"] == []

    def test_add_and_list(self, client):
        created = client.post("/household/appliances", json={"appliance": AC})
        assert created.status_code == 201
        appliance = created.json()
        # AUTOINCREMENT ids are never reused, so only assert that an id was assigned.
        assert isinstance(appliance["id"], int) and appliance["id"] > 0
        assert appliance["name"] == "冷氣機"
        assert appliance["power_watts"] == 900

        listing = client.get("/household/appliances").json()
        assert listing["count"] == 1
        assert listing["appliances"][0]["id"] == appliance["id"]
        assert listing["total_monthly_kwh"] == pytest.approx(162.0)

    def test_defaults_are_applied_on_create(self, client):
        appliance = client.post(
            "/household/appliances",
            json={"appliance": {"name": "Fan", "power_watts": 45, "hours_per_day": 8}},
        ).json()
        assert appliance["days_per_month"] == 30
        assert appliance["quantity"] == 1

    def test_list_total_matches_the_calculator(self, client):
        from app.calculators.consumption import calculate_consumption

        client.post("/household/appliances", json={"appliance": AC})
        client.post("/household/appliances", json={"appliance": FRIDGE})
        listing = client.get("/household/appliances").json()
        expected = calculate_consumption([AC, FRIDGE])["total_monthly_kwh"]
        assert listing["total_monthly_kwh"] == pytest.approx(expected, abs=0.01)

    def test_update_changes_only_that_field(self, client):
        created = client.post("/household/appliances", json={"appliance": AC}).json()
        response = client.put(
            f"/household/appliances/{created['id']}", json={"hours_per_day": 3}
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["hours_per_day"] == 3
        assert updated["power_watts"] == 900
        assert updated["name"] == "冷氣機"

    def test_update_requires_at_least_one_field(self, client):
        created = client.post("/household/appliances", json={"appliance": AC}).json()
        response = client.put(f"/household/appliances/{created['id']}", json={})
        assert response.status_code == 422

    def test_update_rejects_invalid_value(self, client):
        created = client.post("/household/appliances", json={"appliance": AC}).json()
        response = client.put(
            f"/household/appliances/{created['id']}", json={"power_watts": 0}
        )
        assert response.status_code == 422

    def test_update_unknown_id_is_404(self, client):
        response = client.put("/household/appliances/999999", json={"hours_per_day": 2})
        assert response.status_code == 404
        assert response.json()["code"] == "appliance_not_found"

    def test_delete(self, client):
        created = client.post("/household/appliances", json={"appliance": AC}).json()
        response = client.delete(f"/household/appliances/{created['id']}")
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert client.get("/household/appliances").json()["count"] == 0

    def test_delete_unknown_id_is_404(self, client):
        assert client.delete("/household/appliances/999999").status_code == 404

    def test_save_all_replaces_the_household(self, client):
        client.post("/household/appliances", json={"appliance": AC})
        response = client.put(
            "/household/appliances", json={"appliances": [FRIDGE]}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["appliances"][0]["name"] == "冰箱"

    def test_save_all_can_clear(self, client):
        client.post("/household/appliances", json={"appliance": AC})
        response = client.put("/household/appliances", json={"appliances": []})
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_invalid_appliance_is_rejected_before_persisting(self, client):
        response = client.post(
            "/household/appliances",
            json={"appliance": {"name": "Bad", "power_watts": 0, "hours_per_day": 1}},
        )
        assert response.status_code == 422
        assert client.get("/household/appliances").json()["count"] == 0

    def test_invalid_save_all_is_rejected_before_persisting(self, client):
        client.post("/household/appliances", json={"appliance": AC})
        response = client.put(
            "/household/appliances",
            json={"appliances": [{"name": "Bad", "power_watts": -5, "hours_per_day": 1}]},
        )
        assert response.status_code == 422
        # The previous household must survive a rejected save.
        assert client.get("/household/appliances").json()["count"] == 1


class TestDashboard:
    def test_dashboard_uses_the_saved_household(self, client):
        client.post("/household/appliances", json={"appliance": AC})
        client.post("/household/appliances", json={"appliance": FRIDGE})
        body = client.post("/household/dashboard", json={"month": 8}).json()
        assert body["source"] == "saved"
        assert body["appliance_count"] == 2
        assert body["summary"]["total_monthly_kwh"] == pytest.approx(255.6)

    def test_dashboard_accepts_an_unsaved_scratchpad(self, client):
        body = client.post(
            "/household/dashboard", json={"appliances": [AC], "month": 8}
        ).json()
        assert body["source"] == "request"
        assert body["appliance_count"] == 1
        assert body["summary"]["total_monthly_kwh"] == pytest.approx(162.0)

    def test_dashboard_does_not_persist_the_scratchpad(self, client):
        client.post("/household/dashboard", json={"appliances": [AC]})
        assert client.get("/household/appliances").json()["count"] == 0

    def test_dashboard_summary_matches_the_individual_endpoints(self, client):
        consumption = client.post(
            "/calculate/consumption", json={"appliances": [AC, FRIDGE]}
        ).json()
        bill = client.post(
            "/calculate/cost",
            json={"consumption_kwh": consumption["total_monthly_kwh"], "month": 8},
        ).json()
        dashboard = client.post(
            "/household/dashboard", json={"appliances": [AC, FRIDGE], "month": 8}
        ).json()
        assert dashboard["summary"]["total_monthly_kwh"] == pytest.approx(
            consumption["total_monthly_kwh"], abs=0.01
        )
        assert dashboard["summary"]["estimated_monthly_cost_twd"] == pytest.approx(
            bill["total_amount"], abs=0.01
        )

    def test_dashboard_handles_an_empty_household(self, client):
        body = client.post("/household/dashboard", json={"month": 8}).json()
        assert body["appliance_count"] == 0
        assert body["summary"]["total_monthly_kwh"] == 0
        assert body["summary"]["estimated_monthly_cost_twd"] == 0
        assert body["load"] is None
        assert body["recommendations"] is None

    def test_dashboard_reports_the_load_verdict(self, client):
        body = client.post(
            "/household/dashboard",
            json={
                "appliances": [
                    {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110},
                    {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110},
                ],
                "load_limit_amps": 15,
            },
        ).json()
        assert body["summary"]["load_verdict"] == "over_limit"
        assert body["summary"]["load_severity"] == "danger"
        assert body["load"]["disclaimer_zh"]

    def test_dashboard_can_skip_recommendations(self, client):
        body = client.post(
            "/household/dashboard",
            json={"appliances": [AC], "include_recommendations": False},
        ).json()
        assert body["recommendations"] is None
        assert body["summary"]["potential_monthly_saving_kwh"] is None

    def test_dashboard_rejects_invalid_appliances(self, client):
        response = client.post(
            "/household/dashboard",
            json={"appliances": [{"name": "x", "power_watts": 0, "hours_per_day": 1}]},
        )
        assert response.status_code == 422

    def test_dashboard_passes_proration_errors_through(self, client):
        response = client.post(
            "/household/dashboard",
            json={
                "appliances": [AC],
                "plan_id": "flat_rate_resell_reference",
                "billing_months": 2,
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == "plan_does_not_support_billing_months"

    def test_dashboard_is_json_serialisable(self, client):
        import json

        body = client.post("/household/dashboard", json={"appliances": [AC], "month": 8}).json()
        assert json.loads(json.dumps(body))["appliance_count"] == 1
