"""A platform 429 must not look like a dead backend, and must not wipe the UI.

Reported from the Flet page:

    Backend unreachable: HTTP 429 from /appliances/presets
    ... Safety Status: NO LIMIT SET, 0 W (no circuit limit set)

Nothing in this project returns 429 (only validation_error, invalid_value,
appliance_not_found, storage_error), so the limit came from the platform edge. Our own
defects were: treating it as fatal, and fetching presets/tariffs/household in one try block.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent
FRONTEND = SERVER.parent / "frontend"
sys.path.insert(0, str(FRONTEND))

import desktop.app as app_module  # noqa: E402


@pytest.fixture()
def fake_http(monkeypatch, tmp_path):
    """Serve canned responses per path; unknown paths raise like the code would."""

    calls: list[str] = []
    responses: dict[str, object] = {}

    def handler(path, *, method="GET", payload=None, timeout=25):
        calls.append(path)
        answer = responses.get(path)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise AssertionError(f"unexpected request {method} {path}")
        if callable(answer):
            return answer()
        return answer

    # Defaults for the calls Store._recalculate makes once the household is loaded.
    responses.update({
        "/household/dashboard": {
            "bill": {"total_amount": 100.0, "season_label_en": "Summer"},
            "consumption": {"total_monthly_kwh": 40.0, "appliances": [{"monthly_kwh": 40.0}]},
            "summary": {"effective_rate_per_kwh": 2.5},
            "recommendations": {"recommendations": []},
        },
        "/calculate/load": {"verdict": "no_limit", "total_power_watts": 0.0, "limit_watts": None},
        "/product-recommendations": {"recommendations": []},
    })

    monkeypatch.setattr(app_module, "request", handler)
    monkeypatch.setattr(app_module, "PREFS_FILE", str(tmp_path / "prefs.json"))
    return calls, responses


PRESETS = {
    "presets": [
        {"key": "air_conditioner", "name_en": "Air conditioner", "name_zh": "冷氣機",
         "power_watts": 900, "hours_per_day": 6},
    ],
    "circuits": [{"label": "15 A / 110 V", "amps": 15, "volts": 110}],
    "default_circuit_amps": 15,
    "default_voltage": 110,
}
TARIFFS = {
    "plans": [{"id": "tw_residential_tiered", "name_en": "Residential tiered"}],
    "default_plan_id": "tw_residential_tiered",
}
EMPTY = {"appliances": []}


class TestRateLimitIsRetried:
    def test_the_client_retries_429_then_succeeds(self, monkeypatch):
        """A 429 that clears on the next attempt must be invisible to the user."""

        import urllib.error

        attempts = []

        def fake_urlopen(req, timeout=None):
            attempts.append(req.full_url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"ok": true}'

            return Response()

        monkeypatch.setattr(app_module.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(app_module.time, "sleep", lambda _s: None)

        assert app_module.request("/appliances/presets") == {"ok": True}
        assert len(attempts) == 2, "the first 429 should have been retried"

    def test_a_real_error_is_still_reported(self, monkeypatch):
        import urllib.error

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        monkeypatch.setattr(app_module.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(app_module.ApiError):
            app_module.request("/nope")


class TestOneFailureDoesNotWipeEverything:
    def test_presets_failing_keeps_the_circuit_and_the_household(self, fake_http):
        calls, responses = fake_http
        responses["/appliances/presets"] = app_module.ApiError("HTTP 429 from /appliances/presets")
        responses["/tariffs"] = TARIFFS
        responses["/household/appliances"] = {
            "appliances": [{"id": 1, "name": "Fan", "power_watts": 50,
                            "hours_per_day": 8, "days_per_month": 30}]
        }

        store = app_module.Store()

        # The plan and the appliances still load...
        assert store.st["plan_id"] == "tw_residential_tiered"
        assert len(store.st["appliances"]) == 1
        # ...and the circuit is still configured, so no "NO LIMIT SET / 0 W".
        assert store.st["amps"] == 15
        assert store.st["volts"] == 110
        # The error is still shown: the catalogue is genuinely missing.
        assert "429" in (store.st["error"] or "")

    def test_the_catalogue_is_cached_for_the_next_start(self, fake_http):
        calls, responses = fake_http
        responses["/appliances/presets"] = PRESETS
        responses["/tariffs"] = TARIFFS
        responses["/household/appliances"] = EMPTY

        app_module.Store()                    # first run: everything answers
        assert app_module.PRESETS, "the first load should fill PRESETS"

        app_module.PRESETS.clear()
        responses["/appliances/presets"] = app_module.ApiError("HTTP 429 from /appliances/presets")
        store = app_module.Store()            # second run: the catalogue is rate limited

        assert app_module.PRESETS, "the cached catalogue should be used instead of nothing"
        assert store.st["amps"] == 15
