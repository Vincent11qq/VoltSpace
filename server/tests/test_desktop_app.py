"""The desktop UI's data layer: everything comes from the backend, nothing is recomputed.

The screens themselves are exercised by ``tools/check_desktop.py`` against a live server.
These tests cover the mapping logic with a stubbed HTTP layer, so they run fast and offline
- including the guard that the old hardcoded tariff table cannot come back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

flet = pytest.importorskip("flet")  # the desktop UI needs Flet; skip elsewhere

import desktop.app as desktop  # noqa: E402


@pytest.fixture()
def no_http(monkeypatch):
    """Fail loudly if something tries to reach the network."""

    def boom(*_args, **_kwargs):
        raise AssertionError("this test must not perform HTTP requests")

    monkeypatch.setattr(desktop, "request", boom)
    return monkeypatch


class TestPayloadMapping:
    def test_ui_appliance_maps_to_the_api_shape(self):
        row = desktop.to_api(
            {"id": 7, "name": "Air conditioner", "icon": "air_conditioner",
             "watts": 900, "hours": 9, "days": 30, "on": True, "kwh": 243.0}
        )
        assert row["name"] == "Air conditioner"
        assert row["power_watts"] == 900
        assert row["hours_per_day"] == 9
        assert row["days_per_month"] == 30
        assert row["quantity"] == 1

    def test_local_only_fields_are_not_sent(self):
        """The API rejects unknown fields (extra="forbid"), so icon/on must stay local."""

        row = desktop.to_api(
            {"name": "Fan", "icon": "electric_fan", "watts": 45,
             "hours": 8, "days": 30, "on": False, "kwh": 10.8}
        )
        assert "icon" not in row
        assert "on" not in row
        assert "kwh" not in row
        assert "id" not in row


class TestVerdict:
    EXPECTED = {
        "safe": ("safe", "WITHIN MARGIN"),
        "near_limit": ("near", "NEAR LIMIT"),
        "over_limit": ("over", "OVER LIMIT"),
        "no_limit": ("none", "NO LIMIT SET"),
    }

    @pytest.mark.parametrize("verdict", list(EXPECTED))
    def test_backend_verdict_maps_to_a_neutral_label(self, verdict):
        ui_key, label = self.EXPECTED[verdict]
        st = {
            "load": {
                "verdict": verdict,
                "total_power_watts": 1800.0,
                "limit_watts": 3300.0 if verdict != "no_limit" else None,
            }
        }
        pct, key, used, limit = desktop.safety_of(st)
        assert key == ui_key
        assert desktop.STATUS_LABEL[key] == label
        assert used == 1800.0
        if limit:
            assert pct == pytest.approx(1800.0 / 3300.0 * 100, rel=1e-6)

    def test_no_label_claims_safety(self):
        """The project refuses to guarantee electrical safety; the UI must not either."""

        for label in desktop.STATUS_LABEL.values():
            assert "SAFE" not in label.upper(), f"{label!r} claims safety"

    def test_load_line_shows_the_ratio_and_handles_no_limit(self):
        assert "55%" in desktop.load_line(1800, 3300)
        assert "no circuit limit" in desktop.load_line(1800, 0)


class TestMoney:
    def test_cost_breakdown_splits_the_backend_bill_by_usage(self):
        st = {
            "bill": 500.0,
            "total_kwh": 200.0,
            "appliances": [
                {"name": "AC", "kwh": 150.0},
                {"name": "TV", "kwh": 50.0},
            ],
        }
        bill, total, rows = desktop.cost_breakdown(st)
        assert bill == 500.0
        assert total == 200.0
        assert rows[0][2] == pytest.approx(375.0)
        assert rows[1][2] == pytest.approx(125.0)

    def test_no_usage_means_no_division_by_zero(self):
        bill, total, rows = desktop.cost_breakdown({"bill": 0.0, "total_kwh": 0.0, "appliances": []})
        assert (bill, total, rows) == (0.0, 0.0, [])


class TestSuggestions:
    def test_uses_the_backend_recommendations_in_english(self):
        st = {
            "error": None,
            "appliances": [{"name": "Air conditioner"}],
            "recs": [
                {
                    "title_en": "Air conditioner runs more than 8 hours a day",
                    "suggestion_en": "Use a timer.",
                    "estimated_monthly_saving_twd": 51.0,
                }
            ],
        }
        tips = desktop.make_suggestions(st)
        assert len(tips) == 1
        assert "Air conditioner runs more than 8 hours a day" in tips[0]
        assert "Use a timer." in tips[0]
        assert "NT$ 51" in tips[0]

    def test_says_so_when_the_backend_is_unreachable(self):
        tips = desktop.make_suggestions({"error": "cannot reach http://x", "appliances": []})
        assert "Backend unreachable" in tips[0]

    def test_asks_for_appliances_first(self):
        tips = desktop.make_suggestions({"error": None, "appliances": [], "recs": []})
        assert "Add your appliances" in tips[0]


class TestNoReimplementedMaths:
    """The original file hardcoded a summer tariff table; that must not return."""

    SOURCE = Path(desktop.__file__).read_text(encoding="utf-8")

    @pytest.mark.parametrize("rate", ["1.78", "2.55", "3.80", "5.14", "6.44", "8.46", "8.86"])
    def test_no_tariff_rates_in_the_desktop_source(self, rate):
        assert rate not in self.SOURCE, f"{rate} suggests a hardcoded tariff again"

    def test_no_default_tariff_constant(self):
        assert not hasattr(desktop, "DEFAULT_TARIFF")

    def test_there_is_no_local_calculation_of_current(self):
        """Amps must come from /calculate/load, not be derived here."""

        assert "power_factor" not in self.SOURCE
        assert "/ 110" not in self.SOURCE and "* 110" not in self.SOURCE


class TestStoreAgainstStubbedBackend:
    @pytest.fixture()
    def store(self, monkeypatch, tmp_path):
        calls: list[tuple[str, str]] = []

        def fake_request(path, *, method="GET", payload=None, timeout=25):
            calls.append((method, path))
            if path == "/appliances/presets":
                return {
                    "presets": [
                        {"key": "air_conditioner", "name_en": "Air conditioner",
                         "name_zh": "冷氣機", "power_watts": 900, "hours_per_day": 6},
                    ],
                    "circuits": [],
                    "default_circuit_amps": 15,
                    "default_voltage": 110.0,
                }
            if path == "/tariffs":
                return {"default_plan_id": "tw_residential_tiered",
                        "plans": [{"id": "tw_residential_tiered", "name_en": "Taipower tiered"}]}
            if path == "/household/appliances":
                return {"appliances": [
                    {"id": 1, "name": "Air conditioner", "power_watts": 900,
                     "hours_per_day": 9, "days_per_month": 30},
                ]}
            if path == "/household/dashboard":
                return {
                    "consumption": {"total_monthly_kwh": 243.0,
                                    "appliances": [{"monthly_kwh": 243.0}]},
                    "bill": {"total_amount": 491.58, "season_label_en": "Non-summer (Oct 1 - May 31)"},
                    "summary": {"effective_rate_per_kwh": 2.02},
                    "recommendations": {"recommendations": [
                        {"title_en": "AC runs long", "suggestion_en": "Use a timer.",
                         "estimated_monthly_saving_twd": 51.0},
                    ]},
                }
            if path == "/calculate/load":
                return {"verdict": "near_limit", "total_power_watts": 900.0,
                        "limit_watts": 1650.0}
            if path == "/product-recommendations":
                return {
                    "recommendations": [
                        {
                            "appliance": "Air conditioner",
                            "product_id": 1,
                            "product_name": "Inverter AC",
                            "brand": "Demo",
                            "price": 23900,
                            "estimated_savings_kwh": 54.0,
                            "estimated_savings_cost": 117.0,
                        }
                    ],
                    "total": 1,
                    "rate_per_kwh": 2.1698,
                    "currency": "TWD",
                    "saved": 0,
                }
            raise AssertionError(f"unexpected request {method} {path}")

        monkeypatch.setattr(desktop, "request", fake_request)
        monkeypatch.setattr(desktop, "PREFS_FILE", str(tmp_path / "prefs.json"))
        built = desktop.Store(prefs_path=str(tmp_path / "prefs.json"))
        return built, calls

    def test_loads_the_household_and_the_numbers_from_the_backend(self, store):
        built, _calls = store
        st = built.st
        assert st["error"] is None
        assert [a["name"] for a in st["appliances"]] == ["Air conditioner"]
        assert st["bill"] == 491.58
        assert st["total_kwh"] == 243.0
        assert st["appliances"][0]["kwh"] == 243.0
        assert st["appliances"][0]["icon"] == "air_conditioner"
        assert st["plan_name"] == "Taipower tiered"

    def test_uses_the_backend_verdict_for_the_circuit(self, store):
        built, _calls = store
        _pct, key, used, limit = desktop.safety_of(built.st)
        assert key == "near"
        assert (used, limit) == (900.0, 1650.0)

    def test_icon_and_switch_preferences_are_remembered_locally(self, store):
        built, _calls = store
        built.remember("Air conditioner", icon="tv", on=False)
        assert built.prefs["air conditioner"] == {"icon": "tv", "on": False}
        assert Path(built.path).exists()

    def test_an_unreachable_backend_becomes_a_message_not_a_crash(self, monkeypatch, tmp_path):
        def down(*_a, **_k):
            raise desktop.ApiError("cannot reach http://127.0.0.1:8000")

        monkeypatch.setattr(desktop, "request", down)
        built = desktop.Store(prefs_path=str(tmp_path / "p.json"))
        assert "cannot reach" in built.st["error"]
        assert built.st["appliances"] == []
        assert "Backend unreachable" in desktop.make_suggestions(built.st)[0]
