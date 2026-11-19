"""Scenario simulation: compare a baseline household against a modified one.

Contract
--------
The simulator **never mutates the caller's data**. Appliance records are copied into
fresh dictionaries before any change is applied, and the result reports both the
baseline and the modified household so the frontend can show a before/after table.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from ..calculators.consumption import (
    ValidationError,
    calculate_consumption,
    validate_appliance,
)
from ..calculators.electricity_bill import calculate_bill
from ..calculators.load_estimator import estimate_load

# Change types a scenario may apply to one appliance.
SUPPORTED_CHANGES = (
    "hours_per_day",
    "power_watts",
    "days_per_month",
    "quantity",
    "replace_with",
)


class SimulationError(ValueError):
    def __init__(self, message: str, *, code: str = "simulation_error") -> None:
        super().__init__(message)
        self.code = code


def _snapshot(appliances: Sequence[Any]) -> list[dict[str, Any]]:
    """Deep-copy appliances into plain dicts (the non-mutation guarantee)."""

    snapshot: list[dict[str, Any]] = []
    for raw in appliances:
        if isinstance(raw, Mapping):
            record = copy.deepcopy(dict(raw))
        else:
            record = copy.deepcopy(dict(raw.__dict__))
        record.setdefault("days_per_month", 30)
        record.setdefault("quantity", 1)
        record.setdefault("voltage", 110.0)
        snapshot.append(record)
    return snapshot


def _identify(record: Mapping[str, Any], fallback: str) -> str:
    return str(record.get("appliance_id") or record.get("name") or fallback)


def _apply_change(
    record: dict[str, Any],
    change: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a NEW record with the change applied; ``record`` is left untouched."""

    result = copy.deepcopy(record)
    field = change.get("field")
    if field not in SUPPORTED_CHANGES:
        raise SimulationError(
            f"unsupported change field '{field}'. Supported: {', '.join(SUPPORTED_CHANGES)}",
            code="unsupported_change_field",
        )

    if field == "replace_with":
        replacement = change.get("replacement") or {}
        if not isinstance(replacement, Mapping):
            raise SimulationError(
                "replacement must be an object", code="invalid_replacement"
            )
        # Callers such as Pydantic's ``model_dump()`` emit ``None`` for unset optional
        # fields, which means "not provided" here: keep the original value instead of
        # overwriting it with None.
        for key in ("name", "appliance_id"):
            if replacement.get(key) is not None:
                result[key] = replacement[key]

        if replacement.get("power_watts") is not None:
            result["power_watts"] = float(replacement["power_watts"])
        if replacement.get("voltage") is not None:
            result["voltage"] = float(replacement["voltage"])
        if replacement.get("power_factor") is not None:
            result["power_factor"] = float(replacement["power_factor"])
        # A purchase swap can also come with a new usage habit.
        if replacement.get("hours_per_day") is not None:
            result["hours_per_day"] = float(replacement["hours_per_day"])
        if replacement.get("days_per_month") is not None:
            result["days_per_month"] = int(replacement["days_per_month"])
        if replacement.get("quantity") is not None:
            result["quantity"] = int(replacement["quantity"])

        # Remember the pre-swap identity so the before/after table can still pair this
        # record with its baseline row even when the replacement renames the appliance.
        result["replaced_from"] = copy.deepcopy(record)
        result["replacement_label"] = replacement.get("label") or replacement.get("name")
        return result

    if "value" not in change:
        raise SimulationError(
            f"change on field '{field}' requires a 'value'", code="missing_change_value"
        )
    value = change["value"]
    if field in ("hours_per_day", "power_watts"):
        result[field] = float(value)
    else:
        result[field] = int(value)
    return result


def simulate(
    appliances: Sequence[Any],
    changes: Sequence[Mapping[str, Any]],
    *,
    month: int | None = None,
    plan_id: str | None = None,
    billing_period: str = "monthly",
    billing_months: int | None = None,
    load_limit_amps: float | None = None,
    baseline_override_kwh: float | None = None,
) -> dict[str, Any]:
    """Compare baseline vs. modified household consumption, cost and load.

    Parameters
    ----------
    appliances:
        The user's saved appliances. They are copied and never modified.
    changes:
        A list of ``{"appliance_id" | "name", "field", "value" | "replacement"}``
        operations. ``field`` is one of :data:`SUPPORTED_CHANGES`.
    month:
        Calendar month used for the season (1-12). If omitted, ``billing_period``
        still applies and the non-summer season is used.
    billing_period / billing_months:
        Forwarded to the bill calculator so both sides of the comparison are priced
        over the same billing period. ``billing_months`` wins when both are given.
    baseline_override_kwh:
        Optional; when Member B already knows the user's real metered baseline it can
        be supplied instead of the value derived from the appliance list.
    """

    # Take ONE snapshot of the caller's data, then let the modified side work on a copy
    # of it. ``_apply_change`` deep-copies each record it edits, so the baseline and the
    # caller's own objects stay untouched (see TestNonMutation).
    baseline_records = _snapshot(appliances)
    modified_records = [copy.deepcopy(record) for record in baseline_records]

    # Validate the baseline before doing anything else.
    for record in baseline_records:
        try:
            validate_appliance(record)
        except ValidationError as exc:
            raise SimulationError(
                f"invalid baseline appliance '{record.get('name')}': {exc}", code=exc.code
            ) from exc

    # --- Build the modified household -----------------------------------------
    applied: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for change in changes:
        target = change.get("appliance_id") or change.get("name")
        if target is None:
            raise SimulationError(
                "each change needs 'appliance_id' or 'name'", code="missing_change_target"
            )
        index = next(
            (
                position
                for position, record in enumerate(modified_records)
                if _identify(record, str(position)) == str(target)
                or str(record.get("name")) == str(target)
            ),
            None,
        )
        if index is None:
            unmatched.append({"target": str(target), "field": change.get("field")})
            continue

        before = copy.deepcopy(modified_records[index])
        after = _apply_change(modified_records[index], change)
        try:
            validate_appliance(after)
        except ValidationError as exc:
            raise SimulationError(
                f"change on '{target}' produces an invalid appliance: {exc}", code=exc.code
            ) from exc
        modified_records[index] = after

        renamed = after.get("name") != before.get("name")
        applied.append(
            {
                # Identified by the original appliance so the entry lines up with
                # ``comparison_table``; a rename is reported in ``new_name``.
                "appliance": str(before.get("name")),
                "new_name": str(after.get("name")) if renamed else None,
                "appliance_id": before.get("appliance_id") or after.get("appliance_id"),
                "field": change.get("field"),
                "before": _comparable(before, change.get("field")),
                "after": _comparable(after, change.get("field")),
                "label_zh": change.get("label_zh"),
            }
        )

    if unmatched:
        raise SimulationError(
            "these changes did not match any appliance: "
            + ", ".join(item["target"] for item in unmatched),
            code="appliance_not_found",
        )

    # --- Calculate both sides --------------------------------------------------
    baseline = calculate_consumption(baseline_records)
    modified = calculate_consumption(modified_records)

    baseline_kwh = (
        float(baseline_override_kwh)
        if baseline_override_kwh is not None
        else float(baseline["total_monthly_kwh"])
    )
    modified_kwh = float(modified["total_monthly_kwh"])

    baseline_bill = calculate_bill(
        baseline_kwh,
        plan_id=plan_id,
        month=month,
        billing_period=billing_period,
        billing_months=billing_months,
    )
    modified_bill = calculate_bill(
        modified_kwh,
        plan_id=plan_id,
        month=month,
        billing_period=billing_period,
        billing_months=billing_months,
    )

    # Per-appliance deltas, matched by name (order-independent).
    deltas = _appliance_deltas(baseline["appliances"], modified["appliances"])

    saved_kwh = baseline_kwh - modified_kwh
    saved_amount = baseline_bill["total_amount"] - modified_bill["total_amount"]

    result: dict[str, Any] = {
        "currency": "TWD",
        "month": month,
        "plan_id": baseline_bill["plan_id"],
        "billing_period": billing_period,
        "billing_months": baseline_bill["billing_months"],
        "baseline": {
            "total_monthly_kwh": round(baseline_kwh, 3),
            "estimated_bill_twd": baseline_bill["total_amount"],
            "estimated_bill_rounded_twd": baseline_bill["total_amount_rounded"],
            "effective_rate_per_kwh": baseline_bill["effective_rate_per_kwh"],
            "appliance_count": baseline["count"],
            "appliances": baseline["appliances"],
            "bill_lines": baseline_bill["lines"],
        },
        "modified": {
            "total_monthly_kwh": round(modified_kwh, 3),
            "estimated_bill_twd": modified_bill["total_amount"],
            "estimated_bill_rounded_twd": modified_bill["total_amount_rounded"],
            "effective_rate_per_kwh": modified_bill["effective_rate_per_kwh"],
            "appliance_count": modified["count"],
            "appliances": modified["appliances"],
            "bill_lines": modified_bill["lines"],
        },
        "delta": {
            "saved_kwh": round(saved_kwh, 3),
            "saved_amount_twd": round(saved_amount, 2),
            "saved_amount_rounded_twd": int(round(saved_amount)),
            "saved_percent_of_kwh": round(
                (saved_kwh / baseline_kwh * 100) if baseline_kwh > 0 else 0.0, 2
            ),
            "saved_percent_of_amount": round(
                (saved_amount / baseline_bill["total_amount"] * 100)
                if baseline_bill["total_amount"] > 0
                else 0.0,
                2,
            ),
            "annual_saved_amount_twd": round(saved_amount * 12, 2),
            "is_saving": saved_kwh > 0,
        },
        "comparison_table": [
            {
                "appliance": delta["appliance"],
                "baseline_kwh": delta["baseline_kwh"],
                "modified_kwh": delta["modified_kwh"],
                "saved_kwh": delta["saved_kwh"],
                "percent_change": delta["percent_change"],
                "status": delta["status"],
                "replaced_by": delta["replaced_by"],
                "replacement_label": delta["replacement_label"],
            }
            for delta in deltas
        ],
        "appliance_deltas": deltas,
        "applied_changes": applied,
        "season_label_zh": baseline_bill["season_label_zh"],
        "notes": [
            "baseline 資料為原始家電資料的複本，模擬過程不會修改使用者已儲存的資料。",
            "所有金額與度數皆為估算值，實際帳單可能因級距、季節與房東收費方式而不同。",
        ],
    }

    # --- Optional load comparison ---------------------------------------------
    if load_limit_amps is not None:
        baseline_load = estimate_load(baseline_records, load_limit_amps=load_limit_amps)
        modified_load = estimate_load(modified_records, load_limit_amps=load_limit_amps)
        result["load"] = {
            "limit_amps": load_limit_amps,
            "baseline_current_amps": baseline_load["estimated_total_current_amps"],
            "modified_current_amps": modified_load["estimated_total_current_amps"],
            "current_change_amps": round(
                modified_load["estimated_total_current_amps"]
                - baseline_load["estimated_total_current_amps"],
                4,
            ),
            "baseline_verdict": baseline_load["verdict"],
            "modified_verdict": modified_load["verdict"],
            "baseline_severity": baseline_load["severity"],
            "modified_severity": modified_load["severity"],
            "disclaimer_zh": baseline_load["disclaimer_zh"],
        }

    return result


def _comparable(record: Mapping[str, Any], field: Any) -> Any:
    if field in (
        "power_watts",
        "hours_per_day",
        "days_per_month",
        "quantity",
        "voltage",
        "power_factor",
    ):
        return record.get(field)
    return {
        "name": record.get("name"),
        "power_watts": record.get("power_watts"),
        "hours_per_day": record.get("hours_per_day"),
        "days_per_month": record.get("days_per_month"),
        "quantity": record.get("quantity"),
    }


def _identity_keys(record: Mapping[str, Any]) -> list[str]:
    """Keys that identify a record, including the pre-swap identity if present.

    A ``replace_with`` change may rename the appliance, so ``replaced_from`` is
    consulted first to keep the baseline and modified rows paired. It is stored as the
    original name (the shape produced by ``calculate_consumption``), but the full
    original record is also accepted so either form works.
    """

    keys: list[str] = []
    origin = record.get("replaced_from")
    if isinstance(origin, Mapping):
        for value in (origin.get("appliance_id"), origin.get("name")):
            if value:
                keys.append(str(value))
    elif origin:
        keys.append(str(origin))
    for value in (record.get("appliance_id"), record.get("name")):
        if value:
            keys.append(str(value))
    return keys


def _appliance_deltas(
    baseline_appliances: Sequence[Mapping[str, Any]],
    modified_appliances: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Match appliances between the two households and report per-appliance deltas.

    Matching happens in two passes so that duplicate names behave sensibly:

    1. by ``appliance_id`` (unique, the normal case), then
    2. by ``name``, but each modified record may be consumed only once. Without this,
       two appliances sharing a name would both be compared against the same record.

    Each modified record also exposes the identity it replaced (``replaced_from``), so a
    swap that renames the appliance still pairs with its baseline row.
    """

    # Pass 1: unique identifiers, including any identity recorded before a swap.
    unclaimed_modified = list(range(len(modified_appliances)))
    by_key: dict[str, int] = {}
    for position, record in enumerate(modified_appliances):
        for key in _identity_keys(record):
            by_key.setdefault(key, position)

    matched: dict[int, int] = {}  # baseline position -> modified position
    unresolved: list[int] = []
    for position, record in enumerate(baseline_appliances):
        target = None
        for key in _identity_keys(record):
            if key in by_key:
                target = by_key[key]
                break
        if target is not None and target in unclaimed_modified:
            matched[position] = target
            unclaimed_modified.remove(target)
        else:
            unresolved.append(position)

    # Pass 2: fall back to the name, claiming each modified record at most once.
    for position in unresolved:
        name = str(baseline_appliances[position].get("name") or "")
        if not name:
            continue
        for target in list(unclaimed_modified):
            candidates = [str(modified_appliances[target].get("name") or "")]
            origin = modified_appliances[target].get("replaced_from")
            if isinstance(origin, Mapping):
                candidates.append(str(origin.get("name") or ""))
            if name in candidates:
                matched[position] = target
                unclaimed_modified.remove(target)
                break

    deltas: list[dict[str, Any]] = []
    for position, record in enumerate(baseline_appliances):
        target = matched.get(position)
        match = modified_appliances[target] if target is not None else None
        baseline_kwh = float(record.get("monthly_kwh", 0.0))
        modified_kwh = float(match.get("monthly_kwh", 0.0)) if match else 0.0
        # The row is always identified by the ORIGINAL appliance so the comparison table
        # stays stable when a swap renames it; the new name is reported separately.
        replaced_by = None
        replacement_label = None
        if match is not None and match.get("replaced_from"):
            # ``replaced_from`` is the name of the appliance this record replaced.
            if match["replaced_from"] == record.get("name"):
                replacement_label = match.get("replacement_label")
                new_name = match.get("name")
                if new_name and new_name != record.get("name"):
                    replaced_by = new_name
        deltas.append(
            {
                "appliance": record.get("name"),
                "appliance_id": record.get("appliance_id"),
                "baseline_kwh": round(baseline_kwh, 3),
                "modified_kwh": round(modified_kwh, 3),
                "saved_kwh": round(baseline_kwh - modified_kwh, 3),
                "percent_change": (
                    round((modified_kwh - baseline_kwh) / baseline_kwh * 100, 2)
                    if baseline_kwh > 0
                    else None
                ),
                "status": (
                    "new"
                    if match is None
                    else ("changed" if abs(baseline_kwh - modified_kwh) > 1e-9 else "unchanged")
                ),
                "replaced_by": replaced_by,
                "replacement_label": replacement_label,
            }
        )

    # Appliances that only exist after the change (a simulated purchase).
    for position in unclaimed_modified:
        record = modified_appliances[position]
        modified_kwh = float(record.get("monthly_kwh", 0.0))
        deltas.append(
            {
                "appliance": record.get("name"),
                "appliance_id": record.get("appliance_id"),
                "baseline_kwh": 0.0,
                "modified_kwh": round(modified_kwh, 3),
                "saved_kwh": round(-modified_kwh, 3),
                "percent_change": None,
                "status": "added",
                "replaced_by": None,
                "replacement_label": None,
            }
        )

    return deltas


def what_if_reduction(
    appliances: Sequence[Any],
    *,
    reduction_percent: float,
    month: int | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Quick scenario: "what if the whole household used N% less electricity?"."""

    if not 0 <= reduction_percent <= 100:
        raise SimulationError(
            "reduction_percent must be between 0 and 100", code="invalid_reduction_percent"
        )
    records = _snapshot(appliances)
    baseline = calculate_consumption(records)
    baseline_kwh = float(baseline["total_monthly_kwh"])
    modified_kwh = baseline_kwh * (1 - reduction_percent / 100.0)

    baseline_bill = calculate_bill(baseline_kwh, plan_id=plan_id, month=month)
    modified_bill = calculate_bill(modified_kwh, plan_id=plan_id, month=month)
    saved_amount = baseline_bill["total_amount"] - modified_bill["total_amount"]

    return {
        "currency": "TWD",
        "reduction_percent": reduction_percent,
        "baseline_total_monthly_kwh": round(baseline_kwh, 3),
        "modified_total_monthly_kwh": round(modified_kwh, 3),
        "baseline_estimated_bill_twd": baseline_bill["total_amount"],
        "modified_estimated_bill_twd": modified_bill["total_amount"],
        "saved_kwh": round(baseline_kwh - modified_kwh, 3),
        "saved_amount_twd": round(saved_amount, 2),
        "annual_saved_amount_twd": round(saved_amount * 12, 2),
        "note_zh": (
            "此為整體用電量等比縮減的快速試算。因為電費是累進級距，"
            "省下的金額比例通常會略高於省下的度數比例。"
        ),
    }
