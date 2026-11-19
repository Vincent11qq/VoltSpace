"""Monthly electricity consumption calculation.

Formula
-------
    daily_kwh   = power_watts / 1000 * hours_per_day
    monthly_kwh = daily_kwh * days_per_month * quantity

The module is deliberately free of any validation *framework*: it raises
``ValueError`` with a machine readable code so that both Pydantic (API layer) and
plain unit tests can use the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --- Validation limits -------------------------------------------------------
MIN_POWER_WATTS = 0.1
MAX_POWER_WATTS = 100_000.0
MIN_HOURS_PER_DAY = 0.0
MAX_HOURS_PER_DAY = 24.0
MIN_DAYS_PER_MONTH = 0
MAX_DAYS_PER_MONTH = 31
MIN_QUANTITY = 1
MAX_QUANTITY = 999

# Useful equivalence for the frontend: one 60 W bulb for 1000 hours = 60 kWh.
WATTS_PER_KILOWATT = 1000.0


class ValidationError(ValueError):
    """Raised when an appliance record is physically implausible."""

    def __init__(self, message: str, *, code: str, field_name: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field_name = field_name

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.field_name:
            payload["field"] = self.field_name
        return payload


@dataclass(frozen=True)
class ApplianceInput:
    """One appliance the user owns, with its usage habit."""

    name: str
    power_watts: float
    hours_per_day: float
    days_per_month: int = 30
    quantity: int = 1
    voltage: float = 110.0
    power_factor: float = 1.0
    appliance_id: str | None = None
    category: str | None = None

    def validate(self) -> None:
        validate_appliance(self)


@dataclass
class MonthlyConsumption:
    """Result of the consumption calculation for a single appliance."""

    name: str
    appliance_id: str | None
    category: str | None
    power_watts: float
    hours_per_day: float
    days_per_month: int
    quantity: int
    daily_kwh: float
    monthly_kwh: float
    share_of_total_percent: float | None = None
    replacement_label: str | None = None
    replaced_from: str | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "appliance_id": self.appliance_id,
            "name": self.name,
            "category": self.category,
            "power_watts": _round(self.power_watts, 4),
            "hours_per_day": _round(self.hours_per_day, 4),
            "days_per_month": self.days_per_month,
            "quantity": self.quantity,
            "daily_kwh": _round(self.daily_kwh, 4),
            "monthly_kwh": _round(self.monthly_kwh, 4),
            "share_of_total_percent": (
                _round(self.share_of_total_percent, 2)
                if self.share_of_total_percent is not None
                else None
            ),
            "replacement_label": self.replacement_label,
            "replaced_from": self.replaced_from,
            "warnings": self.warnings,
        }


def _round(value: float, digits: int) -> float:
    return round(value + 0.0, digits)


def _require_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(
            f"{field_name} must be a number, got {type(value).__name__}",
            code="not_a_number",
            field_name=field_name,
        )
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError(
            f"{field_name} must be a finite number", code="not_finite", field_name=field_name
        )
    return number


def validate_appliance(appliance: ApplianceInput | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate one appliance record.

    Returns a list of non-fatal warnings (plausible but suspicious values) and
    raises :class:`ValidationError` for values that cannot be calculated at all.
    """

    data: Mapping[str, Any]
    if isinstance(appliance, ApplianceInput):
        data = _as_raw(appliance)
    elif isinstance(appliance, Mapping):
        data = appliance
    else:
        raise ValidationError(
            f"appliance must be an object, got {type(appliance).__name__}",
            code="not_an_object",
            field_name="appliance",
        )
    warnings: list[dict[str, Any]] = []

    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise ValidationError("name must be a string", code="not_a_string", field_name="name")

    power = _require_number(data.get("power_watts"), field_name="power_watts")
    if power <= 0:
        raise ValidationError(
            "power_watts must be greater than 0", code="power_not_positive", field_name="power_watts"
        )
    if power < MIN_POWER_WATTS:
        raise ValidationError(
            f"power_watts is below the supported minimum of {MIN_POWER_WATTS}W",
            code="power_too_small",
            field_name="power_watts",
        )
    if power > MAX_POWER_WATTS:
        raise ValidationError(
            f"power_watts exceeds the supported maximum of {MAX_POWER_WATTS}W",
            code="power_too_large",
            field_name="power_watts",
        )
    if power > 20_000:
        warnings.append(
            {
                "code": "very_high_power",
                "field": "power_watts",
                "message_zh": f"{power:g}W 對家用電器來說偏高，請再確認電器銘牌上的額定功率。",
                "message_en": f"{power:g}W is unusually high for a household appliance; please double check the nameplate.",
            }
        )

    hours = _require_number(data.get("hours_per_day"), field_name="hours_per_day")
    if hours < MIN_HOURS_PER_DAY:
        raise ValidationError(
            "hours_per_day cannot be negative", code="hours_negative", field_name="hours_per_day"
        )
    if hours > MAX_HOURS_PER_DAY:
        raise ValidationError(
            f"hours_per_day cannot exceed {MAX_HOURS_PER_DAY}",
            code="hours_too_large",
            field_name="hours_per_day",
        )
    if hours == 0:
        warnings.append(
            {
                "code": "no_usage",
                "field": "hours_per_day",
                "message_zh": "每日使用時數為 0，這台家電目前不會產生用電量。",
                "message_en": "hours_per_day is 0, so this appliance contributes no consumption.",
            }
        )
    elif hours >= 20:
        warnings.append(
            {
                "code": "near_continuous_use",
                "field": "hours_per_day",
                "message_zh": f"每日 {hours:g} 小時幾乎是全天運轉，建議再用負載估算確認用電安全。",
                "message_en": f"{hours:g} hours/day means this appliance runs almost continuously; use the load estimate to confirm it is safe.",
            }
        )

    days = _require_number(_field(data, "days_per_month", 30), field_name="days_per_month")
    if days != int(days):
        raise ValidationError(
            "days_per_month must be a whole number", code="days_not_integer", field_name="days_per_month"
        )
    days = int(days)
    if days < MIN_DAYS_PER_MONTH or days > MAX_DAYS_PER_MONTH:
        raise ValidationError(
            f"days_per_month must be between {MIN_DAYS_PER_MONTH} and {MAX_DAYS_PER_MONTH}",
            code="days_out_of_range",
            field_name="days_per_month",
        )

    quantity = _require_number(_field(data, "quantity", 1), field_name="quantity")
    if quantity != int(quantity):
        raise ValidationError(
            "quantity must be a whole number", code="quantity_not_integer", field_name="quantity"
        )
    quantity = int(quantity)
    if quantity < MIN_QUANTITY or quantity > MAX_QUANTITY:
        raise ValidationError(
            f"quantity must be between {MIN_QUANTITY} and {MAX_QUANTITY}",
            code="quantity_out_of_range",
            field_name="quantity",
        )

    voltage = _require_number(_field(data, "voltage", 110.0), field_name="voltage")
    if voltage <= 0:
        raise ValidationError(
            "voltage must be greater than 0", code="voltage_not_positive", field_name="voltage"
        )

    # Only the load estimate uses the power factor, but validating it here keeps one
    # set of domain rules for every caller (API and tests).
    power_factor = _require_number(_field(data, "power_factor", 1.0), field_name="power_factor")
    if not 0.1 <= power_factor <= 1.0:
        raise ValidationError(
            "power_factor must be between 0.1 and 1.0",
            code="power_factor_out_of_range",
            field_name="power_factor",
        )

    return warnings


def daily_energy_kwh(
    power_watts: float,
    hours_per_day: float,
    quantity: int = 1,
) -> float:
    """Return kWh consumed in one day."""

    return (power_watts / WATTS_PER_KILOWATT) * hours_per_day * quantity


def monthly_energy_kwh(
    power_watts: float,
    hours_per_day: float,
    days_per_month: int = 30,
    quantity: int = 1,
) -> float:
    """Return kWh consumed in one month."""

    return daily_energy_kwh(power_watts, hours_per_day, quantity) * days_per_month


def _field(data: Mapping[str, Any], key: str, default: Any) -> Any:
    """Read an optional field, treating an explicit ``None`` like 'not provided'."""

    value = data.get(key, default)
    return default if value is None else value


def _as_raw(item: ApplianceInput | Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the raw field mapping so validation sees exactly what the caller sent."""

    if isinstance(item, ApplianceInput):
        return {
            "name": item.name,
            "power_watts": item.power_watts,
            "hours_per_day": item.hours_per_day,
            "days_per_month": item.days_per_month,
            "quantity": item.quantity,
            "voltage": item.voltage,
            "power_factor": item.power_factor,
            "appliance_id": item.appliance_id,
            "category": item.category,
        }
    return item


def _as_appliance(raw: Mapping[str, Any]) -> ApplianceInput:
    """Build the dataclass from an already-validated mapping."""

    return ApplianceInput(
        name=raw.get("name") or "appliance",
        power_watts=float(raw["power_watts"]),
        hours_per_day=float(raw["hours_per_day"]),
        days_per_month=int(_field(raw, "days_per_month", 30)),
        quantity=int(_field(raw, "quantity", 1)),
        voltage=float(_field(raw, "voltage", 110.0)),
        power_factor=float(_field(raw, "power_factor", 1.0)),
        appliance_id=raw.get("appliance_id"),
        category=raw.get("category"),
    )


def calculate_consumption(
    appliances: ApplianceInput | Mapping[str, Any] | Sequence[ApplianceInput | Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate monthly consumption for one appliance or a whole household.

    Returns a JSON-ready dictionary containing ``total_monthly_kwh`` plus a
    per-appliance breakdown with each appliance's share of the total.
    """

    items: Iterable[ApplianceInput | Mapping[str, Any]]
    if isinstance(appliances, (ApplianceInput, Mapping)):
        items = [appliances]
    else:
        items = appliances

    breakdown: list[MonthlyConsumption] = []
    for item in items:
        # Validate the caller's raw values (missing keys, wrong types, bad ranges)
        # BEFORE converting, so every rejection surfaces as a typed ValidationError.
        raw = _as_raw(item)
        warnings = validate_appliance(raw)
        appliance = _as_appliance(raw)
        monthly = monthly_energy_kwh(
            appliance.power_watts,
            appliance.hours_per_day,
            appliance.days_per_month,
            appliance.quantity,
        )
        breakdown.append(
            MonthlyConsumption(
                name=appliance.name,
                appliance_id=appliance.appliance_id,
                category=appliance.category,
                power_watts=appliance.power_watts,
                hours_per_day=appliance.hours_per_day,
                days_per_month=appliance.days_per_month,
                quantity=appliance.quantity,
                daily_kwh=daily_energy_kwh(
                    appliance.power_watts, appliance.hours_per_day, appliance.quantity
                ),
                monthly_kwh=monthly,
                replacement_label=raw.get("replacement_label"),
                replaced_from=(
                    (raw.get("replaced_from") or {}).get("name")
                    if isinstance(raw.get("replaced_from"), Mapping)
                    else None
                ),
                warnings=warnings,
            )
        )

    total = sum(entry.monthly_kwh for entry in breakdown)
    for entry in breakdown:
        entry.share_of_total_percent = (entry.monthly_kwh / total * 100.0) if total > 0 else 0.0

    ranked = sorted(breakdown, key=lambda entry: entry.monthly_kwh, reverse=True)
    return {
        "count": len(breakdown),
        "total_daily_kwh": _round(sum(entry.daily_kwh for entry in breakdown), 4),
        "total_monthly_kwh": _round(total, 4),
        "average_monthly_kwh_per_appliance": _round(total / len(breakdown), 4) if breakdown else 0.0,
        "appliances": [entry.as_dict() for entry in breakdown],
        "highest_consumption_appliance": ranked[0].name if ranked else None,
    }


def calculate_total_consumption(
    appliances: Sequence[ApplianceInput | Mapping[str, Any]],
) -> float:
    """Convenience helper returning only the household total in kWh."""

    return float(calculate_consumption(appliances)["total_monthly_kwh"])
