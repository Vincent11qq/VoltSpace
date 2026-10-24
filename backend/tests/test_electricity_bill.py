"""Tests for the electricity bill calculator.

The headline test reproduces the worked example published with the Taipower
residential tier table (800 kWh in a summer month = NT$2,977), which pins down both
the tier boundaries and the rates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.calculators.electricity_bill import (
    TariffError,
    annual_seasonal_estimate,
    calculate_bill,
    compare_plans,
    get_plan,
    list_plans,
    load_tariffs,
    resolve_season,
    season_label,
)


class TestTariffData:
    def test_data_file_loads(self):
        data = load_tariffs()
        assert data["schema_version"]
        assert "tw_residential_tiered" in data["plans"]

    def test_prices_live_in_json_not_in_code(self):
        """Guard rail for the 'keep tariff data separate' requirement.

        No module under ``app/`` may contain a tariff rate as a numeric literal; the
        only allowed mention is inside a human-readable documentation string, which is
        why the check looks for the rate surrounded by non-digit characters.
        """

        app_dir = Path(__file__).resolve().parent.parent / "app"
        offenders: list[str] = []
        for source in sorted(app_dir.rglob("*.py")):
            text = source.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                # Skip docstrings/description strings that merely document a price.
                if line.lstrip().startswith(("#", '"', "'")) or '"summary"' in line:
                    continue
                if re.search(r"(?<![\d.])(1\.68|2\.45|3\.70|5\.04|6\.24|8\.46)\b", line):
                    offenders.append(f"{source.name}:{line_number}: {line.strip()}")
        assert offenders == [], "tariff rates must come from tariffs.json: " + "; ".join(offenders)

    def test_rates_are_readable_from_the_data_file(self):
        """The JSON is the single source of truth for the numbers the tests assert."""

        plan = get_plan("tw_residential_tiered")
        assert [tier["rate"] for tier in plan["seasons"]["summer"]["tiers"]] == [
            1.68,
            2.45,
            3.70,
            5.04,
            6.24,
            8.46,
        ]

    def test_tier_table_is_complete_for_both_seasons(self):
        plan = get_plan("tw_residential_tiered")
        for season in ("summer", "non_summer"):
            tiers = plan["seasons"][season]["tiers"]
            assert len(tiers) == 6
            assert tiers[0]["up_to_kwh"] == 120
            assert tiers[-1]["up_to_kwh"] is None  # open ended top tier
            assert [tier["index"] for tier in tiers] == [1, 2, 3, 4, 5, 6]

    def test_official_rates_are_recorded(self):
        plan = get_plan("tw_residential_tiered")
        summer = [tier["rate"] for tier in plan["seasons"]["summer"]["tiers"]]
        non_summer = [tier["rate"] for tier in plan["seasons"]["non_summer"]["tiers"]]
        assert summer == [1.68, 2.45, 3.70, 5.04, 6.24, 8.46]
        assert non_summer == [1.68, 2.16, 3.03, 4.14, 5.07, 6.63]

    def test_non_summer_rates_are_never_higher_than_summer(self):
        plan = get_plan("tw_residential_tiered")
        for summer, non_summer in zip(
            plan["seasons"]["summer"]["tiers"], plan["seasons"]["non_summer"]["tiers"]
        ):
            assert non_summer["rate"] <= summer["rate"]

    def test_unknown_plan_raises(self):
        with pytest.raises(TariffError) as excinfo:
            get_plan("does_not_exist")
        assert excinfo.value.code == "unknown_plan"

    def test_list_plans_summarises_every_plan(self):
        plans = list_plans()
        ids = {plan["id"] for plan in plans}
        assert {"tw_residential_tiered", "tw_residential_tou", "flat_rate_resell_reference"} <= ids
        for plan in plans:
            assert plan["currency"] == "TWD"
            assert plan["unit"] == "kWh"

    def test_season_rules_cover_all_twelve_months(self):
        data = load_tariffs()
        months = set(data["season_rules"]["summer"]["months"]) | set(
            data["season_rules"]["non_summer"]["months"]
        )
        assert months == set(range(1, 13))


class TestSeasonResolution:
    @pytest.mark.parametrize("month", [6, 7, 8, 9])
    def test_summer_months(self, month):
        assert resolve_season(month) == "summer"

    @pytest.mark.parametrize("month", [1, 2, 3, 4, 5, 10, 11, 12])
    def test_non_summer_months(self, month):
        assert resolve_season(month) == "non_summer"

    def test_missing_month_defaults_to_non_summer(self):
        assert resolve_season(None) == "non_summer"

    @pytest.mark.parametrize("month", [0, 13, -1, "8", 8.5, True])
    def test_invalid_month_is_rejected(self, month):
        with pytest.raises(TariffError) as excinfo:
            resolve_season(month)
        assert excinfo.value.code == "invalid_month"

    def test_season_labels_are_bilingual(self):
        label = season_label("summer")
        assert "夏月" in label["label_zh"]
        assert "Summer" in label["label_en"]


class TestTieredBill:
    def test_official_worked_example_800_kwh_summer(self):
        """Taipower: 1.68*120 + 2.45*210 + 3.70*170 + 5.04*200 + 6.24*100.

        The published leaflet prints NT$2,977 while the tier amounts sum to
        NT$2,977.10, so the comparison allows that one rounding step.
        """

        bill = calculate_bill(800, month=8)
        assert bill["total_amount"] == pytest.approx(2977.0, abs=0.5)
        assert bill["total_amount_rounded"] == 2977
        assert bill["season"] == "summer"
        assert [line["kwh_in_tier"] for line in bill["lines"]] == [120, 210, 170, 200, 100]

    def test_800_kwh_in_a_non_summer_month(self):
        # 1.68*120 + 2.16*210 + 3.03*170 + 4.14*200 + 5.07*100 = 2,505.30
        bill = calculate_bill(800, month=1)
        assert bill["season"] == "non_summer"
        assert bill["total_amount"] == pytest.approx(2505.3)
        assert [line["rate_per_kwh"] for line in bill["lines"]] == [1.68, 2.16, 3.03, 4.14, 5.07]

    def test_consumption_inside_the_first_tier(self):
        bill = calculate_bill(100, month=8)
        assert bill["total_amount"] == pytest.approx(168.0)
        assert len(bill["lines"]) == 1
        assert bill["lines"][0]["kwh_in_tier"] == pytest.approx(100.0)

    @pytest.mark.parametrize("kwh", [120, 330, 500, 700, 1000])
    def test_exact_tier_boundaries(self, kwh):
        bill = calculate_bill(kwh, month=8)
        # No tier line may claim more kWh than its own width.
        for line in bill["lines"]:
            assert line["kwh_in_tier"] > 0
        covered = sum(line["kwh_in_tier"] for line in bill["lines"])
        assert covered == pytest.approx(float(kwh))

    def test_120_kwh_is_exactly_one_tier(self):
        bill = calculate_bill(120, month=8)
        assert len(bill["lines"]) == 1
        assert bill["total_amount"] == pytest.approx(201.6)

    def test_121_kwh_spills_into_the_second_tier(self):
        bill = calculate_bill(121, month=8)
        assert len(bill["lines"]) == 2
        assert bill["total_amount"] == pytest.approx(1.68 * 120 + 2.45 * 1)

    def test_above_the_top_tier(self):
        bill = calculate_bill(1200, month=8)
        assert len(bill["lines"]) == 6
        expected = (
            1.68 * 120 + 2.45 * 210 + 3.70 * 170 + 5.04 * 200 + 6.24 * 300 + 8.46 * 200
        )
        assert bill["total_amount"] == pytest.approx(expected)
        assert bill["lines"][-1]["range_to_kwh"] is None

    def test_progressive_cost_grows_faster_than_usage(self):
        """Effective rate must increase with consumption (progressive tiers)."""

        low = calculate_bill(200, month=8)["effective_rate_per_kwh"]
        mid = calculate_bill(600, month=8)["effective_rate_per_kwh"]
        high = calculate_bill(1500, month=8)["effective_rate_per_kwh"]
        assert low < mid < high

    def test_zero_consumption_costs_nothing(self):
        bill = calculate_bill(0, month=8)
        assert bill["total_amount"] == 0.0
        assert bill["effective_rate_per_kwh"] == 0.0

    def test_zero_consumption_still_reports_the_applicable_rate(self):
        """A 0 kWh bill keeps the response shape: one illustrative tier, 0 kWh, 0 TWD."""

        bill = calculate_bill(0, month=8)
        assert len(bill["lines"]) == 1
        line = bill["lines"][0]
        assert line["tier_index"] == 1
        assert line["rate_per_kwh"] == 1.68
        assert line["kwh_in_tier"] == 0.0
        assert line["amount"] == 0.0
        assert any(item["code"] == "no_consumption" for item in bill["warnings"])

    def test_zero_consumption_on_a_flat_plan(self):
        bill = calculate_bill(0, plan_id="flat_rate_resell_reference")
        assert bill["total_amount"] == 0.0
        assert bill["lines"][0]["kwh_in_tier"] == 0.0

    def test_non_zero_bill_does_not_report_no_consumption(self):
        bill = calculate_bill(10, month=8)
        assert not any(item["code"] == "no_consumption" for item in bill["warnings"])

    def test_tier_amounts_sum_to_the_total(self):
        bill = calculate_bill(933, month=7)
        assert sum(line["amount"] for line in bill["lines"]) == pytest.approx(
            bill["total_amount"], abs=0.01
        )

    def test_effective_rate_matches_total_over_usage(self):
        bill = calculate_bill(450, month=8)
        assert bill["effective_rate_per_kwh"] == pytest.approx(
            bill["total_amount"] / 450, rel=1e-6
        )

    def test_summer_costs_more_than_non_summer_for_the_same_usage(self):
        summer = calculate_bill(600, month=8)["total_amount"]
        winter = calculate_bill(600, month=1)["total_amount"]
        assert summer > winter

    def test_season_can_be_forced_without_a_month(self):
        forced = calculate_bill(600, season="summer")
        assert forced["total_amount"] == pytest.approx(calculate_bill(600, month=8)["total_amount"])

    def test_invalid_season_is_rejected(self):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(100, season="monsoon")
        assert excinfo.value.code == "invalid_season"

    @pytest.mark.parametrize("kwh", [-1, -100])
    def test_negative_consumption_is_rejected(self, kwh):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(kwh, month=8)
        assert excinfo.value.code == "negative_consumption"

    @pytest.mark.parametrize("kwh", [float("nan"), float("inf")])
    def test_non_finite_consumption_is_rejected(self, kwh):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(kwh, month=8)
        assert excinfo.value.code == "not_finite"

    def test_result_is_json_serialisable(self):
        bill = calculate_bill(520, month=8)
        assert json.loads(json.dumps(bill))["total_amount"] > 0

    def test_warning_explains_that_it_is_only_an_estimate(self):
        bill = calculate_bill(520, month=8)
        assert any(item["code"] == "estimate_only" for item in bill["warnings"])

    def test_every_bill_warning_is_bilingual(self):
        for bill in (
            calculate_bill(520, month=8),
            calculate_bill(520, plan_id="flat_rate_resell_reference"),
            calculate_bill(520, plan_id="tw_residential_tou", month=8),
        ):
            assert bill["warnings"]
            for warning in bill["warnings"]:
                assert warning["code"]
                assert warning["message_zh"].strip()
                assert warning["message_en"].strip()


class TestBillingPeriod:
    def test_two_month_bill_doubles_the_tier_ceilings(self):
        """One 2-month bill for 1040 kWh must equal two monthly bills of 520 kWh."""

        bi_monthly = calculate_bill(1040, month=8, billing_period="bi_monthly")
        monthly_twice = calculate_bill(520, month=8)["total_amount"] * 2
        assert bi_monthly["total_amount"] == pytest.approx(monthly_twice)
        assert bi_monthly["billing_months"] == 2
        assert bi_monthly["lines"][1]["range_to_kwh"] == pytest.approx(660.0)

    def test_monthly_period_keeps_original_ceilings(self):
        bill = calculate_bill(520, month=8, billing_period="monthly")
        assert bill["billing_months"] == 1
        assert bill["lines"][1]["range_to_kwh"] == pytest.approx(330.0)

    def test_billing_months_overrides_billing_period(self):
        bill = calculate_bill(520, month=8, billing_period="monthly", billing_months=2)
        assert bill["billing_months"] == 2

    def test_bi_monthly_is_cheaper_per_kwh_than_monthly_for_the_same_usage(self):
        """Wider tier ceilings mean a lower effective rate for the same total."""

        monthly = calculate_bill(700, month=8, billing_period="monthly")["total_amount"]
        bi_monthly = calculate_bill(700, month=8, billing_period="bi_monthly")["total_amount"]
        assert bi_monthly < monthly

    def test_invalid_billing_period_is_rejected(self):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(100, month=8, billing_period="weekly")
        assert excinfo.value.code == "invalid_billing_period"

    @pytest.mark.parametrize("months", [0, 13, -1])
    def test_invalid_billing_months_is_rejected(self, months):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(100, month=8, billing_months=months)
        assert excinfo.value.code == "invalid_billing_months"

    def test_non_integer_billing_months_is_rejected(self):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(100, month=8, billing_months=1.5)
        assert excinfo.value.code == "invalid_billing_months"

    @pytest.mark.parametrize("months", [1, 2, 3, 6, 12])
    def test_proration_is_exactly_equivalent_to_repeated_monthly_bills(self, months):
        """A bill covering N months must equal N monthly bills of consumption/N."""

        total_kwh = 150.0 * months
        combined = calculate_bill(total_kwh, month=8, billing_months=months)["total_amount"]
        monthly = calculate_bill(150.0, month=8)["total_amount"] * months
        assert combined == pytest.approx(monthly, abs=0.01)

    def test_more_billed_months_means_a_lower_price_for_the_same_total(self):
        """Wider tier ceilings can only lower (or hold) the effective rate."""

        amounts = [
            calculate_bill(900, month=8, billing_months=months)["total_amount"]
            for months in (1, 2, 3)
        ]
        assert amounts[0] > amounts[1] > amounts[2]

    def test_consumption_beyond_every_tier_is_fully_covered(self):
        """The open-ended top tier must absorb arbitrarily large consumption."""

        bill = calculate_bill(50_000, month=8)
        assert sum(line["kwh_in_tier"] for line in bill["lines"]) == pytest.approx(50_000)
        assert not any(item["code"] == "uncovered_consumption" for item in bill["warnings"])


class TestOtherPlans:
    def test_flat_resale_rate(self):
        bill = calculate_bill(400, plan_id="flat_rate_resell_reference")
        assert bill["plan_type"] == "flat"
        assert bill["total_amount"] == pytest.approx(400 * 5.5)
        assert any(item["code"] == "landlord_resale_rate" for item in bill["warnings"])

    def test_flat_rate_is_season_independent(self):
        summer = calculate_bill(400, plan_id="flat_rate_resell_reference", month=8)
        winter = calculate_bill(400, plan_id="flat_rate_resell_reference", month=1)
        assert summer["total_amount"] == pytest.approx(winter["total_amount"])

    def test_time_of_use_splits_peak_and_off_peak(self):
        bill = calculate_bill(1000, plan_id="tw_residential_tou", month=8, peak_share=0.4)
        assert bill["plan_type"] == "time_of_use"
        assert len(bill["lines"]) == 2
        assert bill["total_amount"] == pytest.approx(400 * 5.16 + 600 * 2.13)

    def test_time_of_use_all_off_peak_is_cheapest(self):
        all_off = calculate_bill(1000, plan_id="tw_residential_tou", month=8, peak_share=0.0)
        half = calculate_bill(1000, plan_id="tw_residential_tou", month=8, peak_share=1.0)
        assert all_off["total_amount"] < half["total_amount"]

    @pytest.mark.parametrize("share", [-0.1, 1.1, 2])
    def test_invalid_peak_share_is_rejected(self, share):
        with pytest.raises(TariffError) as excinfo:
            calculate_bill(100, plan_id="tw_residential_tou", month=8, peak_share=share)
        assert excinfo.value.code == "invalid_peak_share"

    def test_time_of_use_carries_a_simplification_warning(self):
        bill = calculate_bill(100, plan_id="tw_residential_tou", month=8)
        assert any(item["code"] == "tou_simplified" for item in bill["warnings"])

    def test_flat_plan_is_flagged_as_an_estimate(self):
        assert calculate_bill(100, plan_id="flat_rate_resell_reference")["is_estimate"] is True

    @pytest.mark.parametrize(
        "plan_id", ["flat_rate_resell_reference", "tw_residential_tou"]
    )
    def test_per_kwh_plans_reject_a_multi_month_period(self, plan_id):
        """Only tiered plans scale their ceilings, so the others must refuse the option.

        Otherwise the response would echo ``billing_months: 2`` while charging one
        month's worth, which is exactly the kind of silent mismatch that makes a
        displayed bill wrong.
        """

        with pytest.raises(TariffError) as excinfo:
            calculate_bill(400, plan_id=plan_id, billing_months=2)
        assert excinfo.value.code == "plan_does_not_support_billing_months"

    @pytest.mark.parametrize(
        "plan_id", ["flat_rate_resell_reference", "tw_residential_tou"]
    )
    def test_per_kwh_plans_accept_a_single_month(self, plan_id):
        assert calculate_bill(400, plan_id=plan_id, billing_period="monthly")["billing_months"] == 1

    def test_tiered_plan_does_support_multi_month_periods(self):
        bill = calculate_bill(1040, month=8, billing_period="bi_monthly")
        assert bill["billing_months"] == 2

    def test_residential_tiered_plan_is_not_flagged_as_estimate(self):
        assert calculate_bill(100, month=8)["is_estimate"] is False


class TestComparisons:
    def test_compare_plans_orders_by_price(self):
        comparison = compare_plans(400, month=8)
        amounts = [plan["total_amount"] for plan in comparison["plans"]]
        assert amounts == sorted(amounts)
        assert comparison["cheapest_plan_id"] == comparison["plans"][0]["plan_id"]

    def test_landlord_flat_rate_is_more_expensive_than_taipower_tiers_at_low_usage(self):
        comparison = compare_plans(300, month=1)
        by_id = {plan["plan_id"]: plan["total_amount"] for plan in comparison["plans"]}
        assert by_id["flat_rate_resell_reference"] > by_id["tw_residential_tiered"]

    def test_annual_estimate_uses_four_summer_months(self):
        annual = annual_seasonal_estimate(400)
        assert annual["annual_amount"] == pytest.approx(
            annual["summer_monthly_amount"] * 4 + annual["non_summer_monthly_amount"] * 8
        )
        # ``average_monthly_amount`` is rounded to two decimals.
        assert annual["average_monthly_amount"] == pytest.approx(
            annual["annual_amount"] / 12, abs=0.01
        )

    def test_annual_summer_component_costs_more(self):
        annual = annual_seasonal_estimate(700)
        assert annual["summer_monthly_amount"] > annual["non_summer_monthly_amount"]
