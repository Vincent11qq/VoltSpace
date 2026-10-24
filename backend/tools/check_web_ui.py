"""Static check that the web UI's JavaScript and HTML agree.

The sandbox cannot open a browser, so this catches the failure mode that would otherwise
only show up as a broken page: an element id the script expects but the HTML never defines
(or the reverse: dead ids), plus unclosed tags.

Usage::

    python tools/check_web_ui.py
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.tag_counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        for name, value in attrs:
            if name == "id" and value:
                if value in self.ids:
                    self.errors.append(f"duplicate id '{value}'")
                self.ids.append(value)
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if not self.stack:
            self.errors.append(f"unexpected </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
        else:
            # Allow a slightly sloppy close, but record it.
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    unclosed = self.stack.pop()
                    self.errors.append(f"unclosed <{unclosed}> before </{tag}>")
                self.stack.pop()
            else:
                self.errors.append(f"unexpected </{tag}>")


def main() -> int:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    parser = IdCollector()
    parser.feed(index)
    html_ids = set(parser.ids)

    # Every $("x") / getElementById("x") in the script must exist in the HTML.
    script_ids = set(re.findall(r'\$\("([^"]+)"\)', script))
    script_ids |= set(re.findall(r'getElementById\("([^"]+)"\)', script))

    missing = sorted(script_ids - html_ids)
    # Ids present in HTML but never used are only worth noting.
    unused = sorted(html_ids - script_ids)

    print(f"html ids   : {len(html_ids)}")
    print(f"script ids : {len(script_ids)}")

    ok = True
    if parser.errors:
        ok = False
        print("\nHTML structure problems:")
        for problem in parser.errors:
            print("  -", problem)
    if missing:
        ok = False
        print("\nJS references ids that the HTML does not define:")
        for name in missing:
            print("  -", name)
    if unused:
        print("\nHTML ids not referenced by the script (informational):")
        for name in unused:
            print("  -", name)

    # The script must fetch from the endpoints the backend actually serves.
    for path in (
        "/health",
        "/appliances/presets",
        "/tariffs",
        "/household/appliances",
        "/household/dashboard",
    ):
        if path not in script:
            ok = False
            print(f"\nscript never calls {path}")
    # CSS must be linked.
    if "/app/app.css" not in index:
        ok = False
        print("\nindex.html does not link /app/app.css")
    if "/app/app.js" not in index:
        ok = False
        print("index.html does not load /app/app.js")

    print("\nweb UI OK" if ok else "\nweb UI has problems")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
