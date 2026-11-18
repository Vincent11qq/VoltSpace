"""Cross-check the numbers written in the docs against the generated examples.

Documentation drifts. This script reads ``docs/examples/*.json`` (which are produced by
running the real code) and asserts that the figures quoted in the README and the
integration notes actually appear there.

It also checks the two counts that go stale most easily but are not in any example:
the number of tests and the Python share. Those used to be updated by hand and were
wrong in one doc while right in another.

Usage::

    python tools/check_docs_numbers.py

Use ``--fast`` to skip the two counts (they run pytest and walk the tree).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
EXAMPLES = BACKEND_ROOT / "docs" / "examples"
# Every doc that quotes figures. Keep this list complete: a number can be right in one
# document and stale in another, which is exactly how 535 survived in the status doc.
DOCS = [
    REPO_ROOT / "README.md",
    BACKEND_ROOT / "docs" / "integration.md",
    REPO_ROOT / "docs" / "backend-status.md",
]

failures: list[str] = []


def load(name: str) -> dict:
    with (EXAMPLES / f"{name}.json").open(encoding="utf-8") as handle:
        return json.load(handle)["response"]


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check(label: str, needle: str, haystack: str) -> None:
    present = needle in haystack
    print(f"[{'PASS' if present else 'FAIL'}] {label}: {needle}")
    if not present:
        failures.append(f"{label}: {needle} not found")


def collected_tests() -> int:
    """How many tests pytest actually collects."""

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    total = 0
    for line in result.stdout.splitlines():
        # "tests/test_api.py: 121"
        if line.startswith("tests") and ":" in line:
            head, _, tail = line.rpartition(":")
            if head.startswith("tests") and tail.strip().isdigit():
                total += int(tail.strip())
    return total


def python_share() -> tuple[str, str]:
    """The two percentages, as ``python_share.py`` prints them."""

    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "tools" / "python_share.py")],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    including = production = ""
    for line in result.stdout.splitlines():
        if "including tests/tooling" in line:
            including = line.split(":", 1)[1].strip().split()[0]
        elif "production-only" in line:
            production = line.split(":", 1)[1].strip().split()[0]
    return including, production


def check_counts(failures: list[str]) -> None:
    """The test count and the Python share must agree with every doc.

    Both are line-scoped on purpose: scanning a whole file for any 3-4 digit number or
    any percentage matches data values (tariff tiers, simulation percentages) and
    historical notes, which produced false alarms when this check was first written.
    """

    import re

    print("\n== counts that drift silently ==")

    total = collected_tests()
    print(f"[INFO] pytest collects {total} tests")
    # A doc may talk about how many tests passed *historically*; that is not a stale claim.
    history = ("版本上", "舊版", "先前", "歷史", "before this round")
    count_patterns = [
        r"(\d{3,4})\s*passed",
        r"(\d{3,4})\s*個測試",
        r"測試（(\d{3,4})\s*個）",
        r"\*\*(\d{3,4}) 個\*\*",
    ]
    for path in DOCS:
        if not path.exists():
            continue
        problems = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(marker in line for marker in history):
                continue
            for pattern in count_patterns:
                for found in re.findall(pattern, line):
                    if int(found) != total:
                        problems.append(f"line {number}: {found} (actual {total})")
        ok = not problems
        print(f"[{'PASS' if ok else 'FAIL'}] {path.name}: test count = {total}")
        for problem in problems:
            print(f"       {problem}")
            failures.append(f"{path.name}: stale test count - {problem}")

    including, production = python_share()
    print(f"[INFO] python share: {including} including tests, {production} production-only")

    def percent(value: str) -> str:
        """Rounded to a whole percent: the share moves whenever any file is edited, so
        documents quote it rounded and this check compares rounded values."""

        try:
            return f"{round(float(value.rstrip('%')))}%"
        except ValueError:
            return ""

    for path, marker_including, marker_production in (
        (REPO_ROOT / "README.md", "含測試與工具", "只算產品程式碼"),
        (REPO_ROOT / "docs" / "backend-status.md", "含測試與工具", "只算產品程式碼"),
    ):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for marker, value in (
            (marker_including, including),
            (marker_production, production),
        ):
            expected = percent(value)
            if not expected:
                continue
            # Only lines that actually make the claim.
            hits = [line for line in text.splitlines() if marker in line]
            ok = bool(hits) and any(expected in line for line in hits)
            print(f"[{'PASS' if ok else 'FAIL'}] {path.name}: {marker} = {expected}")
            if not ok:
                failures.append(
                    f"{path.name}: {marker} should read {expected} (actual {value})"
                )


def fix_share(failures: list[str]) -> None:
    """Rewrite the quoted Python share when it rounds differently.

    The share moves by a fraction of a percent whenever any file is edited (adding a test
    moves it too), so the documents quote whole percentages and this keeps them in step.
    """

    import re

    including, production = python_share()
    if not including or not production:
        return

    def percent(value: str) -> str:
        try:
            return f"{round(float(value.rstrip('%')))}%"
        except ValueError:
            return ""

    targets = (
        ("含測試與工具", percent(including)),
        ("只算產品程式碼", percent(production)),
    )
    print("\n== fixing the quoted Python share ==")
    for name in ("README.md", "docs/backend-status.md"):
        path = REPO_ROOT / name
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = 0
        for index, line in enumerate(lines):
            for marker, expected in targets:
                if marker in line and expected and expected not in line:
                    updated = re.sub(r"\d{2}%", expected, line, count=1)
                    if updated != line:
                        lines[index] = updated
                        changed += 1
        if changed:
            path.write_text("".join(lines), encoding="utf-8")
            print(f"[FIXED] {path.name}: {changed} line(s)")
        else:
            print(f"[OK]    {path.name}")


def structural_counts() -> dict[str, int]:
    """Counts that appear in the docs and are cheap to derive from the tree."""

    sys.path.insert(0, str(BACKEND_ROOT))
    from app.main import app  # imported here so --fast does not pay for it

    # Count route *entries* (one per method), not OpenAPI paths: GET+POST+PUT on
    # /household/appliances is three routes but one path. The docs quote routes.
    entries = [
        route
        for route in app.routes
        if getattr(route, "methods", None) and not route.path.startswith(("/openapi", "/docs", "/redoc"))
    ]
    json_routes = [route for route in entries if route.path != "/"]
    return {
        "json_endpoints": len(json_routes),
        "total_routes": len(entries),
        "test_files": len(list((BACKEND_ROOT / "tests").glob("*.py"))),  # includes conftest
        "tools": len(list((BACKEND_ROOT / "tools").glob("*.py"))),
        "app_modules": len(list((BACKEND_ROOT / "app").rglob("*.py"))),
    }


def check_structures(failures: list[str]) -> None:
    """Assert the structural claims in the status doc still hold."""

    print("\n== structural counts in the status doc ==")
    counts = structural_counts()
    text = text_of(REPO_ROOT / "docs" / "backend-status.md")

    expectations = [
        ("API 路由", f"**{counts['total_routes']} 條**", counts["total_routes"]),
        ("JSON 端點", f"{counts['json_endpoints']} 個 JSON 端點", counts["json_endpoints"]),
        ("應用程式碼", f"{counts['app_modules']} 個模組", counts["app_modules"]),
        ("測試程式碼", f"{counts['test_files']} 個檔案", counts["test_files"]),
        ("開發工具", f"{counts['tools']} 支腳本", counts["tools"]),
    ]
    for label, needle, value in expectations:
        ok = needle in text
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: {needle} (= {value})")
        if not ok:
            failures.append(f"status doc should say {needle!r} for {label}")


def fix_counts(failures: list[str]) -> None:
    """Rewrite stale test counts in the docs to the real number.

    Adding a test changes the number that three documents quote, so this is the one
    figure that goes stale by doing the right thing. ``--fix`` rewrites it in place
    instead of making the author hunt for four occurrences.
    """

    import re

    total = collected_tests()
    if not total:
        return

    print(f"\n== fixing test counts to {total} ==")
    patterns = [
        (r"(\d{3,4})(\s*passed)", "passed"),
        (r"(\d{3,4})(\s*個測試)", "tests"),
        (r"測試（(\d{3,4})(\s*個）)", "paren"),
        (r"\*\*(\d{3,4})( 個\*\*)", "bold"),
    ]
    for path in DOCS:
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        changed = 0
        for index, line in enumerate(lines):
            if any(marker in line for marker in ("版本上", "舊版", "先前", "歷史")):
                continue
            updated = line
            for pattern, _kind in patterns:
                # Replace any 3-4 digit count that is not the real total.
                def swap(match: re.Match[str]) -> str:
                    value = int(match.group(1))
                    if value == total or value < 100:
                        return match.group(0)
                    return match.group(0).replace(match.group(1), str(total), 1)

                updated = re.sub(pattern, swap, updated)
            if updated != line:
                lines[index] = updated
                changed += 1
        if changed:
            path.write_text("".join(lines), encoding="utf-8")
            print(f"[FIXED] {path.name}: {changed} line(s)")
        else:
            print(f"[OK]    {path.name}")


def main() -> int:
    readme = text_of(REPO_ROOT / "README.md")
    integration = text_of(BACKEND_ROOT / "docs" / "integration.md")
    all_docs = readme + integration

    print("== cost example (381.6 kWh, summer) ==")
    cost = load("cost_summer_tiered")
    check("cost total", f"{cost['total_amount']}", readme)
    check("cost effective rate", f"{cost['effective_rate_per_kwh']}", readme)
    for line in cost["lines"]:
        check(f"tier {line['tier_index']} rate", f"{line['rate_per_kwh']}", readme)

    print("\n== recommendations example ==")
    recs = load("recommendations_student_room")
    check("blended rate", f"{recs['blended_rate_per_kwh']}", readme)
    check("headline saving kWh", f"{recs['total_potential_monthly_saving_kwh']}", readme)
    check("headline saving TWD", f"{recs['total_potential_monthly_saving_twd']}", readme)
    check("annual saving", f"{recs['total_potential_annual_saving_twd']}", readme)

    print("\n== simulate example ==")
    sim = load("simulate_reduce_ac_hours")
    check("baseline bill", f"{sim['baseline']['estimated_bill_twd']}", readme)
    check("modified bill", f"{sim['modified']['estimated_bill_twd']}", readme)
    check("saved amount", f"{sim['delta']['saved_amount_twd']}", readme)

    print("\n== tariff table in the README ==")
    tariffs = json.loads((BACKEND_ROOT / "app" / "data" / "tariffs.json").read_text(encoding="utf-8"))
    plan = tariffs["plans"]["tw_residential_tiered"]
    for season, label in (("summer", "夏月"), ("non_summer", "非夏月")):
        for tier in plan["seasons"][season]["tiers"]:
            rate = f"{tier['rate']:g}"
            check(f"{label} tier {tier['index']} rate in README", rate, readme)

    print("\n== published worked example (700 kWh July = 2423.1) ==")
    check("worked example total", "2,423.10", readme)

    print("\n== stale values that must NOT appear ==")
    # Values that were replaced and are not documented as history.
    stale = ["907.02", "2.3769", "275.95", "262.95", "2977"]
    for value in stale:
        absent = value not in all_docs
        print(f"[{'PASS' if absent else 'FAIL'}] {value} absent")
        if not absent:
            failures.append(f"stale value {value} still in docs")

    # 2,977.10 is allowed only inside the explicit "old rate" comparison paragraph.
    old_rate_marker = "舊費率（2024-04-01 ～ 2025-09-30）"
    occurrences = readme.count("2,977.10")
    allowed = 1 if old_rate_marker in readme else 0
    ok = occurrences <= allowed
    print(
        f"[{'PASS' if ok else 'FAIL'}] 2,977.10 only in the historical note "
        f"(occurrences={occurrences}, allowance={allowed})"
    )
    if not ok:
        failures.append("2,977.10 appears outside the historical rate note")

    if "--fix" in sys.argv[1:]:
        fix_counts(failures)
        fix_share(failures)

    if "--fast" not in sys.argv[1:]:
        check_structures(failures)
        check_counts(failures)

    print()
    if failures:
        print(f"{len(failures)} problem(s):")
        for item in failures:
            print("  -", item)
        return 1
    print("documented numbers match the generated examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
