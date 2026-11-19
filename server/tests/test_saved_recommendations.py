"""Member B's ``recommendations`` table must actually be written to.

It was delivered as ``Supabase/member-b-latest/recommendations.sql`` and nothing inserted a
row: /product-recommendations computed the advice and forgot it. These tests pin the
persistence, and - just as important - that a broken table can never break the advice.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app import saved_recommendations


ITEM = {
    "appliance": "Air conditioner",
    "product_id": 7,
    "product_name": "Inverter AC",
    "brand": "Demo",
    "price": 23900,
    "estimated_savings_kwh": 54.0,
    "estimated_savings_cost": 117.0,
}


@pytest.fixture()
def supabase(monkeypatch):
    monkeypatch.setenv("VOLTSPACE_SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setenv("VOLTSPACE_SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("VOLTSPACE_HOUSEHOLD_ID", "11111111-1111-1111-1111-111111111111")
    yield
    for name in (
        "VOLTSPACE_SUPABASE_URL",
        "VOLTSPACE_SUPABASE_SERVICE_KEY",
        "VOLTSPACE_HOUSEHOLD_ID",
    ):
        monkeypatch.delenv(name, raising=False)


class TestSave:
    def test_it_posts_one_row_per_recommendation(self, supabase):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            seen["prefer"] = request.headers.get("Prefer")
            return httpx.Response(201)

        count = saved_recommendations.save([ITEM], transport=httpx.MockTransport(handler))

        assert count == 1
        assert seen["url"].endswith("/rest/v1/recommendations")
        row = seen["body"][0]
        assert row["product_id"] == 7
        assert row["household_id"] == "11111111-1111-1111-1111-111111111111"
        assert row["estimated_savings_kwh"] == 54.0
        assert row["estimated_savings_cost"] == 117.0
        assert "Inverter AC" in row["reason"]
        assert seen["prefer"] == "return=minimal"

    def test_nothing_is_sent_without_supabase(self, monkeypatch):
        monkeypatch.delenv("VOLTSPACE_SUPABASE_URL", raising=False)
        monkeypatch.delenv("VOLTSPACE_SUPABASE_SERVICE_KEY", raising=False)
        assert saved_recommendations.save([ITEM]) == 0

    def test_a_missing_table_does_not_raise(self, supabase):
        def handler(_request):
            return httpx.Response(404, json={"message": "relation does not exist"})

        assert saved_recommendations.save([ITEM], transport=httpx.MockTransport(handler)) == 0

    def test_a_foreign_key_failure_does_not_raise(self, supabase):
        """A fresh project may not have the household/appliance rows yet."""

        def handler(_request):
            return httpx.Response(
                409, json={"message": "insert or update violates foreign key constraint"}
            )

        assert saved_recommendations.save([ITEM], transport=httpx.MockTransport(handler)) == 0

    def test_unreachable_host_does_not_raise(self, supabase):
        def handler(_request):
            raise httpx.ConnectError("no route")

        assert saved_recommendations.save([ITEM], transport=httpx.MockTransport(handler)) == 0

    def test_empty_advice_writes_nothing(self, supabase):
        assert saved_recommendations.save([]) == 0

    def test_rows_without_a_product_are_skipped(self, supabase):
        broken = {**ITEM, "product_id": None}
        assert saved_recommendations.save([broken]) == 0


class TestLatest:
    def test_it_reads_the_newest_first(self, supabase):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[{"id": 1, "product_id": 7}])

        rows = saved_recommendations.latest(transport=httpx.MockTransport(handler))

        assert rows == [{"id": 1, "product_id": 7}]
        assert seen["params"]["order"] == "created_at.desc"
        assert seen["params"]["household_id"].startswith("eq.")

    def test_empty_without_supabase(self, monkeypatch):
        monkeypatch.delenv("VOLTSPACE_SUPABASE_URL", raising=False)
        monkeypatch.delenv("VOLTSPACE_SUPABASE_SERVICE_KEY", raising=False)
        assert saved_recommendations.latest() == []

    def test_a_broken_response_is_an_empty_list(self, supabase):
        def handler(_request):
            return httpx.Response(500, text="boom")

        assert saved_recommendations.latest(transport=httpx.MockTransport(handler)) == []


class TestEndpoint:
    def test_the_endpoint_reports_how_many_rows_it_saved(self, client, monkeypatch):
        from app import main as main_module

        monkeypatch.setattr(main_module, "get_products", lambda: [{
            "id": 1, "name": "Inverter AC", "brand": "Demo", "category": "cooling",
            "power_watts": 700, "price": 23900, "is_active": True,
        }])
        payload = client.post(
            "/product-recommendations",
            json={"appliances": [{
                "name": "冷氣機", "category": "cooling", "power_watts": 900,
                "hours_per_day": 9, "days_per_month": 30,
            }], "month": 8},
        ).json()

        # No Supabase in the test environment, so nothing is stored - but the field is there
        # and the advice is unchanged.
        assert payload["saved"] == 0
        assert payload["total"] == 1

    def test_the_saved_list_is_readable(self, client):
        response = client.get("/household/product-recommendations")
        assert response.status_code == 200
        body = response.json()
        assert body == {"recommendations": [], "total": 0}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
