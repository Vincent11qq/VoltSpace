"""Rule-based energy-saving recommendations.

No machine learning is involved: the service compares each appliance against a
catalogue of typical nameplate power and usage (``app/data/appliances.json``) and
applies declarative rules to produce an explanation, a concrete suggestion, and an
*estimated* saving.

Every saving is an estimate. The response therefore exposes the assumption
(``assumption_zh``) and a ``confidence`` level so the frontend never presents it as
a guaranteed amount.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..calculators.consumption import (
    ValidationError,
    daily_energy_kwh,
    monthly_energy_kwh,
    validate_appliance,
)
from ..calculators.electricity_bill import calculate_bill

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "appliances.json"

# An appliance is "high consumption" when it reaches this share of the household total.
HIGH_SHARE_THRESHOLD = 0.20
MEDIUM_SHARE_THRESHOLD = 0.10

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

# Whitespace, separators and brackets are ignored when comparing names, so
# "Air-Conditioner" and "air conditioner" resolve to the same catalogue entry.
_NORMALISE_PATTERN = re.compile(r"[\s_\-/()（）]+")


@lru_cache(maxsize=1)
def load_appliance_catalog() -> dict[str, Any]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"appliance catalogue not found: {DATA_FILE}")
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _catalog_index() -> dict[str, dict[str, Any]]:
    """Alias -> catalogue entry, built once and reused for every appliance.

    The index is immutable (the catalogue is a static data file), so caching it avoids
    rebuilding ~36 aliases on every lookup.
    """

    catalog = load_appliance_catalog()
    index: dict[str, dict[str, Any]] = {}
    for entry in catalog["appliances"]:
        for alias in (entry["key"], entry["name_en"], entry["name_zh"]):
            index[_normalise(alias)] = entry
    return index


@lru_cache(maxsize=2048)
def _normalise(value: str) -> str:
    return _NORMALISE_PATTERN.sub("", str(value).strip().lower())


@lru_cache(maxsize=1024)
def _best_alias(
    catalog_key: str | None,
    name_en: str | None,
    name: str | None,
    category: str | None,
) -> str | None:
    """Return the winning catalogue alias for these fields, or None.

    Cached on the *strings* (hashable) rather than on the returned entry, because the
    same appliance is matched more than once per request.
    """

    index = _catalog_index()

    # --- Pass 1: exact alias matches ------------------------------------------
    # Collect ALL exact matches instead of returning on the first, because a generic
    # category ("cooling") and a specific name ("冰箱") can both resolve exactly.
    exact: dict[str, dict[str, Any]] = {}
    for candidate in (catalog_key, name_en, name, category):
        if not candidate:
            continue
        alias = _normalise(candidate)
        if alias in index:
            exact[alias] = index[alias]

    # --- Pass 2: substring matches, longest alias wins -------------------------
    normalised_name = _normalise(name or "")
    fuzzy: dict[str, dict[str, Any]] = {}
    if normalised_name:
        for alias, entry in index.items():
            if len(alias) < 2:
                continue
            if alias in normalised_name or normalised_name in alias:
                fuzzy[alias] = entry

    # A specific match beats a generic one: prefer the longest matched alias, and treat
    # an exact match as more specific than a mere substring of the same length.
    combined: dict[str, dict[str, Any]] = dict(fuzzy)
    combined.update(exact)
    if not combined:
        return None

    return max(combined, key=lambda alias: (len(alias), 1 if alias in exact else 0))


def _match_reference(appliance: Mapping[str, Any]) -> dict[str, Any] | None:
    """Find the catalogue entry for an appliance, or None when nothing matches.

    All candidate aliases are scored together rather than returning on the first match,
    because the fields can disagree: a user may send ``name="電冰箱"`` (refrigerator)
    together with a generic English alias that would resolve to a different entry. A
    name that merely *contains* a catalogue alias is also considered, which matters a lot
    for Chinese input (``冰箱`` → refrigerator, ``電冰箱`` → refrigerator, ``小冰箱`` →
    refrigerator), so the substring pass must run even when an exact match already won
    for a different field.

    The longest matched alias wins, and an exact match breaks a length tie. This keeps
    ``"Bedroom air conditioner"`` resolving to ``air_conditioner``.
    """

    alias = _best_alias(
        appliance.get("catalog_key"),
        appliance.get("name_en"),
        appliance.get("name"),
        appliance.get("category"),
    )
    return None if alias is None else _catalog_index().get(alias)


def _rule_matches(rule: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    conditions = rule.get("when") or {}
    for condition, expected in conditions.items():
        if condition == "hours_per_day_gte":
            if not context["hours_per_day"] >= float(expected):
                return False
        elif condition == "hours_per_day_lte":
            if not context["hours_per_day"] <= float(expected):
                return False
        elif condition == "days_per_month_gte":
            if not context["days_per_month"] >= float(expected):
                return False
        elif condition == "power_ratio_gte":
            reference = context.get("reference_power_watts")
            if not reference or not (context["power_watts"] / reference) >= float(expected):
                return False
        elif condition == "power_ratio_lte":
            reference = context.get("reference_power_watts")
            if not reference or not (context["power_watts"] / reference) <= float(expected):
                return False
        elif condition == "is_high_power":
            if bool(context.get("is_high_power")) is not bool(expected):
                return False
        elif condition == "is_always_on":
            if bool(context.get("is_always_on")) is not bool(expected):
                return False
        elif condition == "share_gte":
            if not context["share"] >= float(expected):
                return False
        else:
            # Unknown condition: fail open rather than silently mis-applying a rule.
            return False
    return True


def _estimate_rule_saving(
    rule: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[float, str]:
    """Return ``(saved_kwh_per_month, assumption_zh)`` for one rule."""

    base_kwh = context["monthly_kwh"]

    cap_hours = rule.get("reduction_cap_hours")
    if cap_hours is not None:
        # Saving = removing a slice of the daily schedule, bounded by the cap.
        # The slice is taken as ``reduction_ratio`` of the current schedule, and can
        # never exceed either the cap or the current usage itself.
        planned_hours = context["hours_per_day"] * float(rule.get("reduction_ratio", 0.0))
        hours_saved = min(float(cap_hours), planned_hours, context["hours_per_day"])
        if hours_saved <= 0:
            return 0.0, "目前使用時數已低於建議值，無需調整。"
        saved_kwh = daily_energy_kwh(
            context["power_watts"], hours_saved, context.get("quantity", 1)
        ) * context["days_per_month"]
        assumption = (
            f"假設每日可減少 {hours_saved:.1f} 小時使用（原 {context['hours_per_day']:.1f} 小時），"
            f"每月 {context['days_per_month']} 天。"
        )
        return max(saved_kwh, 0.0), assumption

    ratio = float(rule.get("reduction_ratio", 0.0))
    saved_kwh = base_kwh * ratio
    assumption = f"假設可降低該電器 {ratio * 100:.0f}% 的用電量（以目前每月 {base_kwh:.1f} 度為基準）。"

    if rule.get("use_efficient_alternative"):
        alternative_power = context.get("alternative_power_watts")
        if alternative_power:
            new_kwh = monthly_energy_kwh(
                alternative_power,
                context["hours_per_day"],
                context["days_per_month"],
                context.get("quantity", 1),
            )
            if new_kwh < base_kwh:
                saved_kwh = base_kwh - new_kwh
                assumption = (
                    f"以同類高效率機種 {alternative_power:g}W 取代目前 {context['power_watts']:g}W，"
                    f"使用時數不變，每月可省 {saved_kwh:.1f} 度。"
                )

    return max(saved_kwh, 0.0), assumption


def _severity_from_share(share: float) -> str:
    if share >= HIGH_SHARE_THRESHOLD:
        return "high"
    if share >= MEDIUM_SHARE_THRESHOLD:
        return "medium"
    return "low"


def _build_recommendation(
    *,
    key: str,
    appliance_name: str,
    appliance_key: str,
    title_zh: str,
    reason_zh: str,
    suggestion_zh: str,
    saved_kwh: float,
    monthly_cost_saved: float,
    assumption_zh: str,
    priority: int,
    severity: str,
    confidence: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": key,
        "recommendation_key": f"{key}::{appliance_key}",
        "appliance": appliance_name,
        "appliance_key": appliance_key,
        "title_zh": title_zh,
        "reason_zh": reason_zh,
        "suggestion_zh": suggestion_zh,
        "estimated_monthly_saving_kwh": round(saved_kwh, 3),
        "estimated_monthly_saving_twd": round(monthly_cost_saved, 2),
        "estimated_annual_saving_twd": round(monthly_cost_saved * 12, 2),
        "assumption_zh": assumption_zh,
        "priority": priority,
        "severity": severity,
        "confidence": confidence,
    }
    if extra:
        payload.update(extra)
    return payload


def _blended_cost_per_kwh(total_kwh: float, month: int | None, plan_id: str | None) -> float:
    """Average TWD per kWh at this consumption level (so progressive tiers apply).

    Zero consumption still needs a rate to value a hypothetical saving, so bill a
    nominal 1 kWh instead of dividing by zero.
    """

    reference_kwh = total_kwh if total_kwh > 0 else 1.0
    bill = calculate_bill(reference_kwh, plan_id=plan_id, month=month)
    return bill["total_amount"] / reference_kwh


def generate_recommendations(
    appliances: Sequence[Any],
    *,
    month: int | None = None,
    plan_id: str | None = None,
    top_n: int | None = None,
    max_recommendations: int = 20,
) -> dict[str, Any]:
    """Produce ranked, rule-based energy-saving recommendations.

    Parameters
    ----------
    appliances:
        Household appliances with ``name``, ``power_watts``, ``hours_per_day``,
        ``days_per_month`` and optional ``quantity`` / ``voltage``.
    month:
        Selects the season so savings are valued at the right tariff.
    top_n:
        How many of the highest-consuming appliances to flag explicitly.
    """

    records: list[dict[str, Any]] = []
    for raw in appliances:
        record = dict(raw) if isinstance(raw, Mapping) else dict(raw.__dict__)
        try:
            warnings = validate_appliance(record)
        except ValidationError as exc:
            raise ValidationError(
                f"invalid appliance '{record.get('name')}': {exc}",
                code=exc.code,
                field_name=exc.field_name,
            ) from exc
        record["_warnings"] = warnings
        record["_monthly_kwh"] = monthly_energy_kwh(
            float(record["power_watts"]),
            float(record["hours_per_day"]),
            int(record.get("days_per_month", 30)),
            int(record.get("quantity", 1)),
        )
        records.append(record)

    # Stable identity per appliance. ``appliance_id`` is unique when Member B supplies it;
    # otherwise fall back to name + position, so two appliances that share a name are NOT
    # treated as one (which would under-count savings and merge their advice).
    per_name_counter: dict[str, int] = {}
    for position, record in enumerate(records):
        name = str(record.get("name") or "appliance")
        occurrence = per_name_counter.get(name, 0)
        per_name_counter[name] = occurrence + 1
        identity = record.get("appliance_id")
        record["_key"] = str(identity) if identity else f"{position}:{name}:{occurrence}"

    total_kwh = sum(record["_monthly_kwh"] for record in records)
    blended_rate = _blended_cost_per_kwh(total_kwh, month, plan_id)

    ranked = sorted(records, key=lambda item: item["_monthly_kwh"], reverse=True)
    flagged_count = top_n if top_n is not None else max(1, min(3, len(ranked)))

    recommendations: list[dict[str, Any]] = []
    per_appliance: list[dict[str, Any]] = []

    for record in records:
        name = str(record.get("name") or "appliance")
        share = (record["_monthly_kwh"] / total_kwh) if total_kwh > 0 else 0.0
        reference = _match_reference(record)

        context: dict[str, Any] = {
            "power_watts": float(record["power_watts"]),
            "hours_per_day": float(record["hours_per_day"]),
            "days_per_month": int(record.get("days_per_month", 30)),
            "quantity": int(record.get("quantity", 1)),
            "monthly_kwh": record["_monthly_kwh"],
            "share": share,
            "reference_power_watts": (reference or {}).get("typical_power_watts"),
            "is_high_power": (reference or {}).get("is_high_power", False),
            "is_always_on": (reference or {}).get("always_on", False),
            "alternative_power_watts": ((reference or {}).get("efficient_alternative") or {}).get(
                "power_watts"
            ),
        }

        appliance_recommendations: list[dict[str, Any]] = []

        # --- Rule 0: this appliance dominates the household consumption ---------
        if share >= HIGH_SHARE_THRESHOLD and record["_monthly_kwh"] > 0:
            target_ratio = 0.15
            saved = record["_monthly_kwh"] * target_ratio
            appliance_recommendations.append(
                _build_recommendation(
                    key=f"top_consumer_{len(appliance_recommendations)}_{_normalise(name)}",
                    appliance_name=name,
                    appliance_key=record["_key"],
                    title_zh=f"{name} 是家中用電量最高的電器之一",
                    reason_zh=(
                        f"預估每月用電 {record['_monthly_kwh']:.1f} 度，占全家總用電 {share * 100:.1f}%。"
                        "優先改善這類電器，節電效果最明顯。"
                    ),
                    suggestion_zh=(
                        "縮短使用時間、改用高效率機種或調整使用時段（避開尖峰），"
                        "只要能降低 15% 用電量就能看到明顯差距。"
                    ),
                    saved_kwh=saved,
                    monthly_cost_saved=saved * blended_rate,
                    assumption_zh=f"假設將此電器的用電量降低 15%（目前每月 {record['_monthly_kwh']:.1f} 度）。",
                    priority=1,
                    severity="high",
                    confidence="medium",
                    extra={"share_of_total_percent": round(share * 100, 2)},
                )
            )

        # --- Rules from the catalogue ------------------------------------------
        if reference:
            for rule in reference.get("rules", []):
                if not _rule_matches(rule, context):
                    continue
                saved, assumption = _estimate_rule_saving(rule, context)
                if saved <= 0 and rule.get("reduction_ratio", 0) == 0:
                    # Behavioural/safety advice with no energy claim (e.g. hair dryer).
                    appliance_recommendations.append(
                        _build_recommendation(
                            key=rule["id"],
                            appliance_name=name,
                            appliance_key=record["_key"],
                            title_zh=rule["title_zh"],
                            reason_zh=rule["reason_zh"],
                            suggestion_zh=rule["suggestion_zh"],
                            saved_kwh=0.0,
                            monthly_cost_saved=0.0,
                            assumption_zh="此建議主要針對用電安全與使用習慣，未估算節省度數。",
                            priority=int(rule.get("priority", 3)),
                            severity=str(rule.get("severity", "low")),
                            confidence="high",
                            extra={"rule_id": rule["id"], "advice_only": True},
                        )
                    )
                    continue
                appliance_recommendations.append(
                    _build_recommendation(
                        key=rule["id"],
                        appliance_name=name,
                        appliance_key=record["_key"],
                        title_zh=rule["title_zh"],
                        reason_zh=rule["reason_zh"],
                        suggestion_zh=rule["suggestion_zh"],
                        saved_kwh=saved,
                        monthly_cost_saved=saved * blended_rate,
                        assumption_zh=assumption,
                        priority=int(rule.get("priority", 3)),
                        severity=str(rule.get("severity", "low")),
                        confidence="medium",
                        extra={"rule_id": rule["id"]},
                    )
                )

        # --- Generic rules when we have no catalogue entry ---------------------
        if not reference and record["_monthly_kwh"] > 0:
            if context["hours_per_day"] >= 8:
                saved = record["_monthly_kwh"] * 0.15
                appliance_recommendations.append(
                    _build_recommendation(
                        key=f"generic_long_hours_{_normalise(name)}",
                        appliance_name=name,
                        appliance_key=record["_key"],
                        title_zh=f"{name} 每日使用時間偏長",
                        reason_zh=(
                            f"每日使用 {context['hours_per_day']:.1f} 小時、每月 {context['days_per_month']} 天，"
                            f"月用電量約 {record['_monthly_kwh']:.1f} 度。"
                        ),
                        suggestion_zh="檢視是否真的需要這麼長的時間，並在不用時完全關閉電源。",
                        saved_kwh=saved,
                        monthly_cost_saved=saved * blended_rate,
                        assumption_zh="假設可降低 15% 使用時間。",
                        priority=3,
                        severity=_severity_from_share(share),
                        confidence="low",
                    )
                )

        per_appliance.append(
            {
                "appliance": name,
                "appliance_key": record["_key"],
                "monthly_kwh": round(record["_monthly_kwh"], 3),
                "share_of_total_percent": round(share * 100, 2),
                "matched_catalog_key": (reference or {}).get("key"),
                # Filled in below from the final returned list, so this count includes
                # the household-level swap advice too and never disagrees with it.
                "recommendation_count": 0,
                "input_warnings": record["_warnings"],
            }
        )
        recommendations.extend(appliance_recommendations)

    # --- Household-level substitute advice (brand/alternative comparison) ------
    for record in ranked[:flagged_count]:
        reference = _match_reference(record)
        if not reference:
            continue
        alternative = reference.get("efficient_alternative")
        if not alternative:
            continue
        current_kwh = record["_monthly_kwh"]
        new_kwh = monthly_energy_kwh(
            float(alternative["power_watts"]),
            float(record["hours_per_day"]),
            int(record.get("days_per_month", 30)),
            int(record.get("quantity", 1)),
        )
        if new_kwh >= current_kwh or current_kwh <= 0:
            continue
        saved = current_kwh - new_kwh
        recommendations.append(
            _build_recommendation(
                key=f"swap_{reference['key']}",
                appliance_name=str(record.get("name")),
                appliance_key=record["_key"],
                title_zh=f"考慮更換為{alternative['label_zh']}",
                reason_zh=(
                    f"目前 {record['power_watts']:g}W 的{reference['name_zh']}每月約用 {current_kwh:.1f} 度；"
                    f"同類高效率機種約 {alternative['power_watts']:g}W。"
                ),
                suggestion_zh=(
                    f"{alternative.get('note_zh', '')} 若日後需要汰換，可優先選擇此類機種，"
                    "新機價格需自行評估是否值得。"
                ).strip(),
                saved_kwh=saved,
                monthly_cost_saved=saved * blended_rate,
                assumption_zh=(
                    f"假設使用時數（每日 {record['hours_per_day']:g} 小時、每月 {record.get('days_per_month', 30)} 天）"
                    "與目前完全相同，僅更換機種功率。"
                ),
                priority=2,
                severity="medium",
                confidence="medium",
                extra={
                    "alternative_label_zh": alternative["label_zh"],
                    "alternative_power_watts": alternative["power_watts"],
                    "is_purchase_advice": True,
                },
            )
        )

    # --- Rank and deduplicate --------------------------------------------------
    recommendations.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 9),
            item["priority"],
            -item["estimated_monthly_saving_kwh"],
        )
    )
    # Deduplicate per APPLIANCE, not globally: two air conditioners both legitimately
    # trigger ``ac_hours_high``, and dropping the second would silently lose advice for
    # an appliance the user actually owns. Deduplication keys on the appliance identity
    # (``appliance_id``, or name+position when absent) while ``id`` stays a stable rule
    # identifier for the frontend.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in recommendations:
        key = item["recommendation_key"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    returned = unique[:max_recommendations]

    # Several suggestions can target the same appliance (e.g. "run the AC less" and
    # "buy a more efficient AC"). Summing all of them would double count, so the
    # headline figure counts only the single best suggestion per appliance, while the
    # larger "if everything is applied" total is reported separately. Grouping uses the
    # appliance identity, so two appliances sharing a name are counted separately.
    best_per_appliance: dict[str, float] = {}
    best_cost_per_appliance: dict[str, float] = {}
    for item in returned:
        identity = item["appliance_key"]
        best_per_appliance[identity] = max(
            best_per_appliance.get(identity, 0.0), item["estimated_monthly_saving_kwh"]
        )
        best_cost_per_appliance[identity] = max(
            best_cost_per_appliance.get(identity, 0.0), item["estimated_monthly_saving_twd"]
        )

    total_saving = sum(best_per_appliance.values())
    total_cost = sum(best_cost_per_appliance.values())
    comprehensive_saving = sum(item["estimated_monthly_saving_kwh"] for item in returned)
    comprehensive_cost = sum(item["estimated_monthly_saving_twd"] for item in returned)

    # Per-appliance counts are taken from the final returned list so the summary always
    # matches the ``recommendations`` array (including household-level swap advice).
    counts_by_appliance: dict[str, int] = {}
    for item in returned:
        counts_by_appliance[item["appliance_key"]] = (
            counts_by_appliance.get(item["appliance_key"], 0) + 1
        )
    for entry in per_appliance:
        entry["recommendation_count"] = counts_by_appliance.get(entry["appliance_key"], 0)

    top_consumers = [
        {
            "appliance": str(record.get("name")),
            "monthly_kwh": round(record["_monthly_kwh"], 3),
            "share_of_total_percent": round(
                (record["_monthly_kwh"] / total_kwh * 100) if total_kwh > 0 else 0.0, 2
            ),
        }
        for record in ranked[:flagged_count]
    ]

    return {
        "currency": "TWD",
        "month": month,
        "plan_id": plan_id,
        "total_monthly_kwh": round(total_kwh, 3),
        "blended_rate_per_kwh": round(blended_rate, 4),
        "top_consumers": top_consumers,
        "high_consumption_threshold_percent": HIGH_SHARE_THRESHOLD * 100,
        "recommendation_count": len(returned),
        "total_potential_monthly_saving_kwh": round(total_saving, 3),
        "total_potential_monthly_saving_twd": round(total_cost, 2),
        "total_potential_annual_saving_twd": round(total_cost * 12, 2),
        "potential_saving_percent_of_usage": (
            round(total_saving / total_kwh * 100, 2) if total_kwh > 0 else 0.0
        ),
        "comprehensive_monthly_saving_kwh": round(comprehensive_saving, 3),
        "comprehensive_monthly_saving_twd": round(comprehensive_cost, 2),
        "aggregation_note_zh": (
            "total_potential_* 只計算每台家電最有效的一項建議（避免同一台家電重複計算）；"
            "comprehensive_* 則是所有建議都落實時的合計，數字會較大。"
        ),
        "recommendations": returned,
        "per_appliance": per_appliance,
        "disclaimer_zh": (
            "以上節電量與金額皆為規則式估算，實際節省效果會因機種、環境與使用習慣而不同，"
            "不保證可達成相同金額。"
        ),
        "disclaimer_en": (
            "All savings are rule-based estimates. Actual savings depend on the appliance model, "
            "environment and habits, and are not guaranteed."
        ),
    }


def catalog_summary() -> dict[str, Any]:
    """Expose the reference catalogue (used by ``GET /appliances`` for the frontend)."""

    catalog = load_appliance_catalog()
    return {
        "defaults": catalog["defaults"],
        "count": len(catalog["appliances"]),
        "appliances": [
            {
                "key": entry["key"],
                "name_en": entry["name_en"],
                "name_zh": entry["name_zh"],
                "category": entry["category"],
                "typical_power_watts": entry["typical_power_watts"],
                "power_range_watts": entry["power_range_watts"],
                "voltage_v": entry["voltage_v"],
                "typical_hours_per_day": entry["typical_hours_per_day"],
                "typical_days_per_month": entry["typical_days_per_month"],
                "is_high_power": entry["is_high_power"],
                "always_on": entry["always_on"],
                "efficiency_note_zh": entry.get("efficiency_note_zh"),
                "efficient_alternative": entry.get("efficient_alternative"),
            }
            for entry in catalog["appliances"]
        ],
    }


def catalog_presets() -> dict[str, Any]:
    """Ready-to-use appliance presets for the UI's "appliance library" panel.

    The frontend prototype hard-coded a handful of appliances and guessed their wattage,
    a 1650 W circuit ceiling and a 3.5 TWD/kWh rate. This endpoint replaces all of that:
    the nameplate values come from the catalogue, and the circuit/socket figures are
    derived from the *standard Taiwan ratings* the load estimator already assumes
    (15 A at 110 V, i.e. the common rented-room socket), with the tariff rate coming from
    the same tariff table the bill calculator uses.
    """

    from ..calculators.electricity_bill import calculate_bill, load_tariffs

    catalog = load_appliance_catalog()
    defaults = catalog["defaults"]

    presets = [
        {
            "key": entry["key"],
            "name_zh": entry["name_zh"],
            "name_en": entry["name_en"],
            "category": entry["category"],
            "power_watts": entry["typical_power_watts"],
            "power_range_watts": entry["power_range_watts"],
            "voltage": entry["voltage_v"],
            "hours_per_day": entry["typical_hours_per_day"],
            "days_per_month": entry["typical_days_per_month"],
            "is_high_power": entry["is_high_power"],
            "always_on": entry["always_on"],
        }
        for entry in catalog["appliances"]
    ]
    # Most-used household appliances first, so the drawer is not alphabetical noise.
    preferred = [
        "air_conditioner",
        "refrigerator",
        "desktop_computer",
        "electric_water_heater",
        "hair_dryer",
        "electric_fan",
        "lighting",
        "washing_machine",
        "rice_cooker",
        "microwave",
        "tv",
        "electric_heater",
    ]
    order = {key: position for position, key in enumerate(preferred)}
    presets.sort(key=lambda item: order.get(item["key"], len(order)))

    # Circuit presets: the amps/voltage pairs a Taiwanese rented room actually has.
    circuits = []
    for label_zh, label_en, amps, voltage in (
        ("房間插座迴路（110V 15A）", "Room socket circuit (110 V, 15 A)", 15, 110.0),
        ("廚房專用迴路（110V 20A）", "Kitchen dedicated circuit (110 V, 20 A)", 20, 110.0),
        ("冷氣專用迴路（220V 15A）", "Air-conditioner circuit (220 V, 15 A)", 15, 220.0),
        ("全戶總開關（110V 50A）", "Whole-room main switch (110 V, 50 A)", 50, 110.0),
    ):
        circuits.append(
            {
                "label_zh": label_zh,
                "label_en": label_en,
                "amps": amps,
                "voltage": voltage,
                "max_watts": round(amps * voltage, 1),
            }
        )

    tariffs = load_tariffs()
    default_plan = tariffs["default_plan_id"]
    # A representative 1 kWh rate at the given season, so the UI never hard-codes a price.
    sample = calculate_bill(1.0, plan_id=default_plan)
    return {
        "defaults": defaults,
        "presets": presets,
        "circuits": circuits,
        "default_circuit_amps": 15,
        "default_voltage": float(defaults.get("voltage_v", 110)),
        "default_plan_id": default_plan,
        "reference_rate_per_kwh": round(sample["total_amount"], 4),
        "reference_season": sample["season"],
    }
