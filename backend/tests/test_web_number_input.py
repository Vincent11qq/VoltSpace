"""Test the web UI's number parsing so "150W" is accepted (the reported bug).

The parser lives in app.js, so this extracts the function and runs it in Node with a
minimal DOM stub. If Node is unavailable the test is skipped.

Usage::

    node tools/check_number_parsing.js      (or run through pytest)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_JS = BACKEND_ROOT / "web" / "app.js"

# Cases the parser must handle. The first group is what users actually type.
CASES = [
    # raw input, expected value, why
    ("150", 150, "plain number"),
    ("150W", 150, "unit attached - the reported failure"),
    ("150 W", 150, "unit after a space"),
    ("150w", 150, "lowercase unit"),
    ("150 瓦", 150, "Chinese unit"),
    ("1,200", 1200, "thousands separator"),
    ("1，200", 1200, "full-width thousands separator"),
    ("  150  ", 150, "surrounding spaces"),
    ("0.5", 0.5, "decimal"),
    ("150.5W", 150.5, "decimal with unit"),
    ("110V", 110, "voltage with unit"),
    ("6h", 6, "hours with unit"),
    ("6 小時", 6, "Chinese hours"),
    ("", None, "empty"),
    ("   ", None, "whitespace only"),
    ("abc", None, "not a number"),
    ("W", None, "unit only"),
    (".", None, "lone decimal point"),
]


def _node() -> str | None:
    for name in ("node", "node.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_parser(expressions: list[str]) -> list:
    """Evaluate parseNumber for each expression in Node."""

    node = _node()
    if node is None:
        raise RuntimeError("node not available")

    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function parseNumber(")
    # The function ends at the first line that is a lone closing brace followed by a blank.
    end = source.index("\n}\n", start) + 2
    function_source = source[start:end]

    script = textwrap.dedent(
        """
        const $ = (id) => ({ value: "" });
        const toast = () => {};
        __FUNCTION__
        const inputs = JSON.parse(process.argv[1]);
        const out = inputs.map((raw) => {
          const value = parseNumber(raw);
          return value === null ? null : value;
        });
        process.stdout.write(JSON.stringify(out));
        """
    ).replace("__FUNCTION__", function_source)

    result = subprocess.run(
        [node, "-e", script, json.dumps(expressions)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "node failed")
    return json.loads(result.stdout)


@pytest.mark.skipif(_node() is None, reason="node is not installed")
def test_parse_number_accepts_units():
    raw = [case[0] for case in CASES]
    expected = [case[1] for case in CASES]
    actual = _run_parser(raw)
    problems = []
    for (text, want, why), got in zip(CASES, actual):
        if got != want:
            problems.append(f"{text!r} ({why}) -> {got!r}, expected {want!r}")
    assert problems == [], "\n".join(problems)


@pytest.mark.skipif(_node() is None, reason="node is not installed")
def test_the_reported_case_150w_is_valid():
    """Regression: typing 150W used to fail with the browser's 請輸入有效的值."""

    assert _run_parser(["150W"]) == [150]


def test_the_form_no_longer_uses_native_number_validation():
    """type=number + a unit in the placeholder is what produced the confusing tooltip."""

    html = (BACKEND_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    form_start = html.index('id="customForm"')
    form_end = html.index("</form>", form_start)
    form = html[form_start:form_end]
    assert 'type="number"' not in form, "the custom form should not use type=number"
    assert "novalidate" in form, "the form should opt out of native validation"
    for field in ("cWatts", "cVolts", "cHours", "cDays", "cQty"):
        assert f'id="{field}"' in form, f"{field} is missing"


def test_parse_number_is_used_for_every_custom_field():
    source = APP_JS.read_text(encoding="utf-8")
    assert "function parseNumber(" in source
    for field in ("cWatts", "cVolts", "cHours", "cDays", "cQty"):
        assert f'readField("{field}"' in source, f"{field} is not parsed tolerantly"
