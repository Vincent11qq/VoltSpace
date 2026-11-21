"""The startup probe: wait for /health before firing the loading burst.

The 429 that blanked the UI happened because six requests hit a cold API at once. One
bounded probe at startup removes that; a genuinely dead backend must still reach the screens
instead of hanging.
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
def no_sleep(monkeypatch):
    monkeypatch.setattr(app_module.time, "sleep", lambda _seconds: None)


class TestWarmUp:
    def test_it_returns_immediately_when_the_backend_is_awake(self, monkeypatch, no_sleep):
        calls = []

        def fake(path, **kwargs):
            calls.append(path)
            return {"status": "ok"}

        monkeypatch.setattr(app_module, "request", fake)

        assert app_module.warm_up(timeout=5) is True
        assert calls == ["/health"], "one probe, then stop"

    def test_it_retries_until_the_backend_answers(self, monkeypatch, no_sleep):
        calls = []

        def fake(path, **kwargs):
            calls.append(path)
            if len(calls) < 3:
                raise app_module.ApiError("HTTP 429 from /health")
            return {"status": "ok"}

        monkeypatch.setattr(app_module, "request", fake)

        assert app_module.warm_up(timeout=10) is True
        assert len(calls) == 3

    def test_a_dead_backend_does_not_block_startup(self, monkeypatch, no_sleep):
        def fake(path, **kwargs):
            raise app_module.ApiError("cannot reach the backend")

        monkeypatch.setattr(app_module, "request", fake)

        assert app_module.warm_up(timeout=0) is False

    def test_an_unexpected_shape_is_not_treated_as_ready(self, monkeypatch, no_sleep):
        def fake(path, **kwargs):
            return {"status": "starting"}

        monkeypatch.setattr(app_module, "request", fake)

        assert app_module.warm_up(timeout=0) is False

    def test_the_wait_is_bounded_by_the_environment(self, monkeypatch, no_sleep):
        seen = {}

        def fake(path, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            raise app_module.ApiError("down")

        monkeypatch.setattr(app_module, "request", fake)
        monkeypatch.setenv("VOLTSPACE_WAIT", "0")

        assert app_module.warm_up() is False
        assert seen["timeout"] == 10, "each probe still uses a short request timeout"

    def test_main_calls_it_before_building_the_app(self):
        source = (FRONTEND / "desktop" / "app.py").read_text(encoding="utf-8")
        assert "warm_up()" in source
        # the probe must come before the first screen is built
        assert source.index("warm_up()") < source.index("app = App(page)")
