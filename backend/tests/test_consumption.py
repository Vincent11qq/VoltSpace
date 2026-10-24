"""Tests for the monthly consumption calculator."""

from __future__ import annotations

import pytest

from app.calculators.consumption import (
    ApplianceInput,
    ValidationError,
    calculate_consumption,
    calculate_total_consumption,
    daily_energy_kwh,
    monthly_energy_kwh,
    validate_appliance,
)


class TestEnergyFormula:
    def test_1000w_for_one_hour_is_one_kwh(self):
        assert daily_energy_kwh(1000, 1) == pytest.approx(1.0)

    def test_900w_six_hours_a_day_30_days(self):
        # 0.9 kW * 6 h * 30 d = 162 kWh
        assert monthly_energy_kwh(900, 6, 30) == pytest.approx(162.0)

    def test_daily_energy_is_monthly_divided_by_days(self):
        monthly = monthly_energy_kwh(130, 24, 30)
        assert monthly / 30 == pytest.approx(daily_energy_kwh(130, 24))
        assert monthly == pytest.approx(93.6)  # 0.13 * 24 * 30

    def test_quantity_multiplies_the_result(self):
        one = monthly_energy_kwh(500, 2, 30, quantity=1)
        three = monthly_energy_kwh(500, 2, 30, quantity=3)
        assert three == pytest.approx(one * 3)

    def test_zero_hours_means_zero_energy(self):
        assert monthly_energy_kwh(1200, 0, 30) == pytest.approx(0.0)

    def test_zero_days_means_zero_energy(self):
        assert monthly_energy_kwh(1200, 5, 0) == pytest.approx(0.0)

    def test_full_month_continuous_use_is_744_kwh_per_1000w(self):
        # 1 kW running 24 h/day for 31 days
        assert monthly_energy_kwh(1000, 24, 31) == pytest.approx(744.0)


class TestSingleAppliance:
    def test_single_appliance_breakdown(self):
        result = calculate_consumption(
            {"name": "Hair dryer", "power_watts": 1200, "hours_per_day": 0.25}
        )
        assert result["count"] == 1
        assert result["total_monthly_kwh"] == pytest.approx(9.0)  # 1.2 * 0.25 * 30
        assert result["appliances"][0]["share_of_total_percent"] == pytest.approx(100.0)
        assert result["highest_consumption_appliance"] == "Hair dryer"

    def test_defaults_are_thirty_days_and_one_unit(self):
        entry = calculate_consumption(
            {"name": "Fan", "power_watts": 45, "hours_per_day": 8}
        )["appliances"][0]
        assert entry["days_per_month"] == 30
        assert entry["quantity"] == 1
        assert entry["monthly_kwh"] == pytest.approx(10.8)

    def test_dataclass_input_is_accepted(self):
        result = calculate_consumption(
            ApplianceInput(name="TV", power_watts=100, hours_per_day=3)
        )
        assert result["total_monthly_kwh"] == pytest.approx(9.0)


class TestHouseholdTotal:
    def test_total_is_the_sum_of_appliances(self, student_room):
        result = calculate_consumption(student_room)
        # AC 162 + fridge 93.6 + PC 45 = 300.6
        assert result["total_monthly_kwh"] == pytest.approx(300.6)
        assert result["count"] == 3
        assert result["highest_consumption_appliance"] == "Air conditioner"

    def test_shares_sum_to_one_hundred_percent(self, student_room):
        result = calculate_consumption(student_room)
        total_share = sum(item["share_of_total_percent"] for item in result["appliances"])
        assert total_share == pytest.approx(100.0, abs=0.02)

    def test_appliance_order_does_not_change_the_total(self, student_room):
        reversed_total = calculate_consumption(list(reversed(student_room)))[
            "total_monthly_kwh"
        ]
        assert reversed_total == pytest.approx(calculate_consumption(student_room)["total_monthly_kwh"])

    def test_helper_returns_only_the_total(self, student_room):
        assert calculate_total_consumption(student_room) == pytest.approx(300.6)

    def test_all_zero_usage_gives_zero_total_without_division_error(self):
        result = calculate_consumption(
            [{"name": "Idle", "power_watts": 100, "hours_per_day": 0, "days_per_month": 30}]
        )
        assert result["total_monthly_kwh"] == 0.0
        assert result["appliances"][0]["share_of_total_percent"] == 0.0

    def test_daily_total_matches_monthly_scaled_by_days(self, student_room):
        result = calculate_consumption(student_room)
        assert result["total_daily_kwh"] * 30 == pytest.approx(result["total_monthly_kwh"], abs=0.01)

    def test_editing_power_changes_only_that_appliance(self, student_room):
        baseline = calculate_consumption(student_room)
        edited = [dict(item) for item in student_room]
        edited[0]["power_watts"] = 1800  # double the air conditioner
        after = calculate_consumption(edited)

        baseline_ac = baseline["appliances"][0]["monthly_kwh"]
        after_ac = after["appliances"][0]["monthly_kwh"]
        assert after_ac == pytest.approx(baseline_ac * 2)
        # Untouched appliances keep their values.
        assert after["appliances"][1]["monthly_kwh"] == pytest.approx(
            baseline["appliances"][1]["monthly_kwh"]
        )

    def test_editing_hours_and_days(self):
        base = calculate_consumption(
            [{"name": "AC", "power_watts": 1000, "hours_per_day": 4, "days_per_month": 30}]
        )["total_monthly_kwh"]
        changed = calculate_consumption(
            [{"name": "AC", "power_watts": 1000, "hours_per_day": 2, "days_per_month": 15}]
        )["total_monthly_kwh"]
        assert base == pytest.approx(120.0)
        assert changed == pytest.approx(30.0)

    def test_quantity_scales_the_household_total(self):
        one_fan = calculate_consumption(
            [{"name": "Fan", "power_watts": 45, "hours_per_day": 8, "quantity": 1}]
        )["total_monthly_kwh"]
        four_fans = calculate_consumption(
            [{"name": "Fan", "power_watts": 45, "hours_per_day": 8, "quantity": 4}]
        )["total_monthly_kwh"]
        assert four_fans == pytest.approx(one_fan * 4)


class TestValidation:
    @pytest.mark.parametrize("power", [0, -1, -900])
    def test_power_must_be_positive(self, power):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": power, "hours_per_day": 1}
            )
        assert excinfo.value.code == "power_not_positive"

    def test_power_above_supported_maximum_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": 100_001, "hours_per_day": 1}
            )
        assert excinfo.value.code == "power_too_large"

    @pytest.mark.parametrize("hours", [-0.5, 24.5, 100])
    def test_hours_per_day_range(self, hours):
        with pytest.raises(ValidationError):
            calculate_consumption(
                {"name": "Bad", "power_watts": 100, "hours_per_day": hours}
            )

    @pytest.mark.parametrize("days", [-1, 32, 100])
    def test_days_per_month_range(self, days):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": 100, "hours_per_day": 1, "days_per_month": days}
            )
        assert excinfo.value.code == "days_out_of_range"

    def test_days_per_month_must_be_an_integer(self):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": 100, "hours_per_day": 1, "days_per_month": 15.5}
            )
        assert excinfo.value.code == "days_not_integer"

    @pytest.mark.parametrize("quantity", [0, -2, 1000])
    def test_quantity_range(self, quantity):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": 100, "hours_per_day": 1, "quantity": quantity}
            )
        assert excinfo.value.code == "quantity_out_of_range"

    @pytest.mark.parametrize("value", ["900", None, True, [900]])
    def test_non_numeric_power_is_rejected(self, value):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": value, "hours_per_day": 1}
            )
        assert excinfo.value.code == "not_a_number"

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_values_are_rejected(self, value):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": value, "hours_per_day": 1}
            )
        assert excinfo.value.code == "not_finite"

    def test_negative_voltage_is_rejected(self):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption(
                {"name": "Bad", "power_watts": 100, "hours_per_day": 1, "voltage": -110}
            )
        assert excinfo.value.code == "voltage_not_positive"

    def test_error_carries_field_name_and_dict_shape(self):
        with pytest.raises(ValidationError) as excinfo:
            calculate_consumption({"name": "Bad", "power_watts": -1, "hours_per_day": 1})
        payload = excinfo.value.as_dict()
        assert payload["field"] == "power_watts"
        assert payload["code"] == "power_not_positive"
        assert "message" in payload


class TestWarnings:
    def test_zero_hours_produces_a_non_fatal_warning(self):
        warnings = validate_appliance(
            {"name": "Idle", "power_watts": 100, "hours_per_day": 0}
        )
        assert any(item["code"] == "no_usage" for item in warnings)

    def test_very_high_power_produces_a_warning(self):
        warnings = validate_appliance(
            {"name": "Kiln", "power_watts": 25_000, "hours_per_day": 1}
        )
        assert any(item["code"] == "very_high_power" for item in warnings)

    def test_near_continuous_use_produces_a_warning(self):
        warnings = validate_appliance(
            {"name": "Fridge", "power_watts": 130, "hours_per_day": 22}
        )
        assert any(item["code"] == "near_continuous_use" for item in warnings)

    def test_normal_appliance_has_no_warnings(self):
        assert validate_appliance(
            {"name": "TV", "power_watts": 100, "hours_per_day": 3}
        ) == []

    def test_warnings_are_surfaced_in_the_result(self):
        result = calculate_consumption(
            {"name": "Idle", "power_watts": 100, "hours_per_day": 0}
        )
        assert result["appliances"][0]["warnings"][0]["code"] == "no_usage"

    @pytest.mark.parametrize(
        "appliance",
        [
            {"name": "Idle", "power_watts": 100, "hours_per_day": 0},
            {"name": "Kiln", "power_watts": 25_000, "hours_per_day": 1},
            {"name": "Fridge", "power_watts": 130, "hours_per_day": 22},
        ],
    )
    def test_every_warning_is_bilingual(self, appliance):
        warnings = validate_appliance(appliance)
        assert warnings
        for warning in warnings:
            assert warning["code"]
            assert warning["message_zh"].strip()
            assert warning["message_en"].strip()


class TestEdgeCases:
    def test_boundary_values_are_accepted(self):
        # Minimum power, maximum hours, maximum days, maximum quantity.
        result = calculate_consumption(
            {
                "name": "Edge",
                "power_watts": 0.1,
                "hours_per_day": 24,
                "days_per_month": 31,
                "quantity": 999,
            }
        )
        expected = (0.1 / 1000) * 24 * 31 * 999
        assert result["total_monthly_kwh"] == pytest.approx(expected, rel=1e-9)

    def test_large_household_total(self):
        appliances = [
            {"name": f"Appliance {i}", "power_watts": 1000, "hours_per_day": 1, "days_per_month": 30}
            for i in range(50)
        ]
        assert calculate_consumption(appliances)["total_monthly_kwh"] == pytest.approx(1500.0)

    def test_empty_list_is_a_valid_zero_result(self):
        result = calculate_consumption([])
        assert result["count"] == 0
        assert result["total_monthly_kwh"] == 0.0
        assert result["highest_consumption_appliance"] is None

    def test_single_appliance_result_is_json_serialisable(self):
        import json

        result = calculate_consumption(
            {"name": "TV", "power_watts": 100, "hours_per_day": 3}
        )
        assert json.loads(json.dumps(result))["total_monthly_kwh"] == pytest.approx(9.0)
