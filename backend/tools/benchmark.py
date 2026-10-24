"""Micro-benchmark the calculation core, to guide optimisation decisions.

Measures the pure calculation functions and the full in-process request path so we can
tell whether a change is a real win rather than a guess.

Usage::

    python tools/benchmark.py [iterations]
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

# The app opens its database store during startup; benchmarks must not touch real data.
os.environ.setdefault("VOLTSPACE_DB", str(BACKEND_ROOT / ".test-data" / "benchmark.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ROOM = [
    {
        "appliance_id": f"a{i}",
        "name": name,
        "power_watts": watts,
        "hours_per_day": hours,
        "days_per_month": 30,
        "voltage": voltage,
    }
    for i, (name, watts, hours, voltage) in enumerate(
        [
            ("冷氣機", 900, 9, 220),
            ("冰箱", 130, 24, 110),
            ("桌上型電腦", 250, 6, 110),
            ("電熱水器", 4000, 1, 220),
            ("吹風機", 1200, 0.3, 110),
            ("洗衣機", 500, 0.5, 110),
            ("照明", 20, 6, 110),
            ("電視", 100, 3, 110),
        ]
    )
]


def timeit(label: str, func, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        samples.append((time.perf_counter() - start) * 1000)
    median = statistics.median(samples)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
    print(f"  {label:44} median {median:7.3f} ms   p95 {p95:7.3f} ms")
    return median


def main() -> int:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    from app.calculators.consumption import calculate_consumption
    from app.calculators.electricity_bill import calculate_bill
    from app.calculators.load_estimator import estimate_load
    from app.services.recommendations import catalog_summary, generate_recommendations
    from app.services.simulation import simulate

    print(f"iterations={iterations}\n")

    print("pure functions (8 appliances):")
    timeit("calculate_consumption", lambda: calculate_consumption(ROOM), iterations)
    timeit("calculate_bill (tiered)", lambda: calculate_bill(381.6, month=8), iterations * 10)
    timeit("estimate_load", lambda: estimate_load(ROOM, load_limit_amps=15), iterations)
    timeit(
        "generate_recommendations",
        lambda: generate_recommendations(ROOM, month=8),
        iterations,
    )
    timeit(
        "simulate",
        lambda: simulate(
            ROOM,
            [{"appliance_id": "a0", "field": "hours_per_day", "value": 6}],
            month=8,
            load_limit_amps=15,
        ),
        iterations,
    )
    timeit("catalog_summary", lambda: catalog_summary(), iterations * 10)

    print("\nfull request path (TestClient):")
    with TestClient(app) as client:
        cases = {
            "/calculate/consumption": {"appliances": ROOM},
            "/calculate/cost": {"consumption_kwh": 381.6, "month": 8},
            "/calculate/load": {"appliances": ROOM, "load_limit_amps": 15},
            "/recommendations": {"appliances": ROOM, "month": 8},
            "/simulate": {
                "appliances": ROOM,
                "changes": [{"appliance_id": "a0", "field": "hours_per_day", "value": 6}],
                "month": 8,
            },
        }
        for path, payload in cases.items():
            response = client.post(path, json=payload)
            assert response.status_code == 200, (path, response.status_code)
            timeit(path, lambda p=path, d=payload: client.post(p, json=d), iterations)

        # Scale check: does a larger household stay linear?
        big = [dict(ROOM[i % len(ROOM)], appliance_id=f"b{i}") for i in range(120)]
        timeit(
            "/calculate/consumption (120 appliances)",
            lambda: client.post("/calculate/consumption", json={"appliances": big}),
            iterations,
        )
        timeit(
            "/recommendations (120 appliances)",
            lambda: client.post("/recommendations", json={"appliances": big, "month": 8}),
            iterations,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
