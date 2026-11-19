"""End-to-end smoke test for the household endpoints added for the app integration.

Covers the whole user journey the UI performs:
  presets -> add appliances -> dashboard -> edit -> delete -> save-all -> dashboard

Usage::

    python tools/smoke_app.py [base_url]
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

failures: list[str] = []


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"raw": body}


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def wait_ready() -> bool:
    for _ in range(40):
        try:
            status, _ = call("GET", "/health")
            if status == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    if not wait_ready():
        print("server did not become ready")
        return 1
    print(f"target: {BASE}\n")

    # --- presets ------------------------------------------------------------
    status, presets = call("GET", "/appliances/presets")
    check(
        "GET /appliances/presets",
        status == 200 and len(presets["presets"]) >= 10,
        f"{len(presets.get('presets', []))} presets, {len(presets.get('circuits', []))} circuits",
    )
    room_circuit = presets["circuits"][0]
    check(
        "  circuit ceiling is derived, not hard-coded",
        room_circuit["max_watts"] == room_circuit["amps"] * room_circuit["voltage"],
        f"{room_circuit['label_en']} = {room_circuit['max_watts']} W",
    )
    check(
        "  reference rate comes from the tariff table",
        presets["reference_rate_per_kwh"] > 0,
        f"{presets['reference_rate_per_kwh']} TWD/kWh ({presets['reference_season']})",
    )

    # --- start clean --------------------------------------------------------
    status, _ = call("PUT", "/household/appliances", {"appliances": []})
    check("PUT /household/appliances (clear)", status == 200)

    # --- add appliances -----------------------------------------------------
    ac = next(p for p in presets["presets"] if p["key"] == "air_conditioner")
    fridge = next(p for p in presets["presets"] if p["key"] == "refrigerator")

    status, created = call(
        "POST",
        "/household/appliances",
        {
            "appliance": {
                "name": ac["name_zh"],
                "category": ac["category"],
                "power_watts": ac["power_watts"],
                "hours_per_day": ac["hours_per_day"],
                "days_per_month": ac["days_per_month"],
                "voltage": ac["voltage"],
            }
        },
    )
    check(
        "POST /household/appliances",
        status == 201 and created.get("power_watts") == ac["power_watts"],
        f"id={created.get('id')} {created.get('name')}",
    )
    ac_id = created.get("id")

    status, created2 = call(
        "POST",
        "/household/appliances",
        {
            "appliance": {
                "name": fridge["name_zh"],
                "power_watts": fridge["power_watts"],
                "hours_per_day": fridge["hours_per_day"],
                "days_per_month": fridge["days_per_month"],
                "voltage": fridge["voltage"],
            }
        },
    )
    check("POST /household/appliances (2nd)", status == 201, f"id={created2.get('id')}")

    status, listing = call("GET", "/household/appliances")
    check(
        "GET /household/appliances",
        status == 200 and listing["count"] == 2 and listing["total_monthly_kwh"] > 0,
        f"{listing['count']} appliances, {listing['total_monthly_kwh']} kWh/month",
    )

    # --- invalid appliance must be rejected before persisting ---------------
    status, error = call(
        "POST",
        "/household/appliances",
        {"appliance": {"name": "Bad", "power_watts": 0, "hours_per_day": 1}},
    )
    check(
        "invalid appliance rejected (422)",
        status == 422,
        f"code={error.get('code')} field={error.get('field')}",
    )
    status, listing = call("GET", "/household/appliances")
    check("  and nothing was persisted", listing["count"] == 2)

    # --- dashboard ----------------------------------------------------------
    status, dash = call(
        "POST",
        "/household/dashboard",
        {"month": 8, "load_limit_amps": 15, "include_recommendations": True},
    )
    check(
        "POST /household/dashboard (saved)",
        status == 200 and dash["source"] == "saved",
        f"{dash.get('appliance_count')} appliances",
    )
    summary = dash.get("summary", {})
    check(
        "  summary carries the numbers the UI shows",
        all(
            summary.get(key) is not None
            for key in (
                "total_monthly_kwh",
                "estimated_monthly_cost_twd",
                "estimated_total_current_amps",
                "load_verdict",
            )
        ),
        f"{summary.get('total_monthly_kwh')} kWh, {summary.get('estimated_monthly_cost_twd')} TWD, "
        f"{summary.get('estimated_total_current_amps')} A ({summary.get('load_verdict')})",
    )
    check(
        "  bill and recommendations are included",
        dash["bill"]["total_amount"] > 0 and dash["recommendations"]["recommendation_count"] > 0,
        f"{dash['recommendations']['recommendation_count']} suggestions",
    )

    # --- dashboard with an unsaved scratchpad -------------------------------
    status, scratch = call(
        "POST",
        "/household/dashboard",
        {
            "appliances": [
                {"name": "吹風機", "power_watts": 1200, "hours_per_day": 0.3, "voltage": 110},
                {"name": "電暖器", "power_watts": 1200, "hours_per_day": 3, "voltage": 110},
            ],
            "month": 8,
            "load_limit_amps": 15,
        },
    )
    check(
        "POST /household/dashboard (unsaved scratchpad)",
        status == 200 and scratch["source"] == "request",
        f"verdict={scratch['summary'].get('load_verdict')}",
    )
    check(
        "  overload is detected by the backend",
        scratch["summary"].get("load_verdict") == "over_limit",
        f"{scratch['summary'].get('estimated_total_current_amps')} A vs "
        f"{scratch['load']['limit_amps']} A",
    )

    # --- edit ---------------------------------------------------------------
    status, updated = call(
        "PUT", f"/household/appliances/{ac_id}", {"hours_per_day": 4}
    )
    check(
        "PUT /household/appliances/{id}",
        status == 200 and updated.get("hours_per_day") == 4,
        f"hours_per_day={updated.get('hours_per_day')}",
    )
    status, dash2 = call("POST", "/household/dashboard", {"month": 8})
    check(
        "  dashboard reflects the edit",
        dash2["summary"]["total_monthly_kwh"] < summary["total_monthly_kwh"],
        f"{summary['total_monthly_kwh']} -> {dash2['summary']['total_monthly_kwh']} kWh",
    )

    status, error = call("PUT", "/household/appliances/999999", {"hours_per_day": 4})
    check("update unknown id -> 404", status == 404, f"code={error.get('code')}")

    # --- save-all -----------------------------------------------------------
    status, replaced = call(
        "PUT",
        "/household/appliances",
        {
            "appliances": [
                {"name": "冷氣機", "power_watts": 900, "hours_per_day": 6,
                 "days_per_month": 30, "voltage": 220},
                {"name": "冰箱", "power_watts": 130, "hours_per_day": 24,
                 "days_per_month": 30, "voltage": 110},
                {"name": "照明", "power_watts": 20, "hours_per_day": 6,
                 "days_per_month": 30, "voltage": 110},
            ]
        },
    )
    check(
        "PUT /household/appliances (save all)",
        status == 200 and replaced["count"] == 3,
        f"{replaced['count']} saved",
    )

    # --- delete -------------------------------------------------------------
    some_id = replaced["appliances"][0]["id"]
    status, deleted = call("DELETE", f"/household/appliances/{some_id}")
    check("DELETE /household/appliances/{id}", status == 200 and deleted.get("deleted") is True)
    status, after = call("GET", "/household/appliances")
    check("  count went down", after["count"] == 2, f"{after['count']} remain")

    # --- empty household must still render ----------------------------------
    call("PUT", "/household/appliances", {"appliances": []})
    status, empty = call("POST", "/household/dashboard", {"month": 8})
    check(
        "dashboard on an empty household",
        status == 200 and empty["summary"]["total_monthly_kwh"] == 0,
        f"{empty['summary']['total_monthly_kwh']} kWh, bill "
        f"{empty['summary']['estimated_monthly_cost_twd']} TWD",
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {failures}")
        return 1
    print("all app-integration checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
