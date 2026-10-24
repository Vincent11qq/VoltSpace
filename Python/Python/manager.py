"""Member B's original Supabase adapter — kept for reference, credentials removed.

SUPERSEDED
----------
The working implementation now lives in ``backend/app/store.py`` (local SQLite) with the
schema in ``backend/db/schema.sql``. See ``backend/docs/supabase.md`` for how to point the
backend at Supabase instead.

Two things were wrong with this file and are fixed here:

1. **Credentials were hard-coded** and had been committed to the repository. They now come
   from environment variables, and nothing is embedded in the source.
2. **Importing the module performed database queries and printed them.** Importing a
   module must not have side effects, so the client is created lazily.

The column names also did not match the calculation API (``power``/``minutes`` versus
``power_watts``/``hours_per_day``); the mapping helpers below spell that out.
"""

from __future__ import annotations

import os

# Values that used to be literals in this file are now environment-driven.
SUPABASE_URL_ENV = "VOLTSPACE_SUPABASE_URL"
SUPABASE_KEY_ENV = "VOLTSPACE_SUPABASE_KEY"

_client = None


def get_client():
    """Create the Supabase client on first use.

    Raises a clear error instead of failing at import time when the environment is not
    configured.
    """

    global _client
    if _client is not None:
        return _client

    url = os.environ.get(SUPABASE_URL_ENV)
    key = os.environ.get(SUPABASE_KEY_ENV)
    if not url or not key:
        raise RuntimeError(
            "Supabase is not configured. Set both environment variables:\n"
            f"    {SUPABASE_URL_ENV}=https://YOUR-PROJECT.supabase.co\n"
            f"    {SUPABASE_KEY_ENV}=<publishable / anon key>\n"
            "The app does not need Supabase: it stores data locally by default "
            "(backend/app/store.py)."
        )

    from supabase import create_client

    _client = create_client(url, key)
    return _client


def minutes_to_hours(minutes: float) -> float:
    """The old schema stored usage in minutes; the calculators work in hours."""

    return float(minutes) / 60.0


def hours_to_minutes(hours: float) -> float:
    return float(hours) * 60.0


def to_api_appliance(row: dict) -> dict:
    """Map a legacy ``appliances`` row onto the calculation API's shape."""

    return {
        "appliance_id": str(row["id"]),
        "name": row["appliance"],
        "category": None,
        "power_watts": float(row["power"]),
        "hours_per_day": minutes_to_hours(row["minutes"]),
        "days_per_month": 30,
        "quantity": int(row["quantity"]),
        "voltage": None,
    }


def to_legacy_row(appliance: dict) -> dict:
    """Map an API-shaped appliance back onto the legacy columns."""

    return {
        "appliance": appliance["name"],
        "power": int(round(float(appliance["power_watts"]))),
        "quantity": int(appliance.get("quantity", 1)),
        "minutes": hours_to_minutes(float(appliance["hours_per_day"])),
    }


def get_appliances() -> list[dict]:
    response = get_client().table("appliances").select("*").execute()
    return response.data


def add_appliance(appliance: dict) -> list[dict]:
    """Insert one API-shaped appliance, validating it with the shared rules first."""

    from app.calculators.consumption import validate_appliance

    validate_appliance(appliance)
    response = get_client().table("appliances").insert(to_legacy_row(appliance)).execute()
    return response.data


def calculate_daily_energy(power: float, quantity: int, minutes: float) -> float:
    """kWh for ONE day of this usage."""

    from app.calculators.consumption import daily_energy_kwh

    return daily_energy_kwh(
        power_watts=power,
        hours_per_day=minutes_to_hours(minutes),
        quantity=quantity,
    )


def calculate_energy(power: float, quantity: int, minutes: float, days_per_month: int = 30) -> float:
    """kWh for a whole month of this usage (the original intent of this function).

    Previously ``power * quantity * minutes / 60000``, which is a *daily* figure; that made
    the name ``calculate_energy`` ambiguous. It now returns the monthly value used by the
    rest of the app, and :func:`calculate_daily_energy` gives the one-day figure.

    Both route through the shared calculator so the formula exists in exactly one place.
    """

    from app.calculators.consumption import monthly_energy_kwh

    return monthly_energy_kwh(
        power_watts=power,
        hours_per_day=minutes_to_hours(minutes),
        days_per_month=days_per_month,
        quantity=quantity,
    )
