"""Convert the group's ``electricity tariff.py`` dicts into VoltSpace's JSON format.

The rates were supplied as two flat Python dicts::

    Summer = {
        "first_120_kwh": 1.78,
        "next_210_kwh": 2.55,
        ...
    }

VoltSpace stores the same information as tiered JSON (see ``app/data/tariffs.json``).
This script performs that conversion so a future tariff revision can be applied by
editing the dicts and re-running it, instead of hand-editing JSON and risking a typo.

It writes the tier rates into the plan in ``app/data/tariffs.json`` and updates the
``effective_from`` / ``updated_at`` fields. It does **not** touch the notes, which are
maintained by hand.

Usage::

    # dry run: show what would change
    python tools/import_tariff.py

    # apply, using the rate table below (edit it when Taipower publishes new prices)
    python tools/import_tariff.py --apply

    # apply a specific date
    python tools/import_tariff.py --apply --effective-from 2026-04-01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TARIFF_FILE = BACKEND_ROOT / "app" / "data" / "tariffs.json"

# The rate table to import. Order is significant: it maps onto the six tiers
# (120 / 330 / 500 / 700 / 1000 / open ended).
#
# Source: the group's "electricity tariff.py" (Member A/B), which matches the Ministry of
# Economic Affairs adjustment effective 2025-10-01.
SUMMER = {
    "first_120_kwh": 1.78,
    "next_210_kwh": 2.55,
    "next_170_kwh": 3.80,
    "next_200_kwh": 5.14,
    "next_300_kwh": 6.44,
    "over_1000_kwh": 8.86,
}
NON_SUMMER = {
    "first_120_kwh": 1.78,
    "next_210_kwh": 2.26,
    "next_170_kwh": 3.13,
    "next_200_kwh": 4.24,
    "next_300_kwh": 5.27,
    "over_1000_kwh": 7.03,
}

# The keys, in tier order, and the ceiling each one covers.
TIER_KEYS = [
    "first_120_kwh",
    "next_210_kwh",
    "next_170_kwh",
    "next_200_kwh",
    "next_300_kwh",
    "over_1000_kwh",
]
TIER_CEILINGS = [120, 330, 500, 700, 1000, None]


def to_rates(table: dict[str, float]) -> list[float]:
    missing = [key for key in TIER_KEYS if key not in table]
    if missing:
        raise SystemExit(f"rate table is missing {missing}")
    return [float(table[key]) for key in TIER_KEYS]


def verify_structure(rates: list[float], season: str) -> None:
    if len(rates) != len(TIER_CEILINGS):
        raise SystemExit(f"{season}: expected {len(TIER_CEILINGS)} rates, got {len(rates)}")
    if any(rate <= 0 for rate in rates):
        raise SystemExit(f"{season}: every rate must be greater than 0")
    # Progressive tariffs are monotonically increasing; a decrease signals a typo.
    for index in range(1, len(rates)):
        if rates[index] < rates[index - 1]:
            raise SystemExit(
                f"{season}: rate {index + 1} ({rates[index]}) is lower than "
                f"rate {index} ({rates[index - 1]}); tiers must increase"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the file")
    parser.add_argument(
        "--effective-from",
        default=None,
        help="date the new rates take effect, e.g. 2026-04-01 (default: keep current)",
    )
    args = parser.parse_args()

    data = json.loads(TARIFF_FILE.read_text(encoding="utf-8"))
    plan = data["plans"]["tw_residential_tiered"]

    incoming = {
        "summer": to_rates(SUMMER),
        "non_summer": to_rates(NON_SUMMER),
    }
    for season, rates in incoming.items():
        verify_structure(rates, season)

    print(f"{'season':12} {'current':38} {'incoming':38} changed")
    any_change = False
    for season, rates in incoming.items():
        current = [tier["rate"] for tier in plan["seasons"][season]["tiers"]]
        changed = current != rates
        any_change = any_change or changed
        print(f"{season:12} {str(current):38} {str(rates):38} {changed}")

    if not any_change and args.effective_from is None:
        print("\nno changes: the data file already matches this rate table")
        return 0

    if not args.apply:
        print("\ndry run: re-run with --apply to write the file")
        return 0

    for season, rates in incoming.items():
        for tier, rate in zip(plan["seasons"][season]["tiers"], rates):
            tier["rate"] = rate
        for tier, ceiling in zip(plan["seasons"][season]["tiers"], TIER_CEILINGS):
            tier["up_to_kwh"] = ceiling

    if args.effective_from:
        plan["effective_from"] = args.effective_from
        data["updated_at"] = args.effective_from

    TARIFF_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {TARIFF_FILE}")
    print("Next: python -m app.data_check  &&  python -m pytest tests/test_electricity_bill.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
