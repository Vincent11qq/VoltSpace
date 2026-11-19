"""Supabase product catalogue and energy-saving recommendations."""

from __future__ import annotations

import os
from typing import Any

import httpx


PRODUCTS_TABLE = "products"


def _get_supabase_config() -> tuple[str, str]:
    """Read Supabase credentials from backend environment variables."""

    url = os.getenv("SUPABASE_URL", "").rstrip("/")

    key = (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    )

    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or Supabase API key in backend environment."
        )

    return url, key


def fetch_active_products() -> list[dict[str, Any]]:
    """Fetch active products from Supabase."""

    url, key = _get_supabase_config()

    endpoint = f"{url}/rest/v1/{PRODUCTS_TABLE}"

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    params = {
        "select": "*",
        "is_active": "eq.true",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                endpoint,
                headers=headers,
                params=params,
            )

        response.raise_for_status()

    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not fetch products from Supabase: {exc}") from exc

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError("Unexpected response from Supabase products table.")

    return data


def _normalise_category(category: Any) -> str:
    """Make category matching case-insensitive."""

    if category is None:
        return ""

    return str(category).strip().lower().replace("-", "_").replace(" ", "_")


def generate_product_recommendations(
    appliances: list[dict[str, Any]],
    effective_rate_per_kwh: float,
    *,
    max_recommendations: int = 5,
) -> list[dict[str, Any]]:
    """Match appliances with lower-power products and estimate savings."""

    products = fetch_active_products()

    recommendations: list[dict[str, Any]] = []

    for appliance in appliances:
        appliance_category = _normalise_category(appliance.get("category"))

        if not appliance_category:
            continue

        current_power = float(appliance.get("power_watts") or 0)
        hours_per_day = float(appliance.get("hours_per_day") or 0)
        days_per_month = float(appliance.get("days_per_month") or 30)
        quantity = int(appliance.get("quantity") or 1)

        if current_power <= 0:
            continue

        for product in products:
            product_category = _normalise_category(product.get("category"))

            # Only recommend products in the same category.
            if product_category != appliance_category:
                continue

            product_power = product.get("power_watts")

            if product_power is None:
                continue

            product_power = float(product_power)

            # Only recommend products that use less power.
            if product_power >= current_power:
                continue

            saved_kwh = (
                (current_power - product_power)
                * hours_per_day
                * days_per_month
                * quantity
                / 1000
            )

            saved_cost = saved_kwh * effective_rate_per_kwh

            recommendations.append(
                {
                    "appliance_name": appliance.get("name"),
                    "appliance_category": appliance_category,
                    "current_power_watts": current_power,
                    "product": {
                        "id": product.get("id"),
                        "name": product.get("name"),
                        "brand": product.get("brand"),
                        "model": product.get("model"),
                        "category": product.get("category"),
                        "power_watts": product_power,
                        "voltage": product.get("voltage"),
                        "energy_rating": product.get("energy_rating"),
                        "price": product.get("price"),
                        "currency": product.get("currency", "TWD"),
                        "product_url": product.get("product_url"),
                        "image_url": product.get("image_url"),
                        "description": product.get("description"),
                    },
                    "estimated_savings_kwh": round(saved_kwh, 2),
                    "estimated_savings_cost": round(saved_cost, 2),
                }
            )

    recommendations.sort(
        key=lambda item: item["estimated_savings_cost"],
        reverse=True,
    )

    return recommendations[:max_recommendations]
