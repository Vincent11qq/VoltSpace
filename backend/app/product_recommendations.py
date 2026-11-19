
from typing import Any

import httpx

from .storage import supabase_settings


def get_products() -> list[dict[str, Any]]:
    """Fetch active products from the Supabase products table."""

    settings = supabase_settings()

    if settings is None:
        return []

    url = settings["url"].rstrip("/") + "/rest/v1/products"

    headers = {
        "apikey": settings["key"],
        "Authorization": f"Bearer {settings['key']}",
        "Accept": "application/json",
    }

    params = {
        "select": "*",
        "is_active": "eq.true",
        "order": "id.asc",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                url,
                headers=headers,
                params=params,
            )
            response.raise_for_status()

        return response.json()

    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Could not fetch products from Supabase: {exc}"
        ) from exc


def get_product_recommendations(
    appliances: list[dict[str, Any]],
    products: list[dict[str, Any]],
    tariff: float,
) -> list[dict[str, Any]]:
    """Match lower-power products and estimate monthly energy savings."""

    recommendations = []

    for appliance in appliances:
        appliance_category = appliance.get("category")
        appliance_watts = appliance.get("power_watts")
        hours_per_day = appliance.get("hours_per_day") or 0
        days_per_month = appliance.get("days_per_month") or 30
        quantity = appliance.get("quantity") or 1

        if (
            not appliance_category
            or appliance_watts is None
            or appliance_watts <= 0
        ):
            continue

        matching_products = [
            product
            for product in products
            if product.get("category") == appliance_category
            and product.get("is_active", True)
            and product.get("power_watts") is not None
        ]

        for product in matching_products:
            product_watts = product.get("power_watts")

            if product_watts <= 0 or product_watts >= appliance_watts:
                continue

            saved_watts = appliance_watts - product_watts

            saved_kwh = (
                saved_watts
                * hours_per_day
                * days_per_month
                * quantity
                / 1000
            )

            saved_cost = saved_kwh * tariff

            recommendations.append({
                "appliance": appliance.get("name"),
                "product_id": product.get("id"),
                "product_name": product.get("name"),
                "brand": product.get("brand"),
                "model": product.get("model"),
                "category": product.get("category"),
                "power_watts": product_watts,
                "price": product.get("price"),
                "currency": product.get("currency", "TWD"),
                "energy_rating": product.get("energy_rating"),
                "product_url": product.get("product_url"),
                "image_url": product.get("image_url"),
                "description": product.get("description"),
                "estimated_savings_kwh": round(saved_kwh, 2),
                "estimated_savings_cost": round(saved_cost, 2),
            })

    recommendations.sort(
        key=lambda item: item["estimated_savings_cost"],
        reverse=True,
    )

    return recommendations
