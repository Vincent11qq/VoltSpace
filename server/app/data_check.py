"""Integrity checks for the JSON data files.

The tariff table and the appliance catalogue drive every calculation, so a typo in
either should fail **at startup** with a precise message rather than silently
producing wrong bills for the first user who hits an endpoint.

``app.main`` runs :func:`validate_all` from its lifespan and aborts if it raises.
"""

from __future__ import annotations

from typing import Any, Mapping

from .calculators.electricity_bill import SUMMER, VALID_SEASONS, load_tariffs
from .services.recommendations import load_appliance_catalog

# Conditions the catalogue's rule engine understands (see
# ``app.services.recommendations._rule_matches``). A rule using anything else would be
# silently ignored, so it is rejected here instead.
SUPPORTED_RULE_CONDITIONS = frozenset(
    {
        "hours_per_day_gte",
        "hours_per_day_lte",
        "days_per_month_gte",
        "power_ratio_gte",
        "power_ratio_lte",
        "is_high_power",
        "is_always_on",
        "share_gte",
    }
)
SUPPORTED_PLAN_TYPES = frozenset({"tiered", "flat", "time_of_use"})


class DataIntegrityError(RuntimeError):
    """Raised when a data file is structurally valid JSON but semantically wrong."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise DataIntegrityError(message)


def validate_tariffs(data: Mapping[str, Any] | None = None) -> list[str]:
    """Validate the tariff table and return the plan ids found."""

    data = data if data is not None else load_tariffs()

    _check(
        isinstance(data.get("plans"), dict) and bool(data["plans"]),
        "tariffs: 'plans' must be a non-empty object",
    )
    default_plan = data.get("default_plan_id")
    _check(
        default_plan in data["plans"],
        f"tariffs: default_plan_id '{default_plan}' is not one of {sorted(data['plans'])}",
    )

    rules = data.get("season_rules") or {}
    for season in VALID_SEASONS:
        _check(season in rules, f"tariffs: season_rules is missing '{season}'")
    _check(
        rules[SUMMER]["label_zh"].strip() and rules[SUMMER]["label_en"].strip(),
        "tariffs: summer season label is empty",
    )

    for plan_id, plan in data["plans"].items():
        _check(plan.get("id") == plan_id, f"tariffs[{plan_id}]: 'id' must match its key")
        plan_type = plan.get("type")
        _check(
            plan_type in SUPPORTED_PLAN_TYPES,
            f"tariffs[{plan_id}]: unsupported type '{plan_type}' (expected {sorted(SUPPORTED_PLAN_TYPES)})",
        )
        _check(bool(plan.get("seasons")), f"tariffs[{plan_id}]: 'seasons' is required")

        for season in VALID_SEASONS:
            _check(season in plan["seasons"], f"tariffs[{plan_id}]: missing season '{season}'")

        if plan_type == "tiered":
            for season in VALID_SEASONS:
                tiers = plan["seasons"][season].get("tiers") or []
                _check(len(tiers) >= 1, f"tariffs[{plan_id}/{season}]: no tiers")
                previous = 0.0
                for position, tier in enumerate(tiers):
                    ceiling = tier.get("up_to_kwh")
                    rate = tier.get("rate")
                    _check(
                        isinstance(rate, (int, float)) and rate > 0,
                        f"tariffs[{plan_id}/{season}] tier {position}: rate must be > 0",
                    )
                    is_last = position == len(tiers) - 1
                    if is_last:
                        # The final tier must be open ended, otherwise consumption
                        # above the last ceiling would have no price at all.
                        _check(
                            ceiling is None,
                            f"tariffs[{plan_id}/{season}]: the last tier must have up_to_kwh=null",
                        )
                    else:
                        _check(
                            isinstance(ceiling, (int, float)) and ceiling > previous,
                            f"tariffs[{plan_id}/{season}] tier {position}: up_to_kwh must increase",
                        )
                        previous = float(ceiling)
        elif plan_type == "flat":
            for season in VALID_SEASONS:
                rate = plan["seasons"][season].get("rate", plan.get("rate"))
                _check(
                    isinstance(rate, (int, float)) and rate > 0,
                    f"tariffs[{plan_id}/{season}]: flat rate must be > 0",
                )
        else:  # time_of_use
            for season in VALID_SEASONS:
                season_data = plan["seasons"][season]
                for segment in ("peak", "off_peak"):
                    rate = season_data.get(segment)
                    _check(
                        isinstance(rate, (int, float)) and rate > 0,
                        f"tariffs[{plan_id}/{season}]: '{segment}' rate must be > 0",
                    )
                _check(
                    season_data["off_peak"] <= season_data["peak"],
                    f"tariffs[{plan_id}/{season}]: off-peak rate should not exceed the peak rate",
                )

    return sorted(data["plans"])


def validate_catalog(data: Mapping[str, Any] | None = None) -> int:
    """Validate the appliance catalogue and return the number of entries."""

    data = data if data is not None else load_appliance_catalog()

    defaults = data.get("defaults")
    _check(isinstance(defaults, dict), "appliances: 'defaults' must be an object")
    for key in ("voltage_v", "days_per_month", "power_factor"):
        _check(key in defaults, f"appliances: defaults.{key} is required")

    entries = data.get("appliances")
    _check(isinstance(entries, list) and bool(entries), "appliances: 'appliances' must be a non-empty list")

    keys: set[str] = set()
    for position, entry in enumerate(entries):
        label = entry.get("key") or f"#{position}"
        for field in ("key", "name_en", "name_zh", "category", "typical_power_watts"):
            _check(entry.get(field) is not None, f"appliances[{label}]: missing '{field}'")
        _check(entry["key"] not in keys, f"appliances: duplicate key '{entry['key']}'")
        keys.add(entry["key"])

        low, high = (entry.get("power_range_watts") or [None, None])[:2]
        typical = entry["typical_power_watts"]
        _check(
            isinstance(low, (int, float)) and isinstance(high, (int, float)) and low <= typical <= high,
            f"appliances[{label}]: typical_power_watts must lie within power_range_watts",
        )

        for rule in entry.get("rules", []):
            rule_id = str(rule.get("id") or "").strip()
            _check(bool(rule_id), f"appliances[{label}]: a rule is missing 'id'")
            for field in ("title_zh", "reason_zh", "suggestion_zh"):
                _check(
                    bool(str(rule.get(field, "")).strip()),
                    f"appliances[{label}] rule '{rule_id}': '{field}' is empty",
                )
            conditions = (rule.get("when") or {}).keys()
            _check(bool(conditions), f"appliances[{label}] rule '{rule_id}': 'when' is empty")
            unsupported = set(conditions) - SUPPORTED_RULE_CONDITIONS
            _check(
                not unsupported,
                f"appliances[{label}] rule '{rule_id}': unsupported condition(s) "
                f"{sorted(unsupported)}; supported: {sorted(SUPPORTED_RULE_CONDITIONS)}",
            )
            ratio = rule.get("reduction_ratio", 0)
            _check(
                isinstance(ratio, (int, float)) and 0 <= ratio <= 1,
                f"appliances[{label}] rule '{rule_id}': reduction_ratio must be within 0..1",
            )

        alternative = entry.get("efficient_alternative")
        if alternative is not None:
            _check(
                bool(alternative.get("label_zh")),
                f"appliances[{label}]: efficient_alternative.label_zh is required",
            )
            power = alternative.get("power_watts")
            _check(
                isinstance(power, (int, float)) and power > 0,
                f"appliances[{label}]: efficient_alternative.power_watts must be > 0",
            )

    return len(entries)


def validate_all() -> dict[str, Any]:
    """Run every check; raise :class:`DataIntegrityError` on the first problem."""

    plan_ids = validate_tariffs()
    catalog_count = validate_catalog()
    return {"plan_ids": plan_ids, "appliance_count": catalog_count}


def main() -> int:
    """CLI entry point: ``python -m app.data_check``."""

    try:
        summary = validate_all()
    except DataIntegrityError as exc:
        print(f"DATA INTEGRITY ERROR: {exc}")
        return 1
    print(f"tariffs OK: {', '.join(summary['plan_ids'])}")
    print(f"catalogue OK: {summary['appliance_count']} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
