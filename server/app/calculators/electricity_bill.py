"""Electricity bill estimation against the tariff data in ``app/data/tariffs.json``.

Design rule: **no price is hard-coded here.** Every rate comes from the JSON data
file through :func:`load_tariffs`, so a tariff revision is a data change only.

Supported plan types
--------------------
``tiered``      Progressive (Taiwan Taipower residential) tiers. Tier ceilings apply
                to one billing period, so a 2-month bill gets doubled ceilings.
``time_of_use`` Two-segment peak / off-peak estimation.
``flat``        A single per-kWh price (typical rented-room resale price).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "tariffs.json"

SUMMER = "summer"
NON_SUMMER = "non_summer"
VALID_SEASONS = (SUMMER, NON_SUMMER)
VALID_PERIODS = ("monthly", "bi_monthly")

# Number of billed months implied by a billing period.
PERIOD_MONTHS: dict[str, int] = {"monthly": 1, "bi_monthly": 2}


class TariffError(ValueError):
    """Raised when a tariff plan or an input cannot be resolved."""

    def __init__(self, message: str, *, code: str = "tariff_error") -> None:
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=1)
def load_tariffs(path: str | None = None) -> dict[str, Any]:
    """Load and cache the tariff data file."""

    target = Path(path) if path else DATA_FILE
    if not target.exists():
        raise TariffError(f"tariff data file not found: {target}", code="tariff_file_missing")
    with target.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or "plans" not in data:
        raise TariffError("tariff data file is malformed", code="tariff_file_malformed")
    return data


def list_plans() -> list[dict[str, Any]]:
    """Return a compact summary of every available plan (for the frontend)."""

    data = load_tariffs()
    summaries: list[dict[str, Any]] = []
    for plan in data["plans"].values():
        summaries.append(
            {
                "id": plan["id"],
                "name_en": plan.get("name_en"),
                "name_zh": plan.get("name_zh"),
                "type": plan.get("type"),
                "currency": plan.get("currency", data.get("currency", "TWD")),
                "unit": plan.get("unit", "kWh"),
                "applicable_to": plan.get("applicable_to"),
                "effective_from": plan.get("effective_from"),
                "is_estimate": bool(plan.get("is_estimate", False)),
                "supports_billing_months": bool(plan.get("supports_billing_months", False)),
            }
        )
    return summaries


def get_plan(plan_id: str | None = None) -> dict[str, Any]:
    """Fetch one plan by id, defaulting to the file's default plan."""

    return _plan_from(load_tariffs(), plan_id)


def available_plan_ids() -> list[str]:
    """Every plan id in the data file (used to build the request schema enum)."""

    return sorted(load_tariffs()["plans"])


def resolve_season(month: int | None, *, tariffs: Mapping[str, Any] | None = None) -> str:
    """Map a calendar month to the tariff season."""

    if month is None:
        return NON_SUMMER
    if not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12:
        raise TariffError("month must be an integer between 1 and 12", code="invalid_month")
    data = tariffs if tariffs is not None else load_tariffs()
    rules = data["season_rules"]
    if month in rules[SUMMER]["months"]:
        return SUMMER
    return NON_SUMMER


def season_label(season: str, *, tariffs: Mapping[str, Any] | None = None) -> dict[str, str]:
    data = tariffs if tariffs is not None else load_tariffs()
    rules = data["season_rules"]
    if season not in rules:
        raise TariffError(f"unknown season '{season}'", code="invalid_season")
    return {"label_en": rules[season]["label_en"], "label_zh": rules[season]["label_zh"]}


def _validate_consumption(consumption_kwh: float) -> float:
    if isinstance(consumption_kwh, bool) or not isinstance(consumption_kwh, (int, float)):
        raise TariffError("consumption_kwh must be a number", code="not_a_number")
    value = float(consumption_kwh)
    if math.isnan(value) or math.isinf(value):
        raise TariffError("consumption_kwh must be finite", code="not_finite")
    if value < 0:
        raise TariffError("consumption_kwh cannot be negative", code="negative_consumption")
    return value


def _period_months(billing_period: str | None, billing_months: int | None) -> int:
    """Resolve how many months one bill covers."""

    if billing_months is not None:
        if isinstance(billing_months, bool) or not isinstance(billing_months, int):
            raise TariffError("billing_months must be a whole number", code="invalid_billing_months")
        if billing_months < 1 or billing_months > 12:
            raise TariffError(
                "billing_months must be between 1 and 12", code="invalid_billing_months"
            )
        return billing_months
    if billing_period is None:
        return 1
    if billing_period not in PERIOD_MONTHS:
        raise TariffError(
            f"billing_period must be one of {', '.join(VALID_PERIODS)}", code="invalid_billing_period"
        )
    return PERIOD_MONTHS[billing_period]


def _enforce_period_support(plan: Mapping[str, Any], months: int) -> None:
    """Reject a per-period setting that the plan cannot honour.

    Only a tiered plan prices *per billing period* (its ceilings are scaled). A flat or
    time-of-use plan charges the same per kWh regardless of the period, so silently
    echoing ``billing_months: 2`` would show "2 months" while pricing one month's worth.
    """

    if months <= 1:
        return
    if plan.get("type") != "tiered" or not plan.get("supports_billing_months", True):
        raise TariffError(
            f"tariff plan '{plan['id']}' charges per kWh and does not support a "
            f"{months}-month billing period; send billing_period='monthly' or omit "
            "billing_months for this plan",
            code="plan_does_not_support_billing_months",
        )


def _round(value: float, digits: int = 2) -> float:
    # Taipower rounds the final bill to the nearest dollar; callers decide whether
    # to use ``total_amount_rounded`` or the raw float.
    return round(value + 0.0, digits)


@dataclass
class BillBreakdown:
    """A complete, self-describing bill estimate."""

    plan_id: str
    plan_name_en: str | None
    plan_name_zh: str | None
    plan_type: str
    season: str
    consumption_kwh: float
    total_amount: float
    effective_rate_per_kwh: float
    billing_months: int
    is_estimate: bool
    lines: list[dict[str, Any]]
    warnings: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        labels = season_label(self.season)
        return {
            "plan_id": self.plan_id,
            "plan_name_en": self.plan_name_en,
            "plan_name_zh": self.plan_name_zh,
            "plan_type": self.plan_type,
            "season": self.season,
            "season_label_en": labels["label_en"],
            "season_label_zh": labels["label_zh"],
            "billing_months": self.billing_months,
            "consumption_kwh": _round(self.consumption_kwh, 3),
            "total_amount": _round(self.total_amount),
            "total_amount_rounded": int(round(self.total_amount)),
            "currency": "TWD",
            "effective_rate_per_kwh": _round(self.effective_rate_per_kwh, 4),
            "lines": self.lines,
            "warnings": self.warnings,
            "is_estimate": self.is_estimate,
        }


def _calculate_tiered(
    plan: Mapping[str, Any],
    consumption_kwh: float,
    season: str,
    months: int,
) -> tuple[list[dict[str, Any]], float, list[dict[str, Any]]]:
    season_data = plan["seasons"][season]
    tiers = season_data["tiers"]
    warnings: list[dict[str, Any]] = []

    per_period = bool(plan.get("threshold_semantics", "per_billing_period") == "per_billing_period")
    scale = months if per_period else 1

    lines: list[dict[str, Any]] = []
    total = 0.0
    lower = 0.0
    remaining = consumption_kwh

    for tier in tiers:
        if remaining <= 0 and consumption_kwh > 0:
            break
        ceiling = tier["up_to_kwh"]
        # Tier ceilings are scaled by the number of billed months.
        upper = float(ceiling) * scale if ceiling is not None else math.inf
        span = upper - lower
        used = min(remaining, span) if math.isfinite(span) else remaining
        if used < 0:
            used = 0.0
        if used == 0 and span <= 0:
            lower = upper
            continue
        if used == 0 and lines:
            # Zero consumption: emit one illustrative row for the first tier, then stop.
            break
        amount = used * float(tier["rate"])
        total += amount
        lines.append(
            {
                "tier_index": tier["index"],
                "label_zh": tier.get("label_zh"),
                "range_from_kwh": _round(lower, 3),
                "range_to_kwh": None if ceiling is None else _round(upper, 3),
                "rate_per_kwh": float(tier["rate"]),
                "kwh_in_tier": _round(used, 4),
                "amount": _round(amount),
            }
        )
        remaining -= used
        if math.isfinite(upper):
            lower = upper

    if remaining > 0:
        # Only reachable if the last tier has a finite ceiling (data problem).
        warnings.append(
            {
                "code": "uncovered_consumption",
                "message_zh": f"有 {_round(remaining, 3)} kWh 超出最後一個級距上限，電價表可能已過時。",
                "message_en": f"{_round(remaining, 3)} kWh fell above the last tier ceiling; the tariff table may be out of date.",
            }
        )

    return lines, total, warnings


def _calculate_flat(
    plan: Mapping[str, Any],
    consumption_kwh: float,
    season: str,
) -> tuple[list[dict[str, Any]], float, list[dict[str, Any]]]:
    rate = plan["seasons"][season].get("rate", plan.get("rate"))
    if rate is None:
        raise TariffError("flat plan is missing a rate", code="tariff_file_malformed")
    amount = consumption_kwh * float(rate)
    lines = [
        {
            "tier_index": 1,
            "label_zh": "單一費率",
            "range_from_kwh": 0.0,
            "range_to_kwh": None,
            "rate_per_kwh": float(rate),
            "kwh_in_tier": _round(consumption_kwh, 4),
            "amount": _round(amount),
        }
    ]
    warnings: list[dict[str, Any]] = []
    typical = plan.get("typical_range")
    if typical:
        warnings.append(
            {
                "code": "landlord_resale_rate",
                "message_zh": (
                    "這是房東的單一費率轉售價，不是台電的累進級距。租屋常見行情約 "
                    f"{typical[0]}-{typical[1]} 元/度，通常高於台電住宅累進電價。"
                ),
                "message_en": (
                    "This is a flat per-kWh resale price, not a Taipower tier. Landlords of rented "
                    f"rooms usually charge {typical[0]}-{typical[1]} TWD/kWh, which is normally more "
                    "expensive than the progressive Taipower rate."
                ),
            }
        )
    return lines, amount, warnings


def _calculate_time_of_use(
    plan: Mapping[str, Any],
    consumption_kwh: float,
    season: str,
    peak_share: float,
) -> tuple[list[dict[str, Any]], float, list[dict[str, Any]]]:
    if not 0.0 <= peak_share <= 1.0:
        raise TariffError("peak_share must be between 0 and 1", code="invalid_peak_share")
    season_data = plan["seasons"][season]
    peak_rate = float(season_data["peak"])
    off_peak_rate = float(season_data["off_peak"])

    peak_kwh = consumption_kwh * peak_share
    off_peak_kwh = consumption_kwh - peak_kwh

    lines = [
        {
            "tier_index": 1,
            "label_zh": "尖峰時段",
            "range_from_kwh": None,
            "range_to_kwh": None,
            "rate_per_kwh": peak_rate,
            "kwh_in_tier": _round(peak_kwh, 4),
            "amount": _round(peak_kwh * peak_rate),
        },
        {
            "tier_index": 2,
            "label_zh": "離峰時段",
            "range_from_kwh": None,
            "range_to_kwh": None,
            "rate_per_kwh": off_peak_rate,
            "kwh_in_tier": _round(off_peak_kwh, 4),
            "amount": _round(off_peak_kwh * off_peak_rate),
        },
    ]
    total = peak_kwh * peak_rate + off_peak_kwh * off_peak_rate
    warnings = [
        {
            "code": "tou_simplified",
            "message_zh": plan.get(
                "estimate_note",
                "時間電價為簡化估算，實際費率會依用電契約與尖離峰時段而不同。",
            ),
            "message_en": plan.get(
                "estimate_note",
                "Time-of-use estimate is simplified; actual rates depend on the electricity contract.",
            ),
        }
    ]
    return lines, total, warnings

def calculate_bill(
    consumption_kwh: float,
    *,
    plan_id: str | None = None,
    month: int | None = None,
    season: str | None = None,
    billing_period: str | None = "monthly",
    billing_months: int | None = None,
    peak_share: float = 0.5,
    tariffs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate an electricity bill for a consumption amount.

    Parameters
    ----------
    consumption_kwh:
        Energy for one billing period (or one month when ``billing_period`` is
        ``"monthly"``).
    plan_id:
        Tariff plan id; defaults to :func:`load_tariffs`'s ``default_plan_id``.
    month:
        Calendar month (1-12) used to pick summer / non-summer prices.
    season:
        Force ``"summer"`` or ``"non_summer"`` instead of deriving it from ``month``.
    billing_period / billing_months:
        How many months the amount covers. Tier ceilings are multiplied by this.
    """

    value = _validate_consumption(consumption_kwh)
    data = tariffs or load_tariffs()
    plan = get_plan(plan_id) if tariffs is None else _plan_from(data, plan_id)

    if season is not None:
        if season not in VALID_SEASONS:
            raise TariffError(
                f"season must be one of {', '.join(VALID_SEASONS)}", code="invalid_season"
            )
        resolved_season = season
    else:
        resolved_season = resolve_season(month)

    months = _period_months(billing_period, billing_months)
    _enforce_period_support(plan, months)
    plan_type = plan.get("type")

    if plan_type == "tiered":
        lines, total, warnings = _calculate_tiered(plan, value, resolved_season, months)
    elif plan_type == "flat":
        lines, total, warnings = _calculate_flat(plan, value, resolved_season)
    elif plan_type == "time_of_use":
        lines, total, warnings = _calculate_time_of_use(
            plan, value, resolved_season, peak_share
        )
    else:
        raise TariffError(f"unsupported plan type '{plan_type}'", code="unsupported_plan_type")

    if value <= 0:
        # Keep the response shape stable for the frontend: a zero-usage bill still
        # reports the rate that would have applied, with 0 kWh and 0 TWD.
        warnings.append(
            {
                "code": "no_consumption",
                "message_zh": "用電量為 0，因此電費為 0 元；以下級距僅供對照費率。",
                "message_en": "Consumption is 0, so the bill is 0 TWD; the tiers below only show the applicable rates.",
            }
        )
    else:
        warnings.append(
            {
                "code": "estimate_only",
                "message_zh": (
                    "此為依 VoltSpace 電價表計算的估算值。實際帳單還包含計費期間、"
                    "分攤方式，以及房東可能採用的轉售費率。"
                ),
                "message_en": (
                    "This is an estimate based on the VoltSpace tariff table. The real bill also "
                    "includes metering, proration and possibly a landlord's resale price."
                ),
            }
        )

    bill = BillBreakdown(
        plan_id=plan["id"],
        plan_name_en=plan.get("name_en"),
        plan_name_zh=plan.get("name_zh"),
        plan_type=str(plan_type),
        season=resolved_season,
        consumption_kwh=value,
        total_amount=total,
        effective_rate_per_kwh=(total / value) if value > 0 else 0.0,
        billing_months=months,
        is_estimate=bool(plan.get("is_estimate", False)),
        lines=lines,
        warnings=warnings,
    )
    return bill.as_dict()


def _plan_from(data: Mapping[str, Any], plan_id: str | None) -> dict[str, Any]:
    resolved = plan_id or data.get("default_plan_id")
    plans = data["plans"]
    if resolved not in plans:
        raise TariffError(
            f"unknown tariff plan '{resolved}'. Available: {', '.join(sorted(plans))}",
            code="unknown_plan",
        )
    return plans[resolved]


def compare_plans(
    consumption_kwh: float,
    *,
    month: int | None = None,
    billing_period: str = "monthly",
    peak_share: float = 0.5,
) -> dict[str, Any]:
    """Estimate the same consumption under every available plan, cheapest first."""

    data = load_tariffs()
    results = [
        calculate_bill(
            consumption_kwh,
            plan_id=plan_id,
            month=month,
            billing_period=billing_period,
            peak_share=peak_share,
        )
        for plan_id in data["plans"]
    ]
    results.sort(key=lambda item: item["total_amount"])
    return {
        "consumption_kwh": _round(float(consumption_kwh), 3),
        "cheapest_plan_id": results[0]["plan_id"] if results else None,
        "plans": results,
    }


def annual_seasonal_estimate(
    monthly_kwh: float,
    *,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Estimate a full year: 4 summer months + 8 non-summer months."""

    summer = calculate_bill(monthly_kwh, plan_id=plan_id, season=SUMMER, billing_period="monthly")
    non_summer = calculate_bill(
        monthly_kwh, plan_id=plan_id, season=NON_SUMMER, billing_period="monthly"
    )
    annual = summer["total_amount"] * 4 + non_summer["total_amount"] * 8
    return {
        "monthly_kwh": _round(float(monthly_kwh), 3),
        "summer_monthly_amount": summer["total_amount"],
        "non_summer_monthly_amount": non_summer["total_amount"],
        "annual_amount": _round(annual),
        "annual_amount_rounded": int(round(annual)),
        "average_monthly_amount": _round(annual / 12),
        "currency": "TWD",
        "summer_months": 4,
        "non_summer_months": 8,
    }
