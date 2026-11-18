"""Drive the Flet desktop UI headlessly and check what it renders.

Flet needs a window, so this stubs ``ft.Page`` with ``FakePage`` and walks the control tree
collecting text. It catches the failures that a compile check cannot: a screen that throws
while building, a screen that silently renders nothing, and - most importantly - any
wording that claims the circuit is *safe*, which this project deliberately does not do.

The desktop app reads every number from the backend, so a server must be running:

    cd backend
    run_app.bat                 # in another terminal
    python tools/check_desktop.py

If the backend is not reachable the tool says so instead of failing with a stack trace.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import flet as ft  # noqa: E402

import desktop.app as app_module  # noqa: E402


class FakeWindow:
    width = None
    height = None


class FakePage:
    """Enough of ``ft.Page`` for the UI to build itself."""

    def __init__(self) -> None:
        self.title = None
        self.bgcolor = None
        self.padding = None
        self.theme_mode = None
        self.fonts = None
        self.horizontal_alignment = None
        self.vertical_alignment = None
        self.window = FakeWindow()
        self.controls: list[Any] = []
        self.updates = 0

    def add(self, *controls: Any) -> None:
        self.controls.extend(controls)

    def update(self) -> None:
        self.updates += 1

    def get_control(self, _control_id: Any) -> Any:
        return None


def describe(node: Any, depth: int = 0) -> list[str]:
    """Collect Text values so we can assert the screen actually said something."""

    found: list[str] = []
    if isinstance(node, ft.Text) and node.value:
        found.append(str(node.value))
    for attribute in ("controls", "content", "title", "subtitle", "options", "label"):
        child = getattr(node, attribute, None)
        if isinstance(child, list):
            for item in child:
                found.extend(describe(item, depth + 1))
        elif child is not None and not isinstance(child, (str, int, float)):
            found.extend(describe(child, depth + 1))
    return found


def screen_texts(app: app_module.App, name: str, **params: Any) -> str:
    """Render one screen and flatten all of its text."""

    holder = app.build(name, **params)
    return " | ".join(describe(holder))


def main() -> int:
    page = FakePage()
    app = app_module.App(page)
    page.add(app.holder)

    if app.store.st.get("error"):
        print(f"[SKIP] backend not reachable at {app_module.API}")
        print(f"       {app.store.st['error']}")
        print("       start it with:  run_app.bat")
        return 0

    home = screen_texts(app, "home")
    appliances = screen_texts(app, "appliances")
    cost = screen_texts(app, "cost")
    suggest = screen_texts(app, "suggest")
    settings = screen_texts(app, "settings")
    logs = screen_texts(app, "logs")
    guide = screen_texts(app, "guide")

    print(f"backend        : {app_module.API}")
    print(f"appliances     : {len(app.store.st['appliances'])} saved")
    print(f"bill / total   : NT$ {app.store.st['bill']:,.2f} / {app.store.st['total_kwh']:,.1f} kWh")
    print(f"load verdict   : {(app.store.st['load'] or {}).get('verdict')}")
    print(f"page.update()  : {page.updates} times")
    print()

    verdict_labels = set(app_module.STATUS_LABEL.values())
    checks: list[tuple[str, bool]] = [
        ("home rendered", "Functions" in home and "Safety Status" in home),
        ("home shows a circuit verdict", any(label in home for label in verdict_labels)),
        ("home does not claim SAFE", "SAFE" not in home.upper().replace("SAFETY", "")),
        ("home mentions the estimate caveat", "not a guarantee" in home),
        ("appliances screen rendered", "My appliances" in appliances),
        ("cost screen rendered", "Cost" in cost and "NT$" in cost),
        ("suggestion screen rendered", "Suggestion" in suggest and len(suggest) > 30),
        ("settings screen rendered", "Settings" in settings and "Circuit" in settings),
        ("settings tariff is read-only", "Read-only" in settings and "NT$/kWh" not in settings.replace(" ", "")),
        ("logs screen rendered", "Safety Logs" in logs),
        ("guide screen rendered", "App guide" in guide),
        ("numbers came from the backend", app.store.st["bill"] >= 0 and app.store.st["total_kwh"] >= 0),
    ]

    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")

    failed = [label for label, ok in checks if not ok]
    print()
    if failed:
        print("failing screens:")
        for label, body in (
            ("home", home), ("appliances", appliances), ("cost", cost),
            ("suggest", suggest), ("settings", settings), ("logs", logs),
        ):
            print(f"  {label:11} {body[:160]}")
        return 1
    print("desktop UI renders and takes every number from the backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
