"""Simplified current and electrical-load estimation.

Scope (deliberately limited)
----------------------------
This module answers "roughly how much current does this appliance draw, and does it
look close to a household limit?". It is an *educational first-pass warning*, not an
electrical safety certification.

Modelling assumptions, all of which are stated in the API response:

* **Running current only.** ``I = P / (V * PF)`` uses the rated nameplate power.
  Inrush / starting current (compressors, motors) is much higher and is NOT modelled.
* **simplified (resistive) current** ``I = P / V`` is the conservative upper bound;
  the default ``power_factor=1.0`` therefore reports the *highest* expected current.
* Currents are added **arithmetically**, not by vector/phase sum, so a mixed
  inductive + resistive circuit is approximated pessimistically.
* **We cannot guarantee circuit safety.** Breakers, wire gauge, socket rating and
  circuit sharing must be verified by a qualified electrician.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Mapping, Sequence

MIN_VOLTAGE = 1.0
MAX_VOLTAGE = 1000.0
MIN_POWER_FACTOR = 0.1
MAX_POWER_FACTOR = 1.0

# Common single-phase voltages in Taiwan (V). 110V sockets are the norm in rented
# rooms; 220V is used for air conditioners, induction cookers and clothes dryers.
STANDARD_VOLTAGES = (110.0, 220.0)

DEFAULT_PHASES = 1
DEFAULT_SAFETY_MARGIN = 0.80


class LoadError(ValueError):
    """Raised for load inputs that cannot be evaluated."""

    def __init__(self, message: str, *, code: str = "load_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ApplianceLoad:
    """Current estimate for one appliance."""

    name: str
    appliance_id: str | None
    power_watts: float
    voltage: float
    power_factor: float
    current_amps: float
    apparent_power_va: float
    quantity: int = 1
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "appliance_id": self.appliance_id,
            "name": self.name,
            "power_watts": round(self.power_watts, 3),
            "voltage": self.voltage,
            "power_factor": self.power_factor,
            "quantity": self.quantity,
            "current_amps": round(self.current_amps, 4),
            "apparent_power_va": round(self.apparent_power_va, 2),
            "warnings": self.warnings,
        }


def current_amps(
    power_watts: float,
    voltage: float = 110.0,
    power_factor: float = 1.0,
    *,
    phases: int = 1,
) -> float:
    """Return the running current in amperes.

    ``phases=1``  -> ``I = P / (V * PF)``
    ``phases=3``  -> ``I = P / (sqrt(3) * V * PF)``
    """

    if power_watts <= 0:
        raise LoadError("power_watts must be greater than 0", code="power_not_positive")
    if not MIN_VOLTAGE <= voltage <= MAX_VOLTAGE:
        raise LoadError(
            f"voltage must be between {MIN_VOLTAGE} and {MAX_VOLTAGE}", code="voltage_out_of_range"
        )
    if not MIN_POWER_FACTOR <= power_factor <= MAX_POWER_FACTOR:
        raise LoadError(
            f"power_factor must be between {MIN_POWER_FACTOR} and {MAX_POWER_FACTOR}",
            code="power_factor_out_of_range",
        )
    if phases not in (1, 3):
        raise LoadError("phases must be 1 or 3", code="invalid_phases")

    divisor = voltage * power_factor
    if phases == 3:
        divisor *= 3 ** 0.5
    return power_watts / divisor


def apparent_power_va(power_watts: float, power_factor: float = 1.0) -> float:
    """Apparent power in VA; equals watts when the power factor is 1."""

    if power_factor <= 0:
        raise LoadError("power_factor must be greater than 0", code="power_factor_out_of_range")
    return power_watts / power_factor


def _as_mapping(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    return {
        "name": getattr(item, "name", "appliance"),
        "appliance_id": getattr(item, "appliance_id", None),
        "power_watts": getattr(item, "power_watts"),
        "voltage": getattr(item, "voltage", None),
        "quantity": getattr(item, "quantity", 1),
        "power_factor": getattr(item, "power_factor", None),
    }


def estimate_appliance_loads(
    appliances: Sequence[Any],
    *,
    default_voltage: float = 110.0,
    phases: int = DEFAULT_PHASES,
) -> list[ApplianceLoad]:
    """Estimate current for each appliance independently.

    ``default_voltage`` is used for any appliance that does not state its own voltage
    (an explicitly unknown voltage is treated the same as an omitted one).
    ``phases`` selects the single- or three-phase formula and must be forwarded,
    otherwise a three-phase circuit is over-estimated by a factor of sqrt(3).
    """

    if phases not in (1, 3):
        raise LoadError("phases must be 1 or 3", code="invalid_phases")

    loads: list[ApplianceLoad] = []
    for raw in appliances:
        item = _as_mapping(raw)
        power = float(item.get("power_watts", 0) or 0)
        voltage = float(item.get("voltage") or default_voltage)
        power_factor = float(item.get("power_factor") or 1.0)
        quantity = int(item.get("quantity") or 1)

        warnings: list[dict[str, Any]] = []
        if voltage not in STANDARD_VOLTAGES:
            common = "、".join(f"{v:g}" for v in STANDARD_VOLTAGES)
            warnings.append(
                {
                    "code": "non_standard_voltage",
                    "message_zh": (
                        f"{voltage:g}V 不是台灣常見的家用電壓（{common}V），請再確認電器銘牌。"
                    ),
                    "message_en": (
                        f"{voltage:g}V is not one of the common Taiwan household voltages "
                        f"({common.replace('、', ', ')}V). Please confirm the nameplate."
                    ),
                }
            )
        if power_factor < 1.0:
            warnings.append(
                {
                    "code": "power_factor_applied",
                    "message_zh": f"已套用功率因數 {power_factor:g}，因此電流會高於純電阻性估算值。",
                    "message_en": (
                        f"A power factor of {power_factor:g} was applied, so the current is higher "
                        "than the purely resistive estimate."
                    ),
                }
            )

        current = current_amps(power, voltage, power_factor, phases=phases) * quantity
        loads.append(
            ApplianceLoad(
                name=str(item.get("name") or "appliance"),
                appliance_id=item.get("appliance_id"),
                power_watts=power,
                voltage=voltage,
                power_factor=power_factor,
                current_amps=current,
                apparent_power_va=apparent_power_va(power, power_factor) * quantity,
                quantity=quantity,
                warnings=warnings,
            )
        )
    return loads


def _verdict(total_current: float, limit: float | None, safety_margin: float) -> tuple[str, str, str]:
    """Return ``(verdict, severity, zh_message)``."""

    if limit is None or limit <= 0:
        return (
            "no_limit",
            "info",
            "未提供負載上限，僅提供電流估算結果，無法判斷是否接近上限。",
        )
    threshold = limit * safety_margin
    if total_current > limit:
        return (
            "over_limit",
            "danger",
            f"估算總電流 {total_current:.2f}A 已超過上限 {limit:.2f}A，請勿同時開啟這些電器，並請專業電工檢查迴路。",
        )
    if total_current > threshold:
        return (
            "near_limit",
            "warning",
            f"估算總電流 {total_current:.2f}A 已達上限 {limit:.2f}A 的 {total_current / limit * 100:.0f}%，建議避免同時使用高功率電器。",
        )
    return (
        "safe",
        "ok",
        f"估算總電流 {total_current:.2f}A 低於上限 {limit:.2f}A 的建議使用值 {threshold:.2f}A。",
    )


def estimate_load(
    appliances: Sequence[Any],
    *,
    voltage: float | None = None,
    load_limit_amps: float | None = None,
    safety_margin: float = DEFAULT_SAFETY_MARGIN,
    phases: int = DEFAULT_PHASES,
    breaker_amps: float | None = None,
    circuit_label: str | None = None,
) -> dict[str, Any]:
    """Estimate the combined current of a set of appliances and warn if it is high.

    Parameters
    ----------
    appliances:
        Anything with ``name`` / ``power_watts`` / ``voltage`` / ``quantity``.
    voltage:
        Household supply voltage used when an appliance does not specify one.
    load_limit_amps:
        The user's stated circuit / socket limit. Typical Taiwan room circuits are
        15A (110V) or 20A; a rented room's main breaker is often 20-50A. Never
        assume this value for the user.
    safety_margin:
        Fraction of the limit that should be treated as the practical ceiling.
    breaker_amps:
        Optional; when supplied and greater than ``load_limit_amps``, a combined
        note is produced.
    """

    if not 0.1 <= safety_margin <= 1.0:
        raise LoadError("safety_margin must be between 0.1 and 1.0", code="invalid_safety_margin")
    if load_limit_amps is not None and load_limit_amps <= 0:
        raise LoadError("load_limit_amps must be greater than 0", code="invalid_limit")
    if phases not in (1, 3):
        raise LoadError("phases must be 1 or 3", code="invalid_phases")

    resolved_voltage = float(voltage) if voltage else 110.0
    loads = estimate_appliance_loads(
        appliances, default_voltage=resolved_voltage, phases=phases
    )

    total_current = sum(load.current_amps for load in loads)
    total_watts = sum(load.power_watts * load.quantity for load in loads)
    total_va = sum(load.apparent_power_va for load in loads)

    verdict, severity, message_zh = _verdict(total_current, load_limit_amps, safety_margin)

    warnings: list[dict[str, Any]] = [
        {
            "code": "disclaimer",
            "severity": "info",
            "message_zh": "本估算僅供初步參考，無法保證電路安全；實際配線、斷路器與插座規格需由專業電工確認。",
            "message_en": "Preliminary estimate only. It does not guarantee circuit safety; a qualified electrician must verify wiring, breakers and sockets.",
        },
        {
            "code": "running_current_only",
            "severity": "info",
            "message_zh": "此估算為運轉電流，未包含馬達或壓縮機的啟動電流（啟動電流可能高出數倍）。",
            "message_en": "This is running current only; motor/compressor inrush current is not modelled and can be several times higher.",
        },
    ]

    if load_limit_amps is not None:
        warnings.append(
            {
                "code": verdict,
                "severity": severity,
                "message_zh": message_zh,
                "message_en": {
                    "over_limit": "Estimated total current exceeds the stated limit.",
                    "near_limit": "Estimated total current is close to the stated limit.",
                    "safe": "Estimated total current is comfortably below the stated limit.",
                }[verdict],
                "total_current_amps": round(total_current, 4),
                "limit_amps": load_limit_amps,
                "usage_percent": round(total_current / load_limit_amps * 100, 2),
            }
        )

    if breaker_amps is not None and load_limit_amps is not None and breaker_amps > load_limit_amps:
        warnings.append(
            {
                "code": "socket_vs_breaker",
                "severity": "info",
                "message_zh": (
                    f"插座/迴路上限 {load_limit_amps:g}A 低於斷路器額定 {breaker_amps:g}A。"
                    "斷路器保護的是電線，不會保護插座與延長線，請以較小的數值作為同時用電的依據。"
                ),
                "message_en": (
                    f"The socket/circuit limit ({load_limit_amps:g}A) is lower than the breaker rating "
                    f"({breaker_amps:g}A). A breaker protects the wiring, not the socket or an extension "
                    "lead, so use the smaller value as the practical limit."
                ),
            }
        )

    highest = max(loads, key=lambda load: load.current_amps, default=None)

    return {
        "circuit_label": circuit_label,
        "voltage_used": resolved_voltage,
        "phases": phases,
        "appliance_count": len(loads),
        "total_power_watts": round(total_watts, 2),
        "total_apparent_power_va": round(total_va, 2),
        "estimated_total_current_amps": round(total_current, 4),
        "limit_amps": load_limit_amps,
        "breaker_amps": breaker_amps,
        "safety_margin": safety_margin,
        "recommended_max_current_amps": (
            round(load_limit_amps * safety_margin, 4) if load_limit_amps else None
        ),
        "usage_percent_of_limit": (
            round(total_current / load_limit_amps * 100, 2) if load_limit_amps else None
        ),
        "verdict": verdict,
        "severity": severity,
        "verdict_message_zh": message_zh,
        "highest_current_appliance": (
            {"name": highest.name, "current_amps": round(highest.current_amps, 4)}
            if highest
            else None
        ),
        "appliances": [load.as_dict() for load in loads],
        "warnings": warnings,
        "disclaimer_zh": (
            "本工具僅提供初步負載估算，不構成電路安全保證，也不能取代專業電工的現場檢查。"
        ),
        "disclaimer_en": (
            "This tool provides a preliminary load estimate only. It is not a guarantee of "
            "electrical safety and does not replace an on-site inspection by a qualified electrician."
        ),
    }


def find_overload_combinations(
    appliances: Sequence[Any],
    *,
    load_limit_amps: float,
    voltage: float = 110.0,
    max_combination_size: int = 4,
    phases: int = DEFAULT_PHASES,
) -> dict[str, Any]:
    """Find the smallest appliance combinations whose summed current exceeds the limit.

    This powers the "which two appliances must not run at the same time?" advice.
    """

    if phases not in (1, 3):
        raise LoadError("phases must be 1 or 3", code="invalid_phases")

    loads = estimate_appliance_loads(appliances, default_voltage=voltage, phases=phases)
    flagged: list[dict[str, Any]] = []

    # Search increasing group sizes and stop at the first size that overloads, so the
    # advice names the smallest set of appliances that must not run together.
    for group_size in range(2, min(max_combination_size, len(loads)) + 1):
        for group in combinations(loads, group_size):
            total = sum(load.current_amps for load in group)
            if total <= load_limit_amps:
                continue
            flagged.append(
                {
                    "appliances": [load.name for load in group],
                    "total_current_amps": round(total, 4),
                    "over_by_amps": round(total - load_limit_amps, 4),
                }
            )
        if flagged:
            break

    flagged.sort(key=lambda item: item["total_current_amps"], reverse=True)
    return {
        "load_limit_amps": load_limit_amps,
        "combination_size": len(flagged[0]["appliances"]) if flagged else None,
        "combinations": flagged[:10],
        "message_zh": (
            "以下電器組合的估算電流會超過上限，請避免同時使用。"
            if flagged
            else "在目前輸入的電器中，沒有找到會超過上限的同時使用組合。"
        ),
    }
