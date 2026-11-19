"""The product-recommendation endpoint must price savings with the real tariff.

The delivered version had ``tariff = 4.0  # Temporary default`` written into the endpoint.
That breaks the project's central rule (rates live in ``tariffs.json``, never in code) and
would quote savings that disagree with ``/calculate/cost``. These tests keep it honest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app

REPO = Path(__file__).resolve().parent.parent

APPLIANCE = {
    "name": "冷氣機",
    "category": "cooling",
    "power_watts": 900,
    "hours_per_day": 9,
    "days_per_month": 30,
    "voltage": 220,
}

PRODUCT = {
    "id": 1,
    "name": "一級能效變頻冷氣",
    "brand": "Demo",
    "model": "AC-700",
    "category": "cooling",
    "power_watts": 700,
    "price": 23900,
    "currency": "TWD",
    "energy_rating": "1",
    "is_active": True,
}


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _effective_rate(client: TestClient) -> float:
    # /calculate/cost requires consumption_kwh but recomputes it from the appliance list
    # when appliances are supplied (same convention the docs use).
    response = client.post(
        "/calculate/cost",
        json={"consumption_kwh": 0, "appliances": [APPLIANCE], "month": 8},
    )
    assert response.status_code == 200, response.text
    return response.json()["effective_rate_per_kwh"]


class TestNoHardcodedRate:
    def test_the_endpoint_does_not_fix_a_rate(self):
        source = (REPO / "app" / "main.py").read_text(encoding="utf-8")
        assert "tariff = 4.0" not in source, "a hardcoded tariff is back"
        assert "# Temporary default tariff" not in source

    def test_it_uses_the_bill_calculator(self):
        """The rate must be derived, not invented."""

        source = (REPO / "app" / "main.py").read_text(encoding="utf-8")
        start = source.index("async def product_recommendations_endpoint")
        body = source[start : source.index("# --- 5. Simulation", start)]
        assert "calculate_bill(" in body
        assert "effective_rate_per_kwh" in body


class TestSavingsUseTheTariffTable:
    def test_savings_match_the_bill_rate(self, client, monkeypatch):
        monkeypatch.setattr(main_module, "get_products", lambda: [PRODUCT])

        response = client.post(
            "/product-recommendations",
            json={"appliances": [APPLIANCE], "month": 8},
        )
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["total"] == 1
        item = payload["recommendations"][0]

        # (900 - 700) W x 9 h x 30 d = 54 kWh saved
        assert item["estimated_savings_kwh"] == pytest.approx(54.0)

        rate = _effective_rate(client)
        assert payload["rate_per_kwh"] == pytest.approx(rate, rel=1e-3)
        assert item["estimated_savings_cost"] == pytest.approx(54.0 * rate, rel=1e-3)

    def test_the_rate_follows_the_plan_and_season(self, client, monkeypatch):
        """A different plan or month must move the quoted savings."""

        monkeypatch.setattr(main_module, "get_products", lambda: [PRODUCT])
        august = client.post(
            "/product-recommendations", json={"appliances": [APPLIANCE], "month": 8}
        ).json()["rate_per_kwh"]
        november = client.post(
            "/product-recommendations", json={"appliances": [APPLIANCE], "month": 11}
        ).json()["rate_per_kwh"]

        assert august != november, "summer and non-summer rates should differ"
        assert august > november

    def test_a_broken_catalogue_does_not_break_the_endpoint(self, client, monkeypatch):
        """Product advice is an extra; the rest of the app must keep working."""

        def boom():
            raise RuntimeError("Could not fetch products from Supabase: 404")

        monkeypatch.setattr(main_module, "get_products", boom)
        response = client.post(
            "/product-recommendations",
            json={"appliances": [APPLIANCE], "month": 8},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["recommendations"] == []
        assert "warning" in payload

    def test_no_match_means_no_recommendations(self, client, monkeypatch):
        monkeypatch.setattr(
            main_module,
            "get_products",
            lambda: [{**PRODUCT, "category": "lighting"}],
        )
        payload = client.post(
            "/product-recommendations",
            json={"appliances": [APPLIANCE], "month": 8},
        ).json()
        assert payload["total"] == 0
        assert payload["recommendations"] == []

    def test_a_more_powerful_product_is_not_recommended(self, client, monkeypatch):
        monkeypatch.setattr(
            main_module,
            "get_products",
            lambda: [{**PRODUCT, "power_watts": 1200}],
        )
        payload = client.post(
            "/product-recommendations",
            json={"appliances": [APPLIANCE], "month": 8},
        ).json()
        assert payload["total"] == 0
