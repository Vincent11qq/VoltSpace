"""The Flet layout must fit the screen it is drawn on.

Reported from a phone (space-flet.onrender.com): the right-hand "App guide" cell was cut
off and the bottom navigation sat outside the visible area. Two causes:

  * every screen was wrapped in a fixed 414x896 frame, but a phone viewport is about
    390x700 CSS pixels, so the frame overflowed;
  * the four function cells were a fixed 88px each (352px total) inside 330px of body
    width, so the last one was clipped even on a desktop browser.

These tests build the real screens against a fake page of a given size and check that what
comes out actually fits.
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

DESIGN_W, DESIGN_H = app_module.W, app_module.H


class FakeWindow:
    width = None
    height = None


class FakePage:
    """A page that reports a viewport, which is what a browser does."""

    def __init__(self, width=None, height=None):
        self.width = width
        self.height = height
        self.title = None
        self.bgcolor = None
        self.padding = None
        self.fonts = None
        self.theme_mode = None
        self.horizontal_alignment = None
        self.vertical_alignment = None
        self.window = FakeWindow()
        self.on_resized = None
        self.controls = []
        self.updates = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.updates += 1


class StubStore:
    """The screens only read ``st``; no network in these tests."""

    def __init__(self, *args, **kwargs):
        self.path = None
        self.st = app_module.default_state()
        self.st["appliances"] = [
            {"id": 1, "name": "Air conditioner", "icon": "air_conditioner",
             "watts": 900, "hours": 6, "days": 30, "on": True, "kwh": 162.0},
        ]
        self.st["bill"] = 527.25
        self.st["total_kwh"] = 162.0
        self.st["load"] = {"verdict": "safe", "total_power_watts": 900, "limit_watts": 1650}
        self.st["recs"] = [{"title_en": "Try 26 C", "suggestion_en": "Saves energy."}]
        self.st["amps"] = 15.0
        self.st["volts"] = 110.0
        self.st["plan_id"] = "tw_residential_tiered"
        self.st["plan_name"] = "Residential tiered"

    def reload(self):
        return None

    def remember(self, *args, **kwargs):
        return None

    def save(self):
        return None


@pytest.fixture()
def build(monkeypatch):
    monkeypatch.setattr(app_module, "Store", StubStore)

    def _build(width, height, screen="home", **params):
        page = FakePage(width, height)
        app = app_module.App(page)
        app.go(screen, **params)
        return app, page

    return _build


def _function_cells(node):
    """The four grey boxes with an icon above a label."""

    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ft.Container) and isinstance(current.content, ft.Column):
            kids = getattr(current.content, "controls", [])
            if len(kids) == 2 and isinstance(kids[0], ft.Container) and isinstance(kids[1], ft.Text):
                found.append(current)
        for attribute in ("controls", "content"):
            child = getattr(current, attribute, None)
            if isinstance(child, list):
                stack.extend(child)
            elif child is not None and not isinstance(child, (str, int, float)):
                stack.append(child)
    return found


class TestFrameFitsTheViewport:
    def test_phone_viewport_is_not_exceeded(self, build):
        """390x700 is what an iPhone reports after browser chrome."""

        app, _ = build(390, 700)
        frame = app.holder.content
        assert frame.width <= 390, f"frame is {frame.width}px wide on a 390px screen"
        assert frame.height <= 700

    def test_a_short_phone_still_shows_the_navigation(self, build):
        app, _ = build(390, 640)
        column = app.holder.content.content
        # header + body(expand) + bottom nav: the nav is last and the body takes the rest
        assert isinstance(column, ft.Column)
        assert len(column.controls) == 3
        assert column.controls[-1] is not None, "bottom navigation missing"

    def test_a_wide_window_keeps_the_design_width(self, build):
        """A desktop browser should not stretch the phone layout."""

        app, _ = build(1440, 900)
        frame = app.holder.content
        assert frame.width == DESIGN_W

    def test_it_never_exceeds_the_design_height(self, build):
        app, _ = build(1440, 2000)
        assert app.holder.content.height == DESIGN_H

    def test_a_tiny_window_has_a_floor(self, build):
        """No negative or zero sizes when the platform reports something odd."""

        app, _ = build(200, 300)
        frame = app.holder.content
        assert frame.width >= 200
        assert frame.height >= 300


class TestFunctionGridFits:
    def test_cells_fit_the_body_width(self, build):
        app, _ = build(390, 700)
        cells = _function_cells(app.holder.content)
        assert len(cells) == 4, f"expected 4 function cells, found {len(cells)}"
        body_width = 390 - 84  # scroll_body left/right padding
        total = sum(cell.width for cell in cells) + 3 * 8
        assert total <= body_width, f"the grid needs {total}px but only {body_width}px fit"

    def test_the_row_wraps_when_it_must(self, build):
        app, _ = build(320, 640)
        rows = []

        def walk(node):
            if isinstance(node, ft.Row):
                rows.append(node)
            for attribute in ("controls", "content"):
                child = getattr(node, attribute, None)
                if isinstance(child, list):
                    for item in child:
                        walk(item)
                elif child is not None and not isinstance(child, (str, int, float)):
                    walk(child)

        walk(app.holder.content)
        grid = [row for row in rows if row.wrap]
        assert grid, "the function grid must be able to wrap on a narrow screen"


class TestResizeIsHandled:
    def test_resizing_rebuilds_the_current_screen(self, build):
        app, page = build(390, 700)
        page.width, page.height = 700, 390          # phone rotated to landscape
        # main() does exactly this inside its on_resized handler.
        app.size = app_module.viewport(page)
        app.rebuild()
        assert app.holder.content.width <= 700
        assert app.size == (414, 390), "landscape keeps the design width but the real height"

    def test_the_source_wires_on_resized(self):
        source = (FRONTEND / "desktop" / "app.py").read_text(encoding="utf-8")
        assert "page.on_resized = on_resized" in source
        assert "def viewport(page" in source
        assert "width=W, height=H" not in source, "a fixed frame is back"
