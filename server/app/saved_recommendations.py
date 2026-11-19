"""Save product recommendations into Member B's ``recommendations`` table.

Member B delivered ``Supabase/member-b-latest/recommendations.sql``: a saved-output table
holding ``household_id``, ``appliance_id``, ``product_id``, the estimated savings and a
reason. Nothing ever wrote to it - ``/product-recommendations`` computed the advice and
returned it, then forgot it - so the table stayed empty and the delivered SQL did nothing.

Persisting is deliberately best-effort:

  * no Supabase configured      -> 0 rows, and the endpoint still answers
  * a foreign key the table does not know (empty households/appliances on a fresh project)
    -> the insert fails, we return 0 and the response is unaffected

Advice must never break because a log table is unhappy.
"""

from __future__ import annotations

from typing import Any

import httpx

from .storage import supabase_settings

TABLE = "recommendations"


def _endpoint(settings: dict[str, Any]) -> str:
    return f"{settings['url'].rstrip('/')}/rest/v1/{TABLE}"


def _headers(settings: dict[str, Any], prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": settings["key"],
        "Authorization": f"Bearer {settings['key']}",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def to_row(
    item: dict[str, Any],
    *,
    household_id: str | None,
    appliance_id: int | None = None,
) -> dict[str, Any]:
    """One API recommendation -> one table row."""

    reason = " ".join(
        part
        for part in (
            f"{item.get('brand') or ''} {item.get('product_name') or ''}".strip(),
            f"saves {item.get('estimated_savings_kwh')} kWh/month"
            if item.get("estimated_savings_kwh") is not None
            else "",
        )
        if part
    )
    return {
        "household_id": household_id,
        "appliance_id": appliance_id,
        "product_id": item.get("product_id"),
        "estimated_savings_kwh": item.get("estimated_savings_kwh"),
        "estimated_savings_cost": item.get("estimated_savings_cost"),
        "reason": reason or None,
    }


def save(
    items: list[dict[str, Any]],
    *,
    household_id: str | None = None,
    appliance_id: int | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> int:
    """Insert the recommendations. Returns how many rows were stored."""

    if not items:
        return 0

    try:
        settings = supabase_settings()
    except Exception:
        return 0
    if settings is None:
        return 0

    household = household_id or settings.get("household_id")
    rows = [
        to_row(item, household_id=household, appliance_id=appliance_id)
        for item in items
        if item.get("product_id") is not None
    ]
    if not rows:
        return 0

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(
                _endpoint(settings),
                json=rows,
                headers={**_headers(settings, "return=minimal"), "Content-Type": "application/json"},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        # Missing table, missing foreign key, no permission: the advice still stands.
        return 0
    return len(rows)


def latest(
    *,
    limit: int = 20,
    household_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """The most recently saved recommendations, newest first."""

    try:
        settings = supabase_settings()
    except Exception:
        return []
    if settings is None:
        return []

    household = household_id or settings.get("household_id")
    params = [("select", "*"), ("order", "created_at.desc"), ("limit", str(limit))]
    if household:
        params.append(("household_id", f"eq.{household}"))

    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.get(_endpoint(settings), params=params, headers=_headers(settings))
            response.raise_for_status()
            rows = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    return rows if isinstance(rows, list) else []
