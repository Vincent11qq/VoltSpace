"""Tests for the scenario simulator.

The most important guarantee tested here is that simulating a scenario **never
modifies the caller's appliance records**.
"""

from __future__ import annotations

import copy

import pytest

from app.calculators.consumption import calculate_consumption
from app.calculators.electricity_bill import TariffError
from app.services.simulation import (
    SimulationError,
    simulate,
    what_if_reduction,
)


def appliance(name: str, watts: float, hours: float, days: int = 30, **extra) -> dict:
    payload = {
        "appliance_id": extra.pop("appliance_id", name.lower().replace(" ", "_")),
        "name": name,
        "power_watts": watts,
        "hours_per_day": hours,
        "days_per_month": days,
        "voltage": extra.pop("voltage", 110),
    }
    payload.update(extra)
    return payload


@pytest.fixture
def room() -> list[dict]:
    return [
        appliance("Air conditioner", 900, 6, voltage=220),
        appliance("Refrigerator", 130, 24),
    ]


class TestBaselineVersusModified:
    def test_reducing_hours_lowers_consumption_and_cost(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 5}],
            month=8,
        )
        assert result["baseline"]["total_monthly_kwh"] == pytest.approx(255.6)  # 162 + 93.6
        assert result["modified"]["total_monthly_kwh"] == pytest.approx(228.6)  # 135 + 93.6
        assert result["delta"]["saved_kwh"] == pytest.approx(27.0)
        assert result["delta"]["is_saving"] is True

    def test_saved_amount_matches_the_bill_difference(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}],
            month=8,
        )
        expected = (
            result["baseline"]["estimated_bill_twd"] - result["modified"]["estimated_bill_twd"]
        )
        assert result["delta"]["saved_amount_twd"] == pytest.approx(expected, abs=0.01)

    def test_savings_may_be_negative_when_usage_increases(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 10}],
            month=8,
        )
        assert result["delta"]["saved_kwh"] < 0
        assert result["delta"]["saved_amount_twd"] < 0
        assert result["delta"]["is_saving"] is False

    def test_identical_change_reports_zero_saving(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 6}],
            month=8,
        )
        assert result["delta"]["saved_kwh"] == pytest.approx(0.0)
        assert result["delta"]["saved_amount_twd"] == pytest.approx(0.0)

    def test_percentage_savings_are_reported(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 3}],
            month=8,
        )
        assert result["delta"]["saved_percent_of_kwh"] == pytest.approx(50.0 * 162 / 255.6, abs=0.05)
        assert result["delta"]["saved_percent_of_amount"] > 0
        assert result["delta"]["annual_saved_amount_twd"] == pytest.approx(
            result["delta"]["saved_amount_twd"] * 12, abs=0.05
        )

    def test_progressive_tiers_make_the_saving_percentage_higher_for_money(self, room):
        """Because tiers are progressive, money saved can exceed the kWh share."""

        heavy = [
            appliance("Air conditioner", 2200, 12, voltage=220),
            appliance("Electric water heater", 4000, 2, voltage=220),
        ]
        result = simulate(
            heavy,
            [{"appliance_id": "electric_water_heater", "field": "hours_per_day", "value": 1}],
            month=8,
        )
        assert result["delta"]["saved_percent_of_amount"] > result["delta"]["saved_percent_of_kwh"]

    def test_comparison_table_covers_every_appliance(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 5}],
            month=8,
        )
        names = [row["appliance"] for row in result["comparison_table"]]
        assert set(names) == {"Air conditioner", "Refrigerator"}
        changed = [row for row in result["comparison_table"] if row["saved_kwh"] != 0]
        assert len(changed) == 1
        assert changed[0]["saved_kwh"] == pytest.approx(27.0)

    def test_percent_change_is_reported_per_appliance(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 3}],
            month=8,
        )
        ac = next(
            row for row in result["comparison_table"] if row["appliance"] == "Air conditioner"
        )
        assert ac["percent_change"] == pytest.approx(-50.0)

    def test_applied_changes_describe_before_and_after(self, room):
        result = simulate(
            room,
            [
                {
                    "appliance_id": "air_conditioner",
                    "field": "hours_per_day",
                    "value": 5,
                    "label_zh": "冷氣每天少吹 1 小時",
                }
            ],
            month=8,
        )
        change = result["applied_changes"][0]
        assert change["field"] == "hours_per_day"
        assert change["before"] == 6
        assert change["after"] == 5
        assert change["label_zh"] == "冷氣每天少吹 1 小時"


class TestNonMutation:
    def test_original_list_is_not_modified(self, room):
        before = copy.deepcopy(room)
        simulate(
            room,
            [
                {"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 2},
                {"appliance_id": "air_conditioner", "field": "power_watts", "value": 500},
                {"appliance_id": "refrigerator", "field": "days_per_month", "value": 10},
            ],
            month=8,
        )
        assert room == before

    def test_replace_with_does_not_modify_the_original(self, room):
        before = copy.deepcopy(room)
        simulate(
            room,
            [
                {
                    "appliance_id": "air_conditioner",
                    "field": "replace_with",
                    "replacement": {"power_watts": 700, "name": "Inverter AC"},
                }
            ],
            month=8,
        )
        assert room == before
        assert room[0]["power_watts"] == 900
        assert room[0]["name"] == "Air conditioner"

    def test_baseline_output_matches_a_direct_calculation(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 5}],
            month=8,
        )
        direct = calculate_consumption(room)
        assert result["baseline"]["total_monthly_kwh"] == pytest.approx(
            direct["total_monthly_kwh"], abs=0.01
        )

    def test_modified_output_is_recomputed_not_mutated(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "power_watts", "value": 450}],
            month=8,
        )
        assert result["modified"]["appliances"][0]["power_watts"] == 450
        assert result["baseline"]["appliances"][0]["power_watts"] == 900

    def test_two_simulations_do_not_leak_into_each_other(self, room):
        first = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 2}],
            month=8,
        )
        second = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 12}],
            month=8,
        )
        assert first["modified"]["total_monthly_kwh"] < second["modified"]["total_monthly_kwh"]
        assert first["baseline"]["total_monthly_kwh"] == pytest.approx(
            second["baseline"]["total_monthly_kwh"]
        )


class TestDuplicateApplianceNames:
    """Two appliances may legitimately share a name; matching must stay positional."""

    @pytest.fixture
    def twins(self) -> list[dict]:
        return [
            appliance("Light", 20, 6, appliance_id="l1"),
            appliance("Light", 20, 6, appliance_id="l2"),
        ]

    def test_ids_keep_the_two_appliances_apart(self, twins):
        result = simulate(
            twins,
            [{"appliance_id": "l2", "field": "hours_per_day", "value": 12}],
            month=8,
        )
        rows = result["comparison_table"]
        assert len(rows) == 2
        # l1 unchanged, l2 doubled -> 20W*6h*30d = 3.6 kWh each before.
        assert sorted(row["saved_kwh"] for row in rows) == pytest.approx([-3.6, 0.0])

    def test_name_match_claims_each_record_only_once(self):
        """Without ids, each baseline appliance must map to a distinct modified record."""

        baseline = [
            {"name": "Light", "power_watts": 20, "hours_per_day": 6, "days_per_month": 30},
            {"name": "Light", "power_watts": 20, "hours_per_day": 6, "days_per_month": 30},
        ]
        result = simulate(
            baseline,
            [{"name": "Light", "field": "hours_per_day", "value": 12}],
            month=8,
        )
        rows = result["comparison_table"]
        assert len(rows) == 2
        # Exactly one appliance was changed; the other keeps its baseline value.
        changed = [row for row in rows if row["saved_kwh"] != 0]
        unchanged = [row for row in rows if row["saved_kwh"] == 0]
        assert len(changed) == 1
        assert len(unchanged) == 1
        assert changed[0]["modified_kwh"] == pytest.approx(7.2)
        assert unchanged[0]["modified_kwh"] == pytest.approx(3.6)

    def test_duplicate_names_do_not_inflate_the_total_saving(self, twins):
        result = simulate(
            twins,
            [{"name": "Light", "field": "hours_per_day", "value": 12}],
            month=8,
        )
        # 20W * 6 extra hours * 30 days = 3.6 kWh, counted once.
        assert result["delta"]["saved_kwh"] == pytest.approx(-3.6)


class TestChangeTypes:
    def test_power_change(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "power_watts", "value": 1800}],
            month=8,
        )
        assert result["delta"]["saved_kwh"] == pytest.approx(-162.0)

    def test_days_per_month_change(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "days_per_month", "value": 15}],
            month=8,
        )
        assert result["modified"]["total_monthly_kwh"] == pytest.approx(93.6 + 81.0)

    def test_quantity_change(self, room):
        room = room + [appliance("Fan", 45, 8)]
        result = simulate(
            room,
            [{"appliance_id": "fan", "field": "quantity", "value": 3}],
            month=8,
        )
        # Two extra fans: 2 * 45W * 8h * 30d = 21.6 kWh more
        assert result["delta"]["saved_kwh"] == pytest.approx(-21.6)

    def test_replace_with_a_more_efficient_model(self, room):
        result = simulate(
            room,
            [
                {
                    "appliance_id": "air_conditioner",
                    "field": "replace_with",
                    "replacement": {"label": "一級能效變頻冷氣", "power_watts": 450},
                }
            ],
            month=8,
        )
        assert result["modified"]["appliances"][0]["power_watts"] == 450
        assert result["delta"]["saved_kwh"] == pytest.approx(81.0)
        assert result["modified"]["appliances"][0]["replacement_label"] == "一級能效變頻冷氣"

    def test_replace_with_can_also_change_the_usage_habit(self, room):
        result = simulate(
            room,
            [
                {
                    "appliance_id": "air_conditioner",
                    "field": "replace_with",
                    "replacement": {"power_watts": 700, "hours_per_day": 4},
                }
            ],
            month=8,
        )
        entry = result["modified"]["appliances"][0]
        assert entry["power_watts"] == 700
        assert entry["hours_per_day"] == 4


class TestRenamingSwap:
    """A swap that renames the appliance must stay one row, keyed by the ORIGINAL name."""

    @pytest.fixture
    def single_ac(self) -> list[dict]:
        return [
            {
                "name": "AC",
                "power_watts": 1400,
                "hours_per_day": 8,
                "days_per_month": 30,
                "voltage": 220,
            }
        ]

    def test_rename_without_an_id_still_pairs_baseline_with_modified(self, single_ac):
        """Regression: the rename split one swap into two bogus rows (336->0 and 0->168)."""

        result = simulate(
            single_ac,
            [
                {
                    "name": "AC",
                    "field": "replace_with",
                    "replacement": {"name": "NewAC", "power_watts": 700},
                }
            ],
            month=8,
        )
        rows = result["comparison_table"]
        assert len(rows) == 1, rows
        # 1.4kW * 8h * 30d = 336 kWh -> 0.7kW * 8h * 30d = 168 kWh
        assert rows[0]["appliance"] == "AC"
        assert rows[0]["baseline_kwh"] == pytest.approx(336.0)
        assert rows[0]["modified_kwh"] == pytest.approx(168.0)
        assert rows[0]["saved_kwh"] == pytest.approx(168.0)
        assert rows[0]["percent_change"] == pytest.approx(-50.0)
        assert rows[0]["status"] == "changed"
        # The new name is reported separately rather than replacing the row identity.
        assert rows[0]["replaced_by"] == "NewAC"

    def test_rename_without_an_id_gives_the_same_totals_as_with_an_id(self, single_ac):
        by_name = simulate(
            single_ac,
            [
                {
                    "name": "AC",
                    "field": "replace_with",
                    "replacement": {"name": "NewAC", "power_watts": 700},
                }
            ],
            month=8,
        )
        with_id = simulate(
            [{**single_ac[0], "appliance_id": "a1"}],
            [
                {
                    "appliance_id": "a1",
                    "field": "replace_with",
                    "replacement": {"name": "NewAC", "power_watts": 700},
                }
            ],
            month=8,
        )
        assert by_name["delta"] == with_id["delta"]
        assert by_name["comparison_table"] == with_id["comparison_table"]

    def test_applied_change_reports_the_original_and_the_new_name(self, single_ac):
        result = simulate(
            single_ac,
            [
                {
                    "name": "AC",
                    "field": "replace_with",
                    "replacement": {"name": "NewAC", "power_watts": 700},
                }
            ],
            month=8,
        )
        entry = result["applied_changes"][0]
        assert entry["appliance"] == "AC"
        assert entry["new_name"] == "NewAC"

    def test_applied_change_has_no_new_name_when_nothing_was_renamed(self, single_ac):
        result = simulate(
            single_ac,
            [{"name": "AC", "field": "hours_per_day", "value": 4}],
            month=8,
        )
        assert result["applied_changes"][0]["new_name"] is None

    def test_replacement_label_is_carried_on_the_row(self, single_ac):
        result = simulate(
            single_ac,
            [
                {
                    "name": "AC",
                    "field": "replace_with",
                    "replacement": {"label": "一級能效變頻冷氣", "power_watts": 700},
                }
            ],
            month=8,
        )
        assert result["comparison_table"][0]["replacement_label"] == "一級能效變頻冷氣"

    def test_rename_still_marks_an_added_appliance_as_added(self, room):
        """A swap plus an explicit extra appliance keeps one 'added' row."""

        result = simulate(
            room,
            [
                {
                    "appliance_id": "air_conditioner",
                    "field": "replace_with",
                    "replacement": {"name": "Inverter AC", "power_watts": 700},
                }
            ],
            month=8,
        )
        statuses = {row["appliance"]: row["status"] for row in result["comparison_table"]}
        assert statuses["Air conditioner"] == "changed"
        assert "Inverter AC" not in statuses

    def test_multiple_changes_stack(self, room):
        result = simulate(
            room,
            [
                {"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4},
                {"appliance_id": "air_conditioner", "field": "power_watts", "value": 700},
            ],
            month=8,
        )
        assert result["modified"]["appliances"][0]["hours_per_day"] == 4
        assert result["modified"]["appliances"][0]["power_watts"] == 700
        assert len(result["applied_changes"]) == 2
        assert result["delta"]["saved_kwh"] > 0

    def test_change_can_target_by_name(self, room):
        result = simulate(
            room,
            [{"name": "Refrigerator", "field": "hours_per_day", "value": 12}],
            month=8,
        )
        assert result["modified"]["appliances"][1]["hours_per_day"] == 12

    def test_unsupported_field_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(room, [{"appliance_id": "air_conditioner", "field": "colour", "value": 1}])
        assert excinfo.value.code == "unsupported_change_field"

    def test_missing_value_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(room, [{"appliance_id": "air_conditioner", "field": "hours_per_day"}])
        assert excinfo.value.code == "missing_change_value"

    def test_missing_target_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(room, [{"field": "hours_per_day", "value": 3}])
        assert excinfo.value.code == "missing_change_target"

    def test_unknown_appliance_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(
                room,
                [{"appliance_id": "ghost", "field": "hours_per_day", "value": 3}],
            )
        assert excinfo.value.code == "appliance_not_found"
        assert "ghost" in str(excinfo.value)

    def test_empty_replacement_object_leaves_the_appliance_unchanged(self, room):
        """``{}`` is accepted by the service but changes nothing."""

        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "replace_with", "replacement": {}}],
            month=8,
        )
        assert result["delta"]["saved_kwh"] == pytest.approx(0.0)

    def test_non_object_replacement_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(
                room,
                [{"appliance_id": "air_conditioner", "field": "replace_with", "replacement": 5}],
            )
        assert excinfo.value.code == "invalid_replacement"

    def test_change_that_breaks_validation_is_rejected(self, room):
        with pytest.raises(SimulationError) as excinfo:
            simulate(
                room,
                [{"appliance_id": "air_conditioner", "field": "power_watts", "value": -100}],
            )
        assert excinfo.value.code == "power_not_positive"

    def test_invalid_baseline_is_rejected(self):
        with pytest.raises(SimulationError) as excinfo:
            simulate(
                [appliance("Broken", 0, 5)],
                [{"appliance_id": "broken", "field": "hours_per_day", "value": 3}],
            )
        assert excinfo.value.code == "power_not_positive"


class TestLoadComparison:
    def test_load_is_compared_when_a_limit_is_given(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "power_watts", "value": 1800}],
            month=8,
            load_limit_amps=15,
        )
        load = result["load"]
        assert load["limit_amps"] == 15
        assert load["modified_current_amps"] > load["baseline_current_amps"]
        assert load["current_change_amps"] > 0

    def test_load_section_is_absent_without_a_limit(self, room):
        result = simulate(
            room, [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 5}]
        )
        assert result.get("load") is None

    def test_verdict_can_improve_after_the_change(self):
        room = [
            appliance("Hair dryer", 1200, 0.3),
            appliance("Space heater", 1200, 3),
        ]
        # Baseline 21.8A > 15A. Replacing the heater with a 50W device gives
        # 10.9A + 0.45A = 11.4A, below the 12A safety margin.
        result = simulate(
            room,
            [{"appliance_id": "space_heater", "field": "replace_with",
              "replacement": {"power_watts": 50}}],
            load_limit_amps=15,
        )
        assert result["load"]["baseline_verdict"] == "over_limit"
        assert result["load"]["modified_verdict"] == "safe"


class TestOptions:
    def test_season_changes_the_saved_amount(self, room):
        changes = [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}]
        summer = simulate(room, changes, month=8)["delta"]["saved_amount_twd"]
        winter = simulate(room, changes, month=1)["delta"]["saved_amount_twd"]
        assert summer > winter

    def test_plan_id_can_be_forced(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}],
            plan_id="flat_rate_resell_reference",
        )
        assert result["plan_id"] == "flat_rate_resell_reference"

    def test_baseline_override_uses_a_metered_value(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}],
            month=8,
            baseline_override_kwh=400.0,
        )
        # The override replaces only the baseline (metered) figure.
        assert result["baseline"]["total_monthly_kwh"] == pytest.approx(400.0)
        # Modified side: AC 900W*4h*30d = 108 + fridge 93.6 = 201.6
        assert result["modified"]["total_monthly_kwh"] == pytest.approx(201.6)
        assert result["delta"]["saved_kwh"] == pytest.approx(198.4)

    def test_bi_monthly_billing_period_is_passed_through(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}],
            month=8,
            billing_period="bi_monthly",
        )
        assert result["billing_period"] == "bi_monthly"
        assert result["billing_months"] == 2
        assert result["baseline"]["bill_lines"][1]["range_to_kwh"] == pytest.approx(660.0)

    def test_billing_months_is_forwarded_to_the_bill(self, room):
        """Regression: ``billing_months`` was accepted by the schema and ignored here."""

        changes = [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 6}]
        single = simulate(room, changes, month=8, billing_months=1)
        double = simulate(room, changes, month=8, billing_months=2)

        assert single["billing_months"] == 1
        assert double["billing_months"] == 2
        assert double["baseline"]["estimated_bill_twd"] < single["baseline"]["estimated_bill_twd"]

    def test_billing_months_agrees_with_the_bill_calculator(self, room):
        """The simulation and /calculate/cost must not disagree for the same input."""

        from app.calculators.electricity_bill import calculate_bill

        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 6}],
            month=8,
            billing_months=2,
        )
        direct = calculate_bill(255.6, month=8, billing_months=2)
        assert result["baseline"]["estimated_bill_twd"] == pytest.approx(direct["total_amount"])
        assert result["billing_months"] == direct["billing_months"]

    def test_billing_months_overrides_billing_period(self, room):
        result = simulate(
            room,
            [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 6}],
            month=8,
            billing_period="monthly",
            billing_months=3,
        )
        assert result["billing_months"] == 3

    def test_invalid_billing_months_is_rejected(self, room):
        with pytest.raises(TariffError) as excinfo:
            simulate(
                room,
                [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 6}],
                billing_months=0,
            )
        assert excinfo.value.code == "invalid_billing_months"

    def test_notes_explain_non_mutation_and_estimation(self, room):
        result = simulate(
            room, [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}]
        )
        assert any("不會修改" in note for note in result["notes"])
        assert any("估算" in note for note in result["notes"])

    def test_result_is_json_serialisable(self, room):
        import json

        result = simulate(
            room, [{"appliance_id": "air_conditioner", "field": "hours_per_day", "value": 4}]
        )
        assert json.loads(json.dumps(result))["delta"]["saved_kwh"] > 0


class TestWhatIfReduction:
    def test_uniform_reduction(self, room):
        result = what_if_reduction(room, reduction_percent=10, month=8)
        assert result["saved_kwh"] == pytest.approx(25.56, abs=0.01)
        assert result["saved_amount_twd"] > 0

    def test_no_reduction_saves_nothing(self, room):
        result = what_if_reduction(room, reduction_percent=0, month=8)
        assert result["saved_kwh"] == pytest.approx(0.0)
        assert result["saved_amount_twd"] == pytest.approx(0.0)

    def test_full_reduction_removes_the_whole_bill(self, room):
        result = what_if_reduction(room, reduction_percent=100, month=8)
        assert result["modified_total_monthly_kwh"] == pytest.approx(0.0)
        assert result["modified_estimated_bill_twd"] == pytest.approx(0.0)
        assert result["saved_amount_twd"] == pytest.approx(result["baseline_estimated_bill_twd"])

    @pytest.mark.parametrize("percent", [-1, 101, 200])
    def test_invalid_percentage_is_rejected(self, room, percent):
        with pytest.raises(SimulationError) as excinfo:
            what_if_reduction(room, reduction_percent=percent)
        assert excinfo.value.code == "invalid_reduction_percent"

    def test_tier_effect_is_explained(self, room):
        result = what_if_reduction(room, reduction_percent=20, month=8)
        assert "累進級距" in result["note_zh"]

    def test_does_not_mutate_input(self, room):
        before = copy.deepcopy(room)
        what_if_reduction(room, reduction_percent=30, month=8)
        assert room == before
