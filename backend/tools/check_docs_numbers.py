"""Cross-check the numbers written in the docs against the generated examples.

Documentation drifts. This script reads ``docs/examples/*.json`` (which are produced by
running the real code) and asserts that the figures quoted in the README and the
integration notes actually appear there.

Usage::

    python tools/check_docs_numbers.py
"""

from __future__ import annotations

import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
EXAMPLES = BACKEND_ROOT / "docs" / "examples"
DOCS = [REPO_ROOT / "README.md", BACKEND_ROOT / "docs" / "integration.md"]

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
