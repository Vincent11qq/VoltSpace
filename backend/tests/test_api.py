"""API tests using FastAPI's TestClient (httpx based).

These tests cover the five Member C endpoints plus validation/error behaviour that
Member A needs to rely on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

AC = {
    "appliance_id": "a1",
    "name": "冷氣機",
    "category": "cooling",
    "power_watts": 900,
    "hours_per_day": 6,
    "days_per_month": 30,
    "voltage": 220,
}
FRIDGE = {
    "appliance_id": "a2",
    "name": "冰箱",
    "category": "cooling",
    "power_watts": 130,
    "hours_per_day": 24,
    "days_per_month": 30,
    "voltage": 110,
}
PC = {
    "appliance_id": "a3",
    "name": "桌上型電腦",
    "power_watts": 250,
    "hours_per_day": 6,
    "days_per_month": 30,
    "voltage": 110,
}
HAIR_DRYER = {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110}
HEATER = {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110}


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


class TestServiceEndpoints:
    def test_api_index_lists_the_endpoints(self, client):
        response = client.get("/api")
        assert response.status_code == 200
        body = response.json()
        assert "POST /calculate/consumption" in body["endpoints"]
        assert body["ui"] == "/"

    def test_root_serves_the_ui(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "VoltSpace" in response.text

    def test_ui_assets_are_served(self, client):
        css = client.get("/app/app.css")
        js = client.get("/app/app.js")
        assert css.status_code == 200 and len(css.text) > 500
        assert js.status_code == 200 and len(js.text) > 500

    def test_ui_html_and_js_agree_on_element_ids(self):
        """A missing element id would show up only as a silently broken page.

        The page cannot be rendered in CI, so this statically checks that every id the
        script looks up exists in the HTML, and that the HTML is well formed.
        """

        from tools.check_web_ui import IdCollector, WEB
        import re

        index = (WEB / "index.html").read_text(encoding="utf-8")
        script = (WEB / "app.js").read_text(encoding="utf-8")

        parser = IdCollector()
        parser.feed(index)
        html_ids = set(parser.ids)
        script_ids = set(re.findall(r'\$\("([^"]+)"\)', script))

        assert not parser.errors, parser.errors
        assert script_ids, "the script should look up at least one element"
        assert sorted(script_ids - html_ids) == [], "script expects ids missing from the HTML"

    def test_ui_does_not_reimplement_the_physics_or_tariffs(self, client):
        """The prototype's client-side maths and hard-coded numbers must be gone."""

        js = client.get("/app/app.js").text
        # Strip comments so documentation is not mistaken for behaviour.
        import re

        code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        for forbidden in ("1650", "3.5", "/ 110", "/110"):
            assert forbidden not in code, f"app.js must not hard-code {forbidden!r}"
        # And it must actually call the calculation API.
        assert "/household/dashboard" in code

    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["tariff_default_plan"] == "tw_residential_tiered"
        assert body["appliance_catalog_count"] > 0

    def test_openapi_schema_builds_and_documents_five_required_endpoints(self, client):
        schema = client.get("/openapi.json").json()
        for path in (
            "/calculate/consumption",
            "/calculate/cost",
            "/calculate/load",
            "/recommendations",
            "/simulate",
        ):
            assert path in schema["paths"], path
            assert "post" in schema["paths"][path]

    def test_swagger_ui_is_served(self, client):
        assert client.get("/docs").status_code == 200

    def test_tariffs_endpoint_lists_plans(self, client):
        body = client.get("/tariffs").json()
        ids = {plan["id"] for plan in body["plans"]}
        assert {"tw_residential_tiered", "tw_residential_tou", "flat_rate_resell_reference"} <= ids
        assert body["default_plan_id"] == "tw_residential_tiered"

    def test_appliances_endpoint_lists_catalog(self, client):
        body = client.get("/appliances").json()
        assert body["count"] > 0
        assert body["defaults"]["voltage_v"] == 110


class TestConsumptionEndpoint:
    URL = "/calculate/consumption"

    def test_single_appliance(self, client):
        response = client.post(self.URL, json={"appliances": [AC]})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["total_monthly_kwh"] == pytest.approx(162.0)
        assert body["highest_consumption_appliance"] == "冷氣機"
        assert body["appliances"][0]["share_of_total_percent"] == pytest.approx(100.0)

    def test_multiple_appliances(self, client):
        body = client.post(self.URL, json={"appliances": [AC, FRIDGE, PC]}).json()
        assert body["count"] == 3
        assert body["total_monthly_kwh"] == pytest.approx(300.6)
        assert body["total_daily_kwh"] == pytest.approx(10.02)

    def test_editing_power_and_hours_is_reflected(self, client):
        first = client.post(self.URL, json={"appliances": [AC]}).json()
        edited = client.post(
            self.URL,
            json={"appliances": [{**AC, "power_watts": 1800, "hours_per_day": 3}]},
        ).json()
        assert first["total_monthly_kwh"] == pytest.approx(162.0)
        assert edited["total_monthly_kwh"] == pytest.approx(1800 / 1000 * 3 * 30)

    def test_defaults_are_applied(self, client):
        body = client.post(
            self.URL, json={"appliances": [{"name": "TV", "power_watts": 100, "hours_per_day": 3}]}
        ).json()
        assert body["appliances"][0]["days_per_month"] == 30
        assert body["appliances"][0]["quantity"] == 1
        assert body["total_monthly_kwh"] == pytest.approx(9.0)

    def test_response_matches_manual_formula(self, client):
        body = client.post(self.URL, json={"appliances": [HAIR_DRYER]}).json()
        assert body["total_monthly_kwh"] == pytest.approx(1200 / 1000 * 0.3 * 30)

    @pytest.mark.parametrize(
        "payload,expected_field",
        [
            ({"appliances": [{"name": "x", "power_watts": 0, "hours_per_day": 1}]}, "appliances.0.power_watts"),
            ({"appliances": [{"name": "x", "power_watts": 100, "hours_per_day": 25}]}, "appliances.0.hours_per_day"),
            ({"appliances": [{"name": "x", "power_watts": 100, "hours_per_day": 1, "days_per_month": 40}]}, "appliances.0.days_per_month"),
            ({"appliances": [{"name": "x", "power_watts": 100, "hours_per_day": 1, "quantity": 0}]}, "appliances.0.quantity"),
        ],
    )
    def test_invalid_values_return_422_with_the_offending_field(
        self, client, payload, expected_field
    ):
        response = client.post(self.URL, json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["error"] is True
        assert body["code"] == "validation_error"
        assert body["field"] == expected_field

    def test_empty_appliance_list_is_rejected(self, client):
        assert client.post(self.URL, json={"appliances": []}).status_code == 422

    def test_missing_required_field_is_rejected(self, client):
        response = client.post(self.URL, json={"appliances": [{"name": "x"}]})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    def test_wrong_type_is_rejected(self, client):
        response = client.post(
            self.URL, json={"appliances": [{**AC, "power_watts": "lots"}]}
        )
        assert response.status_code == 422

    def test_blank_name_is_rejected(self, client):
        response = client.post(self.URL, json={"appliances": [{**AC, "name": "   "}]})
        assert response.status_code == 422

    def test_exactly_744_hours_is_allowed(self, client):
        """24 h/day for all 31 days is the boundary and must still be calculable."""

        response = client.post(
            self.URL,
            json={"appliances": [{**FRIDGE, "hours_per_day": 24, "days_per_month": 31}]},
        )
        assert response.status_code == 200
        assert response.json()["total_monthly_kwh"] == pytest.approx(130 / 1000 * 24 * 31)

    def test_hours_beyond_a_month_is_rejected(self, client):
        """A schedule that cannot physically fit in a month is refused."""

        response = client.post(
            self.URL,
            json={"appliances": [{**AC, "hours_per_day": 24, "days_per_month": 40}]},
        )
        assert response.status_code == 422

    def test_unknown_extra_field_is_rejected(self, client):
        """extra='forbid' catches typos from the frontend early."""

        response = client.post(self.URL, json={"appliances": [{**AC, "wattage": 900}]})
        assert response.status_code == 422

    def test_validation_error_lists_every_problem(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [
                    {"name": "x", "power_watts": 0, "hours_per_day": 99},
                    {"name": "y", "power_watts": -5, "hours_per_day": 1},
                ]
            },
        )
        assert response.status_code == 422
        details = response.json()["details"]
        assert len(details) >= 2
        assert {"field", "message", "type"} <= set(details[0])

    def test_suspicious_but_valid_values_return_warnings_not_errors(self, client):
        response = client.post(
            self.URL, json={"appliances": [{**AC, "power_watts": 25_000}]}
        )
        assert response.status_code == 200
        warnings = response.json()["appliances"][0]["warnings"]
        assert any(item["code"] == "very_high_power" for item in warnings)

    def test_zero_usage_is_valid(self, client):
        response = client.post(
            self.URL, json={"appliances": [{**AC, "hours_per_day": 0}]}
        )
        assert response.status_code == 200
        assert response.json()["total_monthly_kwh"] == 0.0

    def test_malformed_json_returns_422(self, client):
        response = client.post(
            self.URL, content=b"{not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 422


class TestCostEndpoint:
    URL = "/calculate/cost"

    def test_summer_bill_with_tier_breakdown(self, client):
        response = client.post(self.URL, json={"consumption_kwh": 800, "month": 8})
        assert response.status_code == 200
        body = response.json()
        assert body["season"] == "summer"
        # Current table (2025-10-01): 1.78*120 + 2.55*210 + 3.80*170 + 5.14*200 + 6.44*100
        assert body["total_amount"] == pytest.approx(3067.1)
        assert len(body["lines"]) == 5
        assert body["lines"][0]["rate_per_kwh"] == 1.78
        assert body["currency"] == "TWD"

    def test_non_summer_bill(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 800, "month": 1}).json()
        assert body["season"] == "non_summer"
        assert body["total_amount"] == pytest.approx(2595.3)

    def test_season_can_be_forced(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 800, "season": "summer"}).json()
        assert body["season"] == "summer"

    def test_bi_monthly_bill_scales_the_tiers(self, client):
        body = client.post(
            self.URL, json={"consumption_kwh": 1040, "month": 8, "billing_period": "bi_monthly"}
        ).json()
        assert body["billing_months"] == 2
        assert body["lines"][1]["range_to_kwh"] == pytest.approx(660.0)

    def test_billing_months_overrides_period(self, client):
        body = client.post(
            self.URL,
            json={
                "consumption_kwh": 1040,
                "month": 8,
                "billing_period": "monthly",
                "billing_months": 2,
            },
        ).json()
        assert body["billing_months"] == 2

    def test_flat_landlord_rate(self, client):
        body = client.post(
            self.URL,
            json={"consumption_kwh": 400, "plan_id": "flat_rate_resell_reference"},
        ).json()
        assert body["total_amount"] == pytest.approx(2200.0)
        assert any(item["code"] == "landlord_resale_rate" for item in body["warnings"])

    def test_time_of_use_plan(self, client):
        body = client.post(
            self.URL,
            json={
                "consumption_kwh": 1000,
                "month": 8,
                "plan_id": "tw_residential_tou",
                "peak_share": 0.4,
            },
        ).json()
        assert len(body["lines"]) == 2
        assert body["total_amount"] == pytest.approx(400 * 5.16 + 600 * 2.13)

    def test_consumption_can_come_from_an_appliance_list(self, client):
        body = client.post(
            self.URL, json={"consumption_kwh": 0, "month": 8, "appliances": [AC, FRIDGE]}
        ).json()
        assert body["consumption_source"] == "appliance_list"
        assert body["computed_total_monthly_kwh"] == pytest.approx(255.6)
        assert body["consumption_kwh"] == pytest.approx(255.6)

    def test_input_kwh_source_is_reported(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 100, "month": 8}).json()
        assert body["consumption_source"] == "input_kwh"
        assert body["computed_total_monthly_kwh"] is None

    def test_zero_consumption(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 0, "month": 8}).json()
        assert body["total_amount"] == 0.0
        # The response keeps its shape: one illustrative tier at 0 kWh.
        assert len(body["lines"]) == 1
        assert body["lines"][0]["kwh_in_tier"] == 0.0
        assert any(item["code"] == "no_consumption" for item in body["warnings"])

    def test_effective_rate_is_included(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 500, "month": 8}).json()
        assert body["effective_rate_per_kwh"] == pytest.approx(
            body["total_amount"] / 500, rel=1e-4
        )

    def test_unknown_plan_returns_400(self, client):
        response = client.post(
            self.URL, json={"consumption_kwh": 100, "plan_id": "not_a_plan"}
        )
        assert response.status_code == 422  # rejected by the Literal type first

    def test_negative_consumption_returns_422(self, client):
        response = client.post(self.URL, json={"consumption_kwh": -5, "month": 8})
        assert response.status_code == 422

    def test_invalid_month_returns_422(self, client):
        response = client.post(self.URL, json={"consumption_kwh": 100, "month": 13})
        assert response.status_code == 422

    def test_invalid_billing_period_returns_422(self, client):
        response = client.post(
            self.URL, json={"consumption_kwh": 100, "billing_period": "weekly"}
        )
        assert response.status_code == 422

    def test_invalid_peak_share_returns_422(self, client):
        response = client.post(
            self.URL, json={"consumption_kwh": 100, "plan_id": "tw_residential_tou", "peak_share": 2}
        )
        assert response.status_code == 422

    def test_estimate_disclaimer_is_present(self, client):
        body = client.post(self.URL, json={"consumption_kwh": 500, "month": 8}).json()
        assert any(item["code"] == "estimate_only" for item in body["warnings"])


class TestLoadEndpoint:
    URL = "/calculate/load"

    def test_single_appliance_current(self, client):
        body = client.post(self.URL, json={"appliances": [HAIR_DRYER], "load_limit_amps": 15}).json()
        assert body["estimated_total_current_amps"] == pytest.approx(10.9091, rel=1e-4)
        assert body["verdict"] == "safe"

    def test_over_limit_warning(self, client):
        heavy = {"name": "電熱水器", "power_watts": 1700, "hours_per_day": 1, "voltage": 110}
        body = client.post(self.URL, json={"appliances": [heavy], "load_limit_amps": 15}).json()
        assert body["verdict"] == "over_limit"
        assert body["severity"] == "danger"
        assert "超過上限" in body["verdict_message_zh"]

    def test_near_limit_warning(self, client):
        heavy = {"name": "吹風機", "power_watts": 1400, "hours_per_day": 0.3, "voltage": 110}
        body = client.post(self.URL, json={"appliances": [heavy], "load_limit_amps": 15}).json()
        assert body["verdict"] == "near_limit"
        assert body["severity"] == "warning"

    def test_combined_current_is_summed(self, client):
        body = client.post(
            self.URL,
            json={"appliances": [HAIR_DRYER, HEATER], "load_limit_amps": 15},
        ).json()
        assert body["estimated_total_current_amps"] == pytest.approx(21.818, rel=1e-3)
        assert body["verdict"] == "over_limit"
        assert body["highest_current_appliance"]["current_amps"] == pytest.approx(10.909, rel=1e-3)

    def test_no_limit_returns_informational_verdict(self, client):
        body = client.post(self.URL, json={"appliances": [PC]}).json()
        assert body["verdict"] == "no_limit"
        assert body["severity"] == "info"
        assert body["usage_percent_of_limit"] is None

    def test_voltage_is_taken_from_the_appliance_when_omitted(self, client):
        """An appliance without an explicit voltage falls back to the schema default."""

        body = client.post(
            self.URL,
            json={
                "appliances": [{"name": "Load", "power_watts": 2200, "hours_per_day": 1}],
                "load_limit_amps": 25,
            },
        ).json()
        assert body["voltage_used"] == 110
        assert body["appliances"][0]["voltage"] == 110
        assert body["estimated_total_current_amps"] == pytest.approx(20.0)

    def test_appliance_voltage_takes_precedence_over_the_request_voltage(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [
                    {"name": "Load", "power_watts": 2200, "hours_per_day": 1, "voltage": 220}
                ],
                "voltage": 110,
                "load_limit_amps": 15,
            },
        ).json()
        assert body["appliances"][0]["voltage"] == 220
        assert body["estimated_total_current_amps"] == pytest.approx(10.0)

    def test_request_voltage_is_used_when_an_appliance_omits_it(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [{"name": "Load", "power_watts": 2200, "hours_per_day": 1}],
                "voltage": 220,
                "load_limit_amps": 15,
            },
        ).json()
        assert body["appliances"][0]["voltage"] == 220
        assert body["estimated_total_current_amps"] == pytest.approx(10.0)

    def test_voltage_falls_back_to_110_when_nothing_is_given(self, client):
        body = client.post(
            self.URL,
            json={"appliances": [{"name": "Load", "power_watts": 2200, "hours_per_day": 1}]},
        ).json()
        assert body["voltage_used"] == 110
        assert body["estimated_total_current_amps"] == pytest.approx(20.0)

    def test_safety_margin_changes_the_verdict(self, client):
        payload = {"appliances": [{"name": "吹風機", "power_watts": 1400, "hours_per_day": 0.3, "voltage": 110}], "load_limit_amps": 15}
        strict = client.post(self.URL, json={**payload, "safety_margin": 0.5}).json()
        relaxed = client.post(self.URL, json={**payload, "safety_margin": 1.0}).json()
        assert strict["verdict"] == "near_limit"
        assert relaxed["verdict"] == "safe"

    def test_breaker_note(self, client):
        body = client.post(
            self.URL, json={"appliances": [PC], "load_limit_amps": 15, "breaker_amps": 20}
        ).json()
        assert any(item["code"] == "socket_vs_breaker" for item in body["warnings"])

    def test_circuit_label_is_echoed(self, client):
        body = client.post(
            self.URL,
            json={"appliances": [PC], "load_limit_amps": 15, "circuit_label": "房間插座迴路"},
        ).json()
        assert body["circuit_label"] == "房間插座迴路"

    def test_overload_combinations_are_optional(self, client):
        payload = {
            "appliances": [HAIR_DRYER, HEATER],
            "load_limit_amps": 15,
            "include_overload_combinations": True,
        }
        body = client.post(self.URL, json=payload).json()
        assert body["overload_combinations"]["combination_size"] == 2
        assert body["overload_combinations"]["combinations"]

    def test_overload_combinations_absent_by_default(self, client):
        body = client.post(self.URL, json={"appliances": [HAIR_DRYER], "load_limit_amps": 15}).json()
        assert body["overload_combinations"] is None

    def test_safety_disclaimer_is_always_returned(self, client):
        body = client.post(self.URL, json={"appliances": [PC], "load_limit_amps": 15}).json()
        assert "不構成電路安全保證" in body["disclaimer_zh"]
        assert "not a guarantee" in body["disclaimer_en"]
        codes = {item["code"] for item in body["warnings"]}
        assert {"disclaimer", "running_current_only"} <= codes

    def test_invalid_limit_returns_422(self, client):
        assert client.post(
            self.URL, json={"appliances": [PC], "load_limit_amps": 0}
        ).status_code == 422

    def test_invalid_safety_margin_returns_422(self, client):
        assert client.post(
            self.URL, json={"appliances": [PC], "load_limit_amps": 15, "safety_margin": 0}
        ).status_code == 422

    def test_empty_appliance_list_returns_422(self, client):
        assert client.post(self.URL, json={"appliances": []}).status_code == 422

    def test_three_phase_is_actually_applied(self, client):
        """Regression: `phases: 3` was echoed back but never used in the formula."""

        motor = {"name": "Motor", "power_watts": 3000, "hours_per_day": 1, "voltage": 220}
        single = client.post(
            self.URL, json={"appliances": [motor], "phases": 1, "load_limit_amps": 15}
        ).json()
        three = client.post(
            self.URL, json={"appliances": [motor], "phases": 3, "load_limit_amps": 15}
        ).json()
        assert three["phases"] == 3
        assert single["estimated_total_current_amps"] == pytest.approx(13.6364, rel=1e-4)
        assert three["estimated_total_current_amps"] == pytest.approx(7.8730, rel=1e-4)
        # The verdict must reflect the three-phase current, not the single-phase one.
        assert single["verdict"] == "near_limit"
        assert three["verdict"] == "safe"

    def test_three_phase_flows_into_the_overload_combination_search(self, client):
        payload = {
            "appliances": [
                {"name": "Motor A", "power_watts": 3000, "hours_per_day": 1, "voltage": 220},
                {"name": "Motor B", "power_watts": 3000, "hours_per_day": 1, "voltage": 220},
            ],
            "load_limit_amps": 15,
            "phases": 3,
            "include_overload_combinations": True,
        }
        body = client.post(self.URL, json=payload).json()
        assert body["overload_combinations"]["combination_size"] == 2
        assert body["overload_combinations"]["combinations"][0][
            "total_current_amps"
        ] == pytest.approx(15.7459, rel=1e-3)

    def test_power_factor_is_applied(self, client):
        """Regression: power_factor used to be unreachable from the API (extra='forbid')."""

        motor = {"name": "Motor", "power_watts": 1000, "hours_per_day": 1, "voltage": 110}
        resistive = client.post(
            self.URL, json={"appliances": [dict(motor, power_factor=1.0)], "load_limit_amps": 15}
        ).json()
        inductive = client.post(
            self.URL, json={"appliances": [dict(motor, power_factor=0.8)], "load_limit_amps": 15}
        ).json()
        assert resistive["estimated_total_current_amps"] == pytest.approx(9.0909, rel=1e-4)
        assert inductive["estimated_total_current_amps"] == pytest.approx(11.3636, rel=1e-4)
        assert inductive["appliances"][0]["power_factor"] == 0.8
        # Higher current must also raise the reported apparent power.
        assert inductive["total_apparent_power_va"] > resistive["total_apparent_power_va"]

    def test_power_factor_defaults_to_one(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [{"name": "Load", "power_watts": 1000, "hours_per_day": 1, "voltage": 110}]
            },
        ).json()
        assert body["appliances"][0]["power_factor"] == 1.0
        assert body["estimated_total_current_amps"] == pytest.approx(9.0909, rel=1e-4)

    @pytest.mark.parametrize("power_factor", [0.05, 1.5, -1])
    def test_invalid_power_factor_is_rejected(self, client, power_factor):
        response = client.post(
            self.URL,
            json={
                "appliances": [
                    {
                        "name": "Motor",
                        "power_watts": 1000,
                        "hours_per_day": 1,
                        "voltage": 110,
                        "power_factor": power_factor,
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["field"] == "appliances.0.power_factor"

    def test_power_factor_is_accepted_by_other_endpoints(self, client):
        """The field is part of the shared appliance schema, so every endpoint accepts it."""

        appliance = {
            "name": "冷氣機",
            "power_watts": 900,
            "hours_per_day": 6,
            "days_per_month": 30,
            "voltage": 220,
            "power_factor": 0.9,
        }
        for path, extra in (
            ("/calculate/consumption", {}),
            ("/calculate/cost", {"consumption_kwh": 0}),
            ("/recommendations", {"month": 8}),
            (
                "/simulate",
                {"changes": [{"name": "冷氣機", "field": "hours_per_day", "value": 4}]},
            ),
        ):
            response = client.post(path, json={"appliances": [appliance], **extra})
            assert response.status_code == 200, (path, response.status_code, response.text[:200])


class TestRecommendationsEndpoint:
    URL = "/recommendations"

    def test_returns_recommendations_with_reasons_and_savings(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [
                    {**AC, "hours_per_day": 9},
                    FRIDGE,
                ],
                "month": 8,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["recommendation_count"] > 0
        for item in body["recommendations"]:
            assert item["reason_zh"]
            assert item["suggestion_zh"]
            assert item["assumption_zh"]
            assert item["estimated_monthly_saving_kwh"] >= 0

    def test_top_consumers_are_ranked(self, client):
        body = client.post(self.URL, json={"appliances": [AC, FRIDGE, PC], "month": 8}).json()
        assert body["top_consumers"][0]["appliance"] == "冷氣機"
        assert body["top_consumers"][0]["monthly_kwh"] == pytest.approx(162.0)

    def test_totals_are_aggregated(self, client):
        body = client.post(self.URL, json={"appliances": [AC, FRIDGE], "month": 8}).json()
        assert body["total_potential_monthly_saving_twd"] >= 0
        assert body["total_potential_annual_saving_twd"] == pytest.approx(
            body["total_potential_monthly_saving_twd"] * 12, abs=0.05
        )
        assert 0 <= body["potential_saving_percent_of_usage"] <= 100

    def test_top_n_option(self, client):
        body = client.post(
            self.URL, json={"appliances": [AC, FRIDGE, PC], "month": 8, "top_n": 1}
        ).json()
        assert len(body["top_consumers"]) == 1
        assert body["top_consumers"][0]["appliance"] == "冷氣機"

    def test_max_recommendations_option(self, client):
        body = client.post(
            self.URL, json={"appliances": [AC, FRIDGE, PC], "month": 8, "max_recommendations": 1}
        ).json()
        assert len(body["recommendations"]) == 1

    def test_purchase_advice_is_generated_for_an_inefficient_appliance(self, client):
        body = client.post(
            self.URL,
            json={"appliances": [{**AC, "power_watts": 1400, "hours_per_day": 8}], "month": 8},
        ).json()
        swaps = [item for item in body["recommendations"] if item.get("is_purchase_advice")]
        assert swaps
        assert swaps[0]["alternative_power_watts"] == 700

    def test_no_ai_model_is_required(self, client):
        """A rule-based catalogue match must work without any trained artefact."""

        body = client.post(self.URL, json={"appliances": [FRIDGE], "month": 8}).json()
        ids = {item["id"] for item in body["recommendations"]}
        assert "fridge_always_on" in ids

    def test_plan_id_changes_the_valued_saving(self, client):
        tiered = client.post(
            self.URL,
            json={"appliances": [{**AC, "hours_per_day": 9}], "month": 8},
        ).json()
        flat = client.post(
            self.URL,
            json={
                "appliances": [{**AC, "hours_per_day": 9}],
                "plan_id": "flat_rate_resell_reference",
            },
        ).json()
        assert flat["blended_rate_per_kwh"] == pytest.approx(5.5)
        assert tiered["blended_rate_per_kwh"] != pytest.approx(5.5)

    def test_disclaimer_is_present(self, client):
        body = client.post(self.URL, json={"appliances": [AC], "month": 8}).json()
        assert "不保證" in body["disclaimer_zh"]

    def test_chinese_alias_names_reach_the_catalogue(self, client):
        """Regression: 電冰箱 fell through to generic advice while 冰箱 matched."""

        for name in ("冰箱", "電冰箱", "小冰箱"):
            body = client.post(
                self.URL,
                json={
                    "appliances": [
                        {"name": name, "power_watts": 130, "hours_per_day": 24, "voltage": 110}
                    ],
                    "month": 8,
                },
            ).json()
            assert body["per_appliance"][0]["matched_catalog_key"] == "refrigerator", name
            ids = {item["id"] for item in body["recommendations"]}
            assert "fridge_always_on" in ids, name

    def test_empty_list_is_rejected(self, client):
        assert client.post(self.URL, json={"appliances": []}).status_code == 422

    def test_invalid_appliance_is_rejected(self, client):
        assert client.post(
            self.URL, json={"appliances": [{**AC, "power_watts": 0}]}
        ).status_code == 422


class TestSimulateEndpoint:
    URL = "/simulate"

    def test_reduce_hours_reports_the_saving(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [AC, FRIDGE],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 5}],
                "month": 8,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["baseline"]["total_monthly_kwh"] == pytest.approx(255.6)
        assert body["modified"]["total_monthly_kwh"] == pytest.approx(228.6)
        assert body["delta"]["saved_kwh"] == pytest.approx(27.0)
        assert body["delta"]["is_saving"] is True

    def test_bill_comparison_is_included(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [AC, FRIDGE],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 3}],
                "month": 8,
            },
        ).json()
        assert body["baseline"]["estimated_bill_twd"] > body["modified"]["estimated_bill_twd"]
        assert body["delta"]["saved_amount_twd"] == pytest.approx(
            body["baseline"]["estimated_bill_twd"] - body["modified"]["estimated_bill_twd"],
            abs=0.01,
        )

    def test_original_appliances_are_not_modified(self, client):
        original = [dict(AC), dict(FRIDGE)]
        response = client.post(
            self.URL,
            json={
                "appliances": original,
                "changes": [
                    {"appliance_id": "a1", "field": "power_watts", "value": 2000},
                    {"appliance_id": "a1", "field": "hours_per_day", "value": 12},
                ],
                "month": 8,
            },
        )
        assert response.status_code == 200
        # The request payload we sent is untouched (Pydantic never mutates our dict).
        assert original[0]["power_watts"] == 900
        assert original[0]["hours_per_day"] == 6
        body = response.json()
        assert body["baseline"]["appliances"][0]["power_watts"] == 900
        assert body["modified"]["appliances"][0]["power_watts"] == 2000

    def test_replacement_carries_a_label(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [
                    {
                        "appliance_id": "a1",
                        "field": "replace_with",
                        "replacement": {"label": "一級能效變頻冷氣", "power_watts": 700},
                    }
                ],
                "month": 8,
            },
        ).json()
        assert body["modified"]["appliances"][0]["replacement_label"] == "一級能效變頻冷氣"
        assert body["delta"]["saved_kwh"] > 0

    def test_comparison_table_has_a_row_per_appliance(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [AC, FRIDGE],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 4}],
                "month": 8,
            },
        ).json()
        assert len(body["comparison_table"]) == 2
        assert {row["appliance"] for row in body["comparison_table"]} == {"冷氣機", "冰箱"}

    def test_load_comparison_when_a_limit_is_supplied(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [HAIR_DRYER, HEATER],
                "changes": [
                    {
                        "name": "電暖器",
                        "field": "replace_with",
                        "replacement": {"power_watts": 50},
                    }
                ],
                "load_limit_amps": 15,
            },
        ).json()
        assert body["load"]["baseline_verdict"] == "over_limit"
        assert body["load"]["modified_verdict"] == "safe"

    def test_baseline_override(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 3}],
                "month": 8,
                "baseline_override_kwh": 400,
            },
        ).json()
        assert body["baseline"]["total_monthly_kwh"] == pytest.approx(400.0)

    def test_unknown_appliance_returns_400(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [{"appliance_id": "ghost", "field": "hours_per_day", "value": 3}],
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == "appliance_not_found"

    def test_change_without_target_returns_422(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [{"field": "hours_per_day", "value": 3}],
            },
        )
        assert response.status_code == 422

    def test_change_without_value_returns_422(self, client):
        response = client.post(
            self.URL,
            json={"appliances": [AC], "changes": [{"appliance_id": "a1", "field": "hours_per_day"}]},
        )
        assert response.status_code == 422

    def test_replace_with_without_replacement_returns_422(self, client):
        response = client.post(
            self.URL,
            json={"appliances": [AC], "changes": [{"appliance_id": "a1", "field": "replace_with"}]},
        )
        assert response.status_code == 422

    def test_unsupported_change_field_returns_422(self, client):
        response = client.post(
            self.URL,
            json={"appliances": [AC], "changes": [{"appliance_id": "a1", "field": "colour", "value": 1}]},
        )
        assert response.status_code == 422

    def test_fractional_days_is_rejected(self, client):
        response = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [{"appliance_id": "a1", "field": "days_per_month", "value": 15.5}],
            },
        )
        assert response.status_code == 422

    def test_empty_change_list_is_rejected(self, client):
        assert client.post(self.URL, json={"appliances": [AC], "changes": []}).status_code == 422

    def test_notes_are_returned(self, client):
        body = client.post(
            self.URL,
            json={
                "appliances": [AC],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 4}],
            },
        ).json()
        assert any("不會修改" in note for note in body["notes"])

    def test_billing_months_is_forwarded_to_the_bill(self, client):
        """Regression: the schema accepted billing_months while the service ignored it."""

        payload = {
            "appliances": [AC],
            "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 6}],
            "month": 8,
        }
        single = client.post(self.URL, json={**payload, "billing_months": 1}).json()
        double = client.post(self.URL, json={**payload, "billing_months": 2}).json()
        assert single["billing_months"] == 1
        assert double["billing_months"] == 2

        # And it must agree with the dedicated cost endpoint.
        cost = client.post(
            "/calculate/cost",
            json={"consumption_kwh": single["baseline"]["total_monthly_kwh"], "month": 8, "billing_months": 2},
        ).json()
        assert double["baseline"]["estimated_bill_twd"] == pytest.approx(cost["total_amount"])

    def test_renaming_swap_keeps_one_comparison_row(self, client):
        """Regression: a rename split one swap into a bogus 100% saving plus a new row."""

        body = client.post(
            self.URL,
            json={
                "appliances": [
                    {"name": "AC", "power_watts": 1400, "hours_per_day": 8, "voltage": 220}
                ],
                "changes": [
                    {
                        "name": "AC",
                        "field": "replace_with",
                        "replacement": {"name": "NewAC", "power_watts": 700},
                    }
                ],
                "month": 8,
            },
        ).json()
        assert len(body["comparison_table"]) == 1
        row = body["comparison_table"][0]
        assert row["appliance"] == "AC"
        assert row["status"] == "changed"
        assert row["saved_kwh"] == pytest.approx(168.0)
        assert row["replaced_by"] == "NewAC"
        assert body["applied_changes"][0]["new_name"] == "NewAC"

    def test_two_identical_appliances_both_get_advice(self, client):
        """Regression: recommendation dedup by rule id dropped the second appliance."""

        body = client.post(
            "/recommendations",
            json={
                "appliances": [
                    {**AC, "appliance_id": "a1", "hours_per_day": 9},
                    {**AC, "appliance_id": "a2", "hours_per_day": 12},
                ],
                "month": 8,
            },
        ).json()
        matching = [item for item in body["recommendations"] if item["id"] == "ac_hours_high"]
        assert len(matching) == 2
        assert {item["appliance_key"] for item in matching} == {"a1", "a2"}
        keys = [item["recommendation_key"] for item in body["recommendations"]]
        assert len(keys) == len(set(keys))


class TestStartupValidation:
    def test_startup_validates_the_data_files(self, client):
        """A broken data file must abort boot instead of serving wrong numbers."""

        assert hasattr(app.state, "data_summary")
        assert app.state.data_summary["appliance_count"] > 0
        assert "tw_residential_tiered" in app.state.data_summary["plan_ids"]

    def test_startup_fails_when_tariffs_are_invalid(self, monkeypatch):
        from app import main as main_module

        def broken() -> dict:
            raise main_module.DataIntegrityError("tariffs: simulated corruption")

        monkeypatch.setattr(main_module, "validate_all", broken)
        with pytest.raises(RuntimeError, match="simulated corruption"):
            with TestClient(main_module.app):
                pass


class TestSchemaDerivedFromData:
    def test_plan_enum_covers_every_data_file_plan(self):
        from app.calculators.electricity_bill import available_plan_ids
        from app.schemas import PlanId

        assert sorted(member.value for member in PlanId) == available_plan_ids()

    def test_unknown_plan_is_rejected_with_422(self, client):
        response = client.post(
            "/calculate/cost", json={"consumption_kwh": 100, "plan_id": "not_a_plan"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


class TestProrationEnforcement:
    """A plan that cannot price a multi-month period must say so, not guess."""

    @pytest.mark.parametrize(
        "plan_id", ["flat_rate_resell_reference", "tw_residential_tou"]
    )
    def test_cost_rejects_multi_month_period_for_per_kwh_plans(self, client, plan_id):
        response = client.post(
            "/calculate/cost",
            json={"consumption_kwh": 400, "plan_id": plan_id, "billing_months": 2},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "plan_does_not_support_billing_months"
        assert plan_id in body["message"]

    def test_cost_accepts_multi_month_period_for_the_tiered_plan(self, client):
        response = client.post(
            "/calculate/cost",
            json={"consumption_kwh": 1040, "month": 8, "billing_period": "bi_monthly"},
        )
        assert response.status_code == 200
        assert response.json()["billing_months"] == 2

    def test_simulate_surfaces_the_same_error(self, client):
        response = client.post(
            "/simulate",
            json={
                "appliances": [AC],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 4}],
                "plan_id": "flat_rate_resell_reference",
                "billing_months": 2,
            },
        )
        assert response.status_code == 400
        assert response.json()["code"] == "plan_does_not_support_billing_months"


class TestCrossEndpointConsistency:
    """The endpoints must agree with each other for the same household."""

    def test_consumption_total_flows_into_cost(self, client):
        consumption = client.post(
            "/calculate/consumption", json={"appliances": [AC, FRIDGE, PC]}
        ).json()
        cost = client.post(
            "/calculate/cost",
            json={"consumption_kwh": consumption["total_monthly_kwh"], "month": 8},
        ).json()
        cost_from_list = client.post(
            "/calculate/cost", json={"consumption_kwh": 0, "month": 8, "appliances": [AC, FRIDGE, PC]}
        ).json()
        assert cost["total_amount"] == pytest.approx(cost_from_list["total_amount"])

    def test_simulation_baseline_matches_the_consumption_endpoint(self, client):
        consumption = client.post(
            "/calculate/consumption", json={"appliances": [AC, FRIDGE]}
        ).json()
        simulation = client.post(
            "/simulate",
            json={
                "appliances": [AC, FRIDGE],
                "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 5}],
                "month": 8,
            },
        ).json()
        assert simulation["baseline"]["total_monthly_kwh"] == pytest.approx(
            consumption["total_monthly_kwh"], abs=0.01
        )

    def test_recommendation_totals_match_the_consumption_endpoint(self, client):
        consumption = client.post(
            "/calculate/consumption", json={"appliances": [AC, FRIDGE]}
        ).json()
        recommendations = client.post(
            "/recommendations", json={"appliances": [AC, FRIDGE], "month": 8}
        ).json()
        assert recommendations["total_monthly_kwh"] == pytest.approx(
            consumption["total_monthly_kwh"], abs=0.01
        )

    def test_simulated_saving_respects_the_tier_structure(self, client):
        """Money saved should exceed the naive kWh-share estimate under tiers."""

        heavy = [
            {"name": "冷氣機", "power_watts": 2200, "hours_per_day": 12, "voltage": 220},
            {"name": "電熱水器", "power_watts": 4000, "hours_per_day": 2, "voltage": 220},
        ]
        body = client.post(
            "/simulate",
            json={
                "appliances": heavy,
                "changes": [
                    {"name": "電熱水器", "field": "hours_per_day", "value": 1}
                ],
                "month": 8,
            },
        ).json()
        assert body["delta"]["saved_percent_of_amount"] > body["delta"]["saved_percent_of_kwh"]
