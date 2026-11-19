"""Quick fill must not disappear from the Add screen.

It broke once: the product-advice fetch was pasted into ``Store.reload()`` and returned
early when /product-recommendations failed, so PRESETS (and every chip label) stayed empty.
The Add screen then showed the "Quick fill" heading with nothing under it.

These tests build the real Add screen against a fake backend and check the chips are there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent
FRONTEND = SERVER.parent / "frontend"
sys.path.insert(0, str(FRONTEND))

import flet as ft  # noqa: E402

import desktop.app as app_module  # noqa: E402

PRESET_ROWS = [
    {"key": "air_conditioner", "name_en": "Air conditioner", "name_zh": "冷氣機",
     "power_watts": 900, "hours_per_day": 6},
    {"key": "refrigerator", "name_en": "Refrigerator", "name_zh": "冰箱",
     "power_watts": 130, "hours_per_day": 24},
    {"key": "hair_dryer", "name_en": "Hair dryer", "name_zh": "吹風機",
     "power_watts": 1200, "hours_per_day": 0.3},
]


class FakePage:
    width = 390
    height = 700

    def __init__(self):
        self.title = None
        self.bgcolor = None
        self.padding = None
        self.fonts = None
        self.theme_mode = None
        self.horizontal_alignment = None
        self.vertical_alignment = None
        self.window = type("W", (), {"width": None, "height": None})()
        self.on_resized = None
        self.controls = []
        self.updates = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.updates += 1


def texts(node) -> list[str]:
    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ft.Text) and current.value:
            found.append(str(current.value))
        for attribute in ("controls", "content", "label"):
            child = getattr(current, attribute, None)
            if isinstance(child, list):
                stack.extend(child)
            elif child is not None and not isinstance(child, (str, int, float)):
                stack.append(child)
    return found


@pytest.fixture()
def add_screen(monkeypatch):
    """A Store that has loaded PRESETS the way the real one does."""

    def fake_request(path, *, method="GET", payload=None, timeout=25):
        if path == "/appliances/presets":
            return {
                "presets": PRESET_ROWS,
                "circuits": [{"label": "15 A / 110 V", "amps": 15, "volts": 110}],
                "default_circuit_amps": 15,
                "default_voltage": 110,
            }
        if path == "/tariffs":
            return {"plans": [{"id": "tw_residential_tiered",
                               "name_en": "Residential tiered"}],
                    "default_plan_id": "tw_residential_tiered"}
        if path == "/household/appliances":
            return {"appliances": []}
        if path == "/product-recommendations":
            # The failure that used to wipe Quick fill.
            raise app_module.ApiError("catalogue unavailable")
        raise AssertionError(f"unexpected request {method} {path}")

    monkeypatch.setattr(app_module, "request", fake_request)
    monkeypatch.setattr(app_module, "PREFS_FILE", str(SERVER / ".test-data" / "prefs.json"))

    def build():
        store = app_module.Store()
        page = FakePage()
        app = app_module.App(page, store=store)
        app.go("form", mode="add")
        return app, store

    return build


class TestPresetsAreLoaded:
    def test_presets_come_from_the_backend(self, add_screen):
        _, store = add_screen()
        assert app_module.PRESETS, "PRESETS stayed empty - reload() returned too early"
        assert ("Air conditioner", "air_conditioner", 900, 6) in app_module.PRESETS

    def test_name_index_is_filled(self, add_screen):
        add_screen()
        assert app_module.NAME_INDEX["冷氣機"] == "air_conditioner"
        assert app_module.guess_icon("refrigerator") == "refrigerator"


class TestQuickFillIsVisible:
    def test_the_add_screen_shows_the_heading_and_chips(self, add_screen):
        app, _ = add_screen()
        body = texts(app.holder.content)
        assert "Quick fill" in body, "the Quick fill section disappeared"

        for preset in PRESET_ROWS:
            assert preset["name_en"] in body, f"chip for {preset['name_en']} is missing"

    def test_the_chips_are_clickable(self, add_screen):
        app, _ = add_screen()
        clicked = []

        def walk(node):
            if isinstance(node, ft.Container) and node.on_click is not None:
                clicked.append(node)
            for attribute in ("controls", "content"):
                child = getattr(node, attribute, None)
                if isinstance(child, list):
                    for item in child:
                        walk(item)
                elif child is not None and not isinstance(child, (str, int, float)):
                    walk(child)

        walk(app.holder.content)
        assert len(clicked) >= len(PRESET_ROWS), "the preset chips lost their on_click"

    def test_editing_does_not_show_quick_fill(self, add_screen):
        """Adding shows the presets; editing an existing appliance stays clean."""

        app, store = add_screen()
        store.st["appliances"] = [
            {"id": 1, "name": "Fan", "icon": "electric_fan", "watts": 50,
             "hours": 8, "days": 30, "on": True, "kwh": 12.0}
        ]
        app.go("form", mode="edit", id=1)
        assert "Quick fill" not in texts(app.holder.content)


class TestProductAdviceStaysOptional:
    def test_a_failing_catalogue_is_not_an_error_banner(self, add_screen):
        _, store = add_screen()
        assert store.st["products"] == []
        assert store.st["error"] is None, "a missing catalogue must not look like an outage"
