"""Audit the API against awkward payloads with an explicit expected status per probe.

Two guarantees are checked:

* no payload produces an unhandled 5xx, and
* every 4xx uses the shared ``{error, code, message}`` shape.

``EXPECTED`` records the status we believe is correct, so a silent behaviour change
(e.g. a valid request starting to fail) is caught rather than ignored.

Usage::

    python tools/probe_errors.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# The app opens its database store during startup; keep probes off the real household.
os.environ.setdefault("VOLTSPACE_DB", str(BACKEND_ROOT / ".test-data" / "probe.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AC = {
    "name": "冷氣機",
    "power_watts": 900,
    "hours_per_day": 6,
    "days_per_month": 30,
    "voltage": 220,
}

# (id, endpoint, payload, expected_status)
PROBES: list[tuple[str, str, dict, int]] = [
    # --- malformed payload shapes -------------------------------------------
    ("list-not-array", "/calculate/consumption", {"appliances": "not-a-list"}, 422),
    ("null-in-list", "/calculate/consumption", {"appliances": [None]}, 422),
    ("array-in-list", "/calculate/consumption", {"appliances": [[]]}, 422),
    ("missing-required", "/calculate/consumption", {"appliances": [{"name": "x"}]}, 422),
    ("missing-body-field", "/calculate/consumption", {}, 422),
    # Pydantic coerces a numeric string; "abc" is rejected (see non-numeric-string).
    ("numeric-string-coerced", "/calculate/consumption", {"appliances": [{**AC, "power_watts": "900"}]}, 200),
    ("non-numeric-string", "/calculate/consumption", {"appliances": [{**AC, "power_watts": "abc"}]}, 422),
    # Python bool is an int subclass, so JSON `true` coerces to 1W. Documented, not a crash.
    ("bool-as-power-coerced", "/calculate/consumption", {"appliances": [{**AC, "power_watts": True}]}, 200),
    ("empty-name", "/calculate/consumption", {"appliances": [{**AC, "name": ""}]}, 422),
    ("blank-name", "/calculate/consumption", {"appliances": [{**AC, "name": "  "}]}, 422),
    ("overlong-name", "/calculate/consumption", {"appliances": [{**AC, "name": "x" * 500}]}, 422),
    ("zero-voltage", "/calculate/consumption", {"appliances": [{**AC, "voltage": 0}]}, 422),
    ("negative-hours", "/calculate/consumption", {"appliances": [{**AC, "hours_per_day": -1}]}, 422),
    ("unknown-field", "/calculate/consumption", {"appliances": [{**AC, "wattage": 900}]}, 422),
    (
        "max-everything-is-valid",
        "/calculate/consumption",
        {"appliances": [{**AC, "power_watts": 1e5, "hours_per_day": 24, "days_per_month": 31, "quantity": 999}]},
        200,
    ),
    # --- cost ---------------------------------------------------------------
    ("cost-empty", "/calculate/cost", {}, 422),
    ("cost-unknown-plan", "/calculate/cost", {"consumption_kwh": 100, "plan_id": "bogus"}, 422),
    ("cost-month-zero", "/calculate/cost", {"consumption_kwh": 100, "month": 0}, 422),
    ("cost-unknown-season", "/calculate/cost", {"consumption_kwh": 100, "season": "bogus"}, 422),
    ("cost-peak-share-2", "/calculate/cost", {"consumption_kwh": 100, "peak_share": 2}, 422),
    ("cost-bad-period", "/calculate/cost", {"consumption_kwh": 100, "billing_period": "yearly"}, 422),
    ("cost-zero-months", "/calculate/cost", {"consumption_kwh": 100, "billing_months": 0}, 422),
    ("cost-appliances-not-array", "/calculate/cost", {"consumption_kwh": 100, "appliances": "nope"}, 422),
    # ``consumption_kwh`` is capped at 1e6; the boundary is inclusive.
    ("cost-above-kwh-cap", "/calculate/cost", {"consumption_kwh": 1_000_001}, 422),
    ("cost-at-kwh-cap", "/calculate/cost", {"consumption_kwh": 1_000_000}, 200),
    ("cost-zero-with-empty-list", "/calculate/cost", {"consumption_kwh": 0, "appliances": []}, 200),
    # --- load ---------------------------------------------------------------
    ("load-empty", "/calculate/load", {}, 422),
    ("load-zero-limit", "/calculate/load", {"appliances": [AC], "load_limit_amps": 0}, 422),
    ("load-zero-margin", "/calculate/load", {"appliances": [AC], "safety_margin": 0}, 422),
    ("load-bad-phases", "/calculate/load", {"appliances": [AC], "phases": 2}, 422),
    (
        "load-tiny-limit-with-combinations",
        "/calculate/load",
        {"appliances": [AC], "load_limit_amps": 0.001, "include_overload_combinations": True},
        200,
    ),
    (
        "load-max-combination-size",
        "/calculate/load",
        {
            "appliances": [AC],
            "load_limit_amps": 1000,
            "include_overload_combinations": True,
            "max_combination_size": 6,
        },
        200,
    ),
    # --- recommendations ----------------------------------------------------
    ("rec-empty", "/recommendations", {}, 422),
    ("rec-top-n-zero", "/recommendations", {"appliances": [AC], "top_n": 0}, 422),
    ("rec-max-rec-zero", "/recommendations", {"appliances": [AC], "max_recommendations": 0}, 422),
    ("rec-unknown-plan", "/recommendations", {"appliances": [AC], "plan_id": "bogus"}, 422),
    ("rec-month-13", "/recommendations", {"appliances": [AC], "month": 13}, 422),
    ("rec-zero-usage-is-valid", "/recommendations", {"appliances": [{**AC, "hours_per_day": 0}], "top_n": 1}, 200),
    # --- simulate -----------------------------------------------------------
    ("sim-empty", "/simulate", {}, 422),
    ("sim-no-changes", "/simulate", {"appliances": [AC], "changes": []}, 422),
    ("sim-blank-change", "/simulate", {"appliances": [AC], "changes": [{}]}, 422),
    (
        "sim-unknown-appliance",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "ghost", "field": "hours_per_day", "value": 1}]},
        400,
    ),
    (
        "sim-fractional-quantity",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "冷氣機", "field": "quantity", "value": 1.5}]},
        422,
    ),
    (
        "sim-hours-24-is-valid",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "冷氣機", "field": "hours_per_day", "value": 24}]},
        200,
    ),
    (
        "sim-empty-replacement-is-valid",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "冷氣機", "field": "replace_with", "replacement": {}}]},
        200,
    ),
    (
        "sim-replacement-zero-power",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "冷氣機", "field": "replace_with", "replacement": {"power_watts": 0}}]},
        422,
    ),
    (
        "sim-replacement-explicit-null-hours-keeps-original",
        "/simulate",
        {
            "appliances": [AC],
            "changes": [
                {
                    "name": "冷氣機",
                    "field": "replace_with",
                    "replacement": {"power_watts": 700, "hours_per_day": None},
                }
            ],
        },
        200,
    ),
    (
        "sim-unsupported-field",
        "/simulate",
        {"appliances": [AC], "changes": [{"name": "冷氣機", "field": "voltage", "value": 110}]},
        422,
    ),
    (
        "sim-zero-baseline-override",
        "/simulate",
        {
            "appliances": [AC],
            "changes": [{"name": "冷氣機", "field": "hours_per_day", "value": 6}],
            "baseline_override_kwh": 0,
        },
        200,
    ),
    (
        "sim-tiny-load-limit",
        "/simulate",
        {
            "appliances": [AC],
            "changes": [{"name": "冷氣機", "field": "hours_per_day", "value": 6}],
            "load_limit_amps": 0.001,
        },
        200,
    ),
    (
        "sim-all-zero-consumption",
        "/simulate",
        {
            "appliances": [{**AC, "hours_per_day": 0}],
            "changes": [{"name": "冷氣機", "field": "hours_per_day", "value": 0}],
        },
        200,
    ),
]

METHOD_PROBES = [
    ("GET", "/calculate/consumption", (405,)),
    ("PUT", "/simulate", (405,)),
    ("DELETE", "/recommendations", (405,)),
]


def main() -> int:
    failures: list[str] = []
    unexpected_ok: list[str] = []

    with TestClient(app, raise_server_exceptions=False) as client:
        for probe_id, path, payload, expected in PROBES:
            response = client.post(path, json=payload)
            status = response.status_code
            rendered = json.dumps(payload, ensure_ascii=False)[:110]

            if status >= 500:
                failures.append(
                    f"[5xx] {probe_id} {path} -> {status}: {response.text[:200]} | {rendered}"
                )
                continue

            if status != expected:
                message = f"[status] {probe_id} {path} expected {expected} got {status} | {rendered}"
                if status == 200 and expected != 200:
                    unexpected_ok.append(message)
                failures.append(message)
                continue

            if status in (400, 422):
                body = response.json()
                missing = [key for key in ("error", "code", "message") if key not in body]
                if missing:
                    failures.append(f"[shape] {probe_id} -> {status} missing {missing}: {body}")

            print(f"  ok  {probe_id:42} {status}", flush=True)

        for method, path, allowed in METHOD_PROBES:
            response = client.request(method, path)
            if response.status_code not in allowed:
                failures.append(
                    f"[method] {method} {path} expected {allowed} got {response.status_code}"
                )

    print()
    print(f"probes run: {len(PROBES)}   failures: {len(failures)}")
    if failures:
        for item in failures:
            print("  -", item)
        return 1
    print("no 5xx, no unexpected status, and every 4xx used the shared error shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
