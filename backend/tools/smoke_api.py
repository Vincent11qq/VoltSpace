"""Smoke-test the running API with real HTTP requests.

Run against a live server started with::

    uvicorn app.main:app --port 8077

Usage::

    python tools/smoke_api.py [base_url]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"

ROOM = [
    {
        "appliance_id": "a1",
        "name": "冷氣機",
        "category": "cooling",
        "power_watts": 900,
        "hours_per_day": 9,
        "days_per_month": 30,
        "voltage": 220,
    },
    {
        "appliance_id": "a2",
        "name": "冰箱",
        "category": "cooling",
        "power_watts": 130,
        "hours_per_day": 24,
        "days_per_month": 30,
        "voltage": 110,
    },
    {
        "appliance_id": "a3",
        "name": "桌上型電腦",
        "category": "electronics",
        "power_watts": 250,
        "hours_per_day": 6,
        "days_per_month": 30,
        "voltage": 110,
    },
]

failures: list[str] = []


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def check(label: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    print(f"[{marker}] {label}" + (f" -> {detail}" if detail else ""), flush=True)
    if not condition:
        failures.append(label)


# --- wait for the server -----------------------------------------------------
for attempt in range(40):
    try:
        status, _ = call("GET", "/health")
        if status == 200:
            break
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.5)
else:
    print("server did not become ready")
    raise SystemExit(1)

print(f"target: {BASE}\n")

# --- health / reference ------------------------------------------------------
status, health = call("GET", "/health")
check("GET /health", status == 200 and health["status"] == "ok", health.get("version", ""))

status, tariffs = call("GET", "/tariffs")
check(
    "GET /tariffs",
    status == 200 and len(tariffs["plans"]) == 3,
    ",".join(plan["id"] for plan in tariffs["plans"]),
)

status, catalog = call("GET", "/appliances")
check("GET /appliances", status == 200 and catalog["count"] >= 10, f"{catalog['count']} entries")

# --- 1. consumption ----------------------------------------------------------
status, consumption = call("POST", "/calculate/consumption", {"appliances": ROOM})
# AC 900W*9h*30d = 243, fridge 93.6, PC 45 -> 381.6
check(
    "POST /calculate/consumption",
    status == 200 and abs(consumption["total_monthly_kwh"] - 381.6) < 0.01,
    f"total={consumption['total_monthly_kwh']} kWh, top={consumption['highest_consumption_appliance']}",
)

# --- 2. cost -----------------------------------------------------------------
status, cost = call(
    "POST", "/calculate/cost", {"consumption_kwh": consumption["total_monthly_kwh"], "month": 8}
)
check(
    "POST /calculate/cost (summer, tiered)",
    status == 200 and cost["total_amount"] > 0 and len(cost["lines"]) >= 3,
    f"{cost['total_amount']} TWD over {len(cost['lines'])} tiers, eff={cost['effective_rate_per_kwh']}",
)

status, cost_bi = call(
    "POST",
    "/calculate/cost",
    {"consumption_kwh": consumption["total_monthly_kwh"] * 2, "month": 8, "billing_period": "bi_monthly"},
)
check(
    "POST /calculate/cost (two-month bill)",
    status == 200 and cost_bi["billing_months"] == 2,
    f"{cost_bi['total_amount']} TWD",
)

status, cost_flat = call(
    "POST", "/calculate/cost", {"consumption_kwh": 358, "plan_id": "flat_rate_resell_reference"}
)
check(
    "POST /calculate/cost (landlord flat rate)",
    status == 200 and abs(cost_flat["total_amount"] - 358 * 5.5) < 0.01,
    f"{cost_flat['total_amount']} TWD",
)

# --- 3. load -----------------------------------------------------------------
status, load = call(
    "POST",
    "/calculate/load",
    {
        "appliances": [
            {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110},
            {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110},
        ],
        "load_limit_amps": 15,
        "breaker_amps": 20,
        "circuit_label": "房間插座迴路",
        "include_overload_combinations": True,
    },
)
check(
    "POST /calculate/load (over limit)",
    status == 200 and load["verdict"] == "over_limit",
    f"{load['estimated_total_current_amps']}A of {load['limit_amps']}A -> {load['verdict']}",
)
check(
    "  overload combination found",
    bool(load["overload_combinations"]["combinations"]),
    str(load["overload_combinations"]["combinations"][:1]),
)
check(
    "  safety disclaimer present",
    "不構成電路安全保證" in load["disclaimer_zh"],
)

# --- 4. recommendations ------------------------------------------------------
status, recs = call("POST", "/recommendations", {"appliances": ROOM, "month": 8, "top_n": 3})
check(
    "POST /recommendations",
    status == 200 and recs["recommendation_count"] > 0,
    f"{recs['recommendation_count']} suggestions, save {recs['total_potential_monthly_saving_kwh']} kWh / {recs['total_potential_monthly_saving_twd']} TWD per month",
)
for item in recs["recommendations"][:3]:
    print(f"         - [{item['severity']}] {item['title_zh']} ({item['estimated_monthly_saving_kwh']} kWh)")
check(
    "  every suggestion explains why and how",
    all(item["reason_zh"] and item["suggestion_zh"] for item in recs["recommendations"]),
)
check(
    "  aggregate avoids double counting the same appliance",
    recs["comprehensive_monthly_saving_kwh"] >= recs["total_potential_monthly_saving_kwh"] > 0,
    f"headline {recs['total_potential_monthly_saving_kwh']} kWh vs all-suggestions "
    f"{recs['comprehensive_monthly_saving_kwh']} kWh",
)

# --- 5. simulation -----------------------------------------------------------
status, simulation = call(
    "POST",
    "/simulate",
    {
        "appliances": ROOM,
        "changes": [
            {"appliance_id": "a1", "field": "hours_per_day", "value": 6},
            {
                "appliance_id": "a1",
                "field": "replace_with",
                "replacement": {"label": "一級能效變頻冷氣", "power_watts": 700},
            },
        ],
        "month": 8,
        "load_limit_amps": 15,
    },
)
check(
    "POST /simulate (hours + appliance swap)",
    status == 200 and simulation["delta"]["saved_kwh"] > 0,
    f"{simulation['baseline']['total_monthly_kwh']} -> {simulation['modified']['total_monthly_kwh']} kWh, "
    f"save {simulation['delta']['saved_amount_twd']} TWD/month",
)
check(
    "  baseline preserved (non-mutating)",
    simulation["baseline"]["appliances"][0]["power_watts"] == 900
    and simulation["modified"]["appliances"][0]["power_watts"] == 700,
)

# --- error handling ----------------------------------------------------------
status, error = call("POST", "/calculate/consumption", {"appliances": [{"name": "x", "power_watts": 0, "hours_per_day": 1}]})
check("422 on invalid power", status == 422 and error["code"] == "validation_error", f"field={error.get('field')}")

status, error = call("POST", "/simulate", {"appliances": ROOM, "changes": [{"appliance_id": "ghost", "field": "hours_per_day", "value": 3}]})
check("400 on unknown appliance", status == 400 and error["code"] == "appliance_not_found", error["message"][:60])

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    raise SystemExit(1)
print("all smoke checks passed")
