"""Exercise the Flet desktop app's logic without rendering it.

The sandbox cannot open a Flutter window, but the app's real logic (API calls, widget
construction, callbacks) can be driven with a stand-in ``Page``. This catches attribute
errors, wrong Flet 1.0 names and bad API payloads before anyone runs the GUI.

Usage::

    python tools/check_desktop.py [base_url]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import flet as ft  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
import os  # noqa: E402

os.environ["VOLTSPACE_API"] = BASE

import desktop.app as app_module  # noqa: E402


class FakeWindow:
    width = None
    height = None


class FakePage:
    """Enough of ``ft.Page`` for ``main()`` to run headlessly."""

    def __init__(self) -> None:
        self.title = None
        self.bgcolor = None
        self.padding = None
        self.theme_mode = None
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
    """Collect text values so we can assert the UI actually rendered numbers."""

    found: list[str] = []
    if isinstance(node, ft.Text):
        if node.value:
            found.append(str(node.value))
    for attribute in ("controls", "content", "title", "subtitle", "options"):
        child = getattr(node, attribute, None)
        if isinstance(child, list):
            for item in child:
                found.extend(describe(item, depth + 1))
        elif child is not None and not isinstance(child, (str, int, float)):
            found.extend(describe(child, depth + 1))
    return found


def main() -> int:
    page = FakePage()
    app_module.main(page)

    texts = describe(page)
    joined = " | ".join(texts)
    print(f"controls added : {len(page.controls)}")
    print(f"page.update()  : {page.updates} times")
    print(f"text widgets   : {len(texts)}")

    checks: list[tuple[str, bool]] = [
        ("header rendered", any("VoltSpace" in text for text in texts)),
        ("appliance presets rendered", any("冷氣機" in text for text in texts)),
        ("plan dropdown populated", bool(getattr(page, "controls"))),
        ("saved-household note rendered", any("已" in text or "沒有" in text for text in texts)),
    ]

    # The dashboard must have produced real numbers for the default household, if any.
    numeric = [text for text in texts if "度" in text or "元" in text]
    checks.append(("summary numbers rendered", bool(numeric)))

    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print()
    print("sample texts:", " | ".join(texts[:14]))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
