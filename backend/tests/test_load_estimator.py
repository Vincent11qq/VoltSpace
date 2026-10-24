"""Tests for the simplified current / load estimator (Ohm's law based)."""

from __future__ import annotations

import pytest

from app.calculators.load_estimator import (
    LoadError,
    apparent_power_va,
    current_amps,
    estimate_load,
    find_overload_combinations,
)


def appliance(name: str, watts: float, voltage: float = 110.0, **extra) -> dict:
    payload = {"name": name, "power_watts": watts, "voltage": voltage}
    payload.update(extra)
    return payload


class TestCurrentFormula:
    def test_taiwan_110v_socket(self):
        # 1100W / 110V = 10A, the classic "15A socket, 10A appliance" case.
        assert current_amps(1100, 110) == pytest.approx(10.0)

    def test_220v_air_conditioner(self):
        assert current_amps(900, 220) == pytest.approx(4.0909, rel=1e-4)

    def test_current_grows_linearly_with_power(self):
        assert current_amps(2400, 110) == pytest.approx(current_amps(1200, 110) * 2)

    def test_current_falls_as_voltage_rises(self):
        assert current_amps(2000, 110) > current_amps(2000, 220)

    def test_power_factor_increases_the_current(self):
        resistive = current_amps(1000, 110, 1.0)
        inductive = current_amps(1000, 110, 0.8)
        assert inductive == pytest.approx(resistive / 0.8)
        assert inductive > resistive

    def test_three_phase_current_uses_root_three(self):
        assert current_amps(1000, 220, 1.0, phases=3) == pytest.approx(
            1000 / (3 ** 0.5 * 220)
        )

    def test_apparent_power_equals_watts_at_unity_power_factor(self):
        assert apparent_power_va(500, 1.0) == pytest.approx(500.0)
        assert apparent_power_va(500, 0.5) == pytest.approx(1000.0)

    @pytest.mark.parametrize("watts", [0, -100])
    def test_non_positive_power_is_rejected(self, watts):
        with pytest.raises(LoadError) as excinfo:
            current_amps(watts, 110)
        assert excinfo.value.code == "power_not_positive"

    @pytest.mark.parametrize("voltage", [0, -110, 2000])
    def test_voltage_range_is_enforced(self, voltage):
        with pytest.raises(LoadError) as excinfo:
            current_amps(1000, voltage)
        assert excinfo.value.code == "voltage_out_of_range"

    @pytest.mark.parametrize("pf", [0, -0.5, 1.5])
    def test_power_factor_range_is_enforced(self, pf):
        with pytest.raises(LoadError) as excinfo:
            current_amps(1000, 110, pf)
        assert excinfo.value.code == "power_factor_out_of_range"

    def test_invalid_phases_is_rejected(self):
        with pytest.raises(LoadError) as excinfo:
            current_amps(1000, 110, 1.0, phases=2)
        assert excinfo.value.code == "invalid_phases"


class TestLoadEstimate:
    def test_single_appliance_current_and_totals(self):
        result = estimate_load([appliance("Hair dryer", 1200, 110)], load_limit_amps=15)
        assert result["estimated_total_current_amps"] == pytest.approx(10.9091, rel=1e-4)
        assert result["total_power_watts"] == pytest.approx(1200.0)
        assert result["appliance_count"] == 1
        assert result["highest_current_appliance"]["name"] == "Hair dryer"

    def test_currents_are_summed(self):
        result = estimate_load(
            [appliance("Hair dryer", 1100, 110), appliance("Heater", 1100, 110)],
            load_limit_amps=15,
        )
        assert result["estimated_total_current_amps"] == pytest.approx(20.0)

    def test_verdict_safe_below_the_margin(self):
        result = estimate_load([appliance("PC", 500, 110)], load_limit_amps=15)
        assert result["verdict"] == "safe"
        assert result["severity"] == "ok"

    def test_verdict_near_limit_between_margin_and_limit(self):
        # 1400W / 110V = 12.73A -> 85% of a 15A socket
        result = estimate_load([appliance("Hair dryer", 1400, 110)], load_limit_amps=15)
        assert result["verdict"] == "near_limit"
        assert result["severity"] == "warning"

    def test_verdict_over_limit(self):
        # 1700W / 110V = 15.45A > 15A
        result = estimate_load([appliance("Heater", 1700, 110)], load_limit_amps=15)
        assert result["verdict"] == "over_limit"
        assert result["severity"] == "danger"

    def test_verdict_without_a_limit_is_informational(self):
        result = estimate_load([appliance("TV", 100, 110)])
        assert result["verdict"] == "no_limit"
        assert result["severity"] == "info"
        assert result["usage_percent_of_limit"] is None
        assert result["recommended_max_current_amps"] is None

    def test_safety_margin_is_configurable(self):
        appliances = [appliance("Hair dryer", 1400, 110)]  # 12.73A
        strict = estimate_load(appliances, load_limit_amps=15, safety_margin=0.5)  # 7.5A
        relaxed = estimate_load(appliances, load_limit_amps=15, safety_margin=1.0)  # 15A
        assert strict["verdict"] == "near_limit"
        assert relaxed["verdict"] == "safe"
        assert strict["recommended_max_current_amps"] == pytest.approx(7.5)

    def test_usage_percent_of_limit_is_reported(self):
        result = estimate_load([appliance("Hair dryer", 1400, 110)], load_limit_amps=20)
        assert result["usage_percent_of_limit"] == pytest.approx(63.64, abs=0.01)

    def test_quantity_multiplies_the_current(self):
        one = estimate_load([appliance("Fan", 45, 110, quantity=1)])
        four = estimate_load([appliance("Fan", 45, 110, quantity=4)])
        assert four["estimated_total_current_amps"] == pytest.approx(
            one["estimated_total_current_amps"] * 4
        )
        assert four["total_power_watts"] == pytest.approx(180.0)

    def test_default_voltage_is_used_when_absent(self):
        result = estimate_load(
            [{"name": "Load", "power_watts": 1100}], voltage=110, load_limit_amps=15
        )
        assert result["voltage_used"] == 110
        assert result["estimated_total_current_amps"] == pytest.approx(10.0)

    def test_explicit_voltage_argument_is_the_default_for_appliances(self):
        result = estimate_load(
            [{"name": "Load", "power_watts": 2200}], voltage=220, load_limit_amps=15
        )
        assert result["estimated_total_current_amps"] == pytest.approx(10.0)

    def test_mixed_voltages_are_each_respected(self):
        result = estimate_load(
            [appliance("AC", 2200, 220), appliance("Heater", 1100, 110)],
            load_limit_amps=20,
        )
        assert result["estimated_total_current_amps"] == pytest.approx(20.0)

    def test_non_standard_voltage_produces_a_warning(self):
        result = estimate_load([appliance("Odd", 500, 100)], load_limit_amps=15)
        entry = result["appliances"][0]
        assert any(item["code"] == "non_standard_voltage" for item in entry["warnings"])

    def test_power_factor_below_one_produces_a_warning(self):
        result = estimate_load(
            [appliance("Motor", 500, 110, power_factor=0.85)], load_limit_amps=15
        )
        entry = result["appliances"][0]
        assert any(item["code"] == "power_factor_applied" for item in entry["warnings"])
        assert result["total_apparent_power_va"] == pytest.approx(500 / 0.85, abs=0.01)

    def test_breaker_note_explains_the_smaller_limit_wins(self):
        result = estimate_load(
            [appliance("PC", 500, 110)], load_limit_amps=15, breaker_amps=20
        )
        assert any(item["code"] == "socket_vs_breaker" for item in result["warnings"])

    def test_no_breaker_note_when_breaker_is_not_larger(self):
        result = estimate_load(
            [appliance("PC", 500, 110)], load_limit_amps=20, breaker_amps=20
        )
        assert not any(item["code"] == "socket_vs_breaker" for item in result["warnings"])

    def test_circuit_label_is_echoed(self):
        result = estimate_load(
            [appliance("PC", 500, 110)], load_limit_amps=15, circuit_label="Bedroom sockets"
        )
        assert result["circuit_label"] == "Bedroom sockets"

    @pytest.mark.parametrize("margin", [0, 1.1, -0.5])
    def test_invalid_safety_margin_is_rejected(self, margin):
        with pytest.raises(LoadError) as excinfo:
            estimate_load([appliance("PC", 500, 110)], safety_margin=margin)
        assert excinfo.value.code == "invalid_safety_margin"

    @pytest.mark.parametrize("limit", [0, -15])
    def test_invalid_limit_is_rejected(self, limit):
        with pytest.raises(LoadError) as excinfo:
            estimate_load([appliance("PC", 500, 110)], load_limit_amps=limit)
        assert excinfo.value.code == "invalid_limit"

    def test_invalid_phases_is_rejected(self):
        with pytest.raises(LoadError) as excinfo:
            estimate_load([appliance("PC", 500, 110)], phases=2)
        assert excinfo.value.code == "invalid_phases"

    def test_three_phase_uses_the_root_three_formula(self):
        """Regression: ``phases`` must actually reach ``current_amps``.

        3000W at 220V is 13.64A single-phase but 7.87A three-phase; silently ignoring
        ``phases`` would over-estimate the load by a factor of sqrt(3).
        """

        single = estimate_load([appliance("Motor", 3000, 220)], phases=1)
        three = estimate_load([appliance("Motor", 3000, 220)], phases=3)
        assert single["estimated_total_current_amps"] == pytest.approx(13.6364, rel=1e-4)
        assert three["estimated_total_current_amps"] == pytest.approx(7.8730, rel=1e-4)
        assert three["phases"] == 3
        assert three["estimated_total_current_amps"] < single["estimated_total_current_amps"]

    def test_three_phase_changes_the_verdict(self):
        result = estimate_load(
            [appliance("Motor", 3000, 220)], load_limit_amps=10, phases=3
        )
        assert result["verdict"] == "safe"

    def test_three_phase_applies_to_the_per_appliance_detail(self):
        result = estimate_load([appliance("Motor", 3000, 220)], phases=3)
        assert result["appliances"][0]["current_amps"] == pytest.approx(7.8730, rel=1e-4)
        assert result["highest_current_appliance"]["current_amps"] == pytest.approx(
            7.8730, rel=1e-4
        )

    def test_three_phase_with_quantity_and_power_factor(self):
        result = estimate_load(
            [appliance("Motor", 3000, 220, quantity=2, power_factor=0.9)], phases=3
        )
        expected = 2 * 3000 / (3 ** 0.5 * 220 * 0.9)
        # The reported total is rounded to 4 decimal places.
        assert result["estimated_total_current_amps"] == pytest.approx(expected, abs=1e-4)


class TestSafetyDisclaimers:
    def test_disclaimer_is_always_present_and_does_not_claim_safety(self):
        result = estimate_load([appliance("PC", 500, 110)], load_limit_amps=15)
        assert "不構成電路安全保證" in result["disclaimer_zh"]
        assert "not a guarantee" in result["disclaimer_en"]
        # The wording must never promise that the circuit is safe.
        assert "保證電路安全" not in result["disclaimer_zh"].replace("不構成電路安全保證", "")
        assert "安全無虞" not in result["disclaimer_zh"]

    def test_running_current_limitation_is_disclosed(self):
        result = estimate_load([appliance("AC", 900, 220)], load_limit_amps=15)
        codes = {item["code"] for item in result["warnings"]}
        assert "running_current_only" in codes
        assert "disclaimer" in codes

    def test_verdict_message_is_human_readable_chinese(self):
        result = estimate_load([appliance("Heater", 1700, 110)], load_limit_amps=15)
        assert "超過上限" in result["verdict_message_zh"]

    def test_result_is_json_serialisable(self):
        import json

        result = estimate_load([appliance("AC", 900, 220)], load_limit_amps=15)
        assert json.loads(json.dumps(result))["appliance_count"] == 1


class TestOverloadCombinations:
    def test_finds_the_smallest_overloading_pair(self):
        appliances = [
            appliance("Hair dryer", 1200, 110),  # 10.91A
            appliance("Space heater", 1200, 110),  # 10.91A
            appliance("Laptop", 65, 110),  # 0.59A
        ]
        result = find_overload_combinations(appliances, load_limit_amps=15)
        assert result["combination_size"] == 2
        assert result["combinations"]
        assert set(result["combinations"][0]["appliances"]) == {"Hair dryer", "Space heater"}
        assert result["combinations"][0]["over_by_amps"] > 0

    def test_no_combination_when_everything_fits(self):
        appliances = [appliance("Laptop", 65, 110), appliance("TV", 100, 110)]
        result = find_overload_combinations(appliances, load_limit_amps=15)
        assert result["combinations"] == []
        assert result["combination_size"] is None
        assert "沒有找到" in result["message_zh"]

    def test_combinations_are_only_pairs_or_larger(self):
        """A single appliance is never reported as a 'combination'."""

        appliances = [appliance("Heater", 1700, 110), appliance("TV", 100, 110)]
        result = find_overload_combinations(appliances, load_limit_amps=15)
        for combination in result["combinations"]:
            assert len(combination["appliances"]) >= 2

    def test_combinations_respect_the_phase_setting(self):
        """Regression: the combination search must use the same phases as the estimate."""

        appliances = [
            appliance("Motor A", 3000, 220),
            appliance("Motor B", 3000, 220),
        ]
        # Three-phase: 7.87A each, 15.75A combined -> overloads a 15A limit.
        three = find_overload_combinations(appliances, load_limit_amps=15, phases=3)
        assert three["combination_size"] == 2
        assert three["combinations"][0]["total_current_amps"] == pytest.approx(15.7459, rel=1e-3)

    def test_invalid_phases_is_rejected_in_combination_search(self):
        with pytest.raises(LoadError) as excinfo:
            find_overload_combinations(
                [appliance("PC", 500, 110)], load_limit_amps=15, phases=2
            )
        assert excinfo.value.code == "invalid_phases"
