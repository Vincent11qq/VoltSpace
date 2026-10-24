"""Tests for the rule-based recommendation service."""

from __future__ import annotations

import pytest

from app.services.recommendations import (
    catalog_summary,
    generate_recommendations,
    load_appliance_catalog,
)


def appliance(name: str, watts: float, hours: float, days: int = 30, **extra) -> dict:
    payload = {
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
        appliance("冷氣機", 900, 6, voltage=220),
        appliance("冰箱", 130, 24),
        appliance("桌上型電腦", 250, 6),
    ]


def ids(result: dict) -> set[str]:
    return {item["id"] for item in result["recommendations"]}


def find(result: dict, recommendation_id: str) -> dict:
    for item in result["recommendations"]:
        if item["id"] == recommendation_id:
            return item
    raise AssertionError(f"{recommendation_id} not in {sorted(ids(result))}")


class TestCatalog:
    def test_catalog_loads(self):
        catalog = load_appliance_catalog()
        assert catalog["appliances"]
        assert catalog["defaults"]["days_per_month"] == 30

    def test_summary_is_json_ready_and_complete(self):
        summary = catalog_summary()
        assert summary["count"] == len(summary["appliances"])
        for entry in summary["appliances"]:
            assert entry["typical_power_watts"] > 0
            assert entry["power_range_watts"][0] <= entry["typical_power_watts"]
            assert entry["power_range_watts"][1] >= entry["typical_power_watts"]
            assert entry["voltage_v"] in (110, 220)

    def test_high_power_appliances_are_marked(self):
        by_key = {entry["key"]: entry for entry in catalog_summary()["appliances"]}
        assert by_key["electric_water_heater"]["is_high_power"] is True
        assert by_key["hair_dryer"]["is_high_power"] is True
        assert by_key["lighting"]["is_high_power"] is False

    def test_always_on_appliances_are_marked(self):
        by_key = {entry["key"]: entry for entry in catalog_summary()["appliances"]}
        assert by_key["refrigerator"]["always_on"] is True
        assert by_key["air_conditioner"]["always_on"] is False


class TestTopConsumers:
    def test_identifies_the_highest_consuming_appliances(self, room):
        result = generate_recommendations(room, month=8, top_n=2)
        names = [entry["appliance"] for entry in result["top_consumers"]]
        assert names == ["冷氣機", "冰箱"]
        assert result["top_consumers"][0]["monthly_kwh"] == pytest.approx(162.0)
        assert result["top_consumers"][0]["share_of_total_percent"] > 50

    def test_top_consumer_recommendation_is_generated(self, room):
        result = generate_recommendations(room, month=8)
        top = [item for item in result["recommendations"] if item["id"].startswith("top_consumer")]
        assert top
        assert top[0]["severity"] == "high"
        assert "占全家總用電" in top[0]["reason_zh"]

    def test_totals_match_the_consumption_calculator(self, room):
        from app.calculators.consumption import calculate_consumption

        expected = calculate_consumption(room)["total_monthly_kwh"]
        result = generate_recommendations(room, month=8)
        assert result["total_monthly_kwh"] == pytest.approx(expected, abs=0.01)

    def test_threshold_is_exposed_to_the_frontend(self, room):
        assert generate_recommendations(room, month=8)["high_consumption_threshold_percent"] == 20.0


class TestRules:
    def test_air_conditioner_hours_rule_fires_and_estimates_a_saving(self):
        # 9 h/day AC: the "over 8 hours" rule should apply.
        result = generate_recommendations([appliance("冷氣機", 900, 9, voltage=220)], month=8)
        item = find(result, "ac_hours_high")
        assert item["appliance"] == "冷氣機"
        assert item["estimated_monthly_saving_kwh"] > 0
        assert item["estimated_monthly_saving_twd"] > 0
        assert "假設每日可減少" in item["assumption_zh"]
        assert item["reason_zh"]
        assert item["suggestion_zh"]

    def test_air_conditioner_saving_is_capped_at_two_hours(self):
        # 12 h/day * 0.2 = 2.4 h, but reduction_cap_hours caps it at 2 h.
        result = generate_recommendations([appliance("冷氣機", 1000, 12, voltage=220)], month=8)
        item = find(result, "ac_hours_high")
        expected = (1000 / 1000) * 2 * 30  # 2 hours removed * 30 days
        assert item["estimated_monthly_saving_kwh"] == pytest.approx(expected)

    def test_air_conditioner_hours_rule_does_not_fire_below_threshold(self):
        result = generate_recommendations([appliance("冷氣機", 900, 6, voltage=220)], month=8)
        assert "ac_hours_high" not in ids(result)

    def test_high_power_air_conditioner_rule_fires(self):
        # Typical is 900 W, so 1400 W is a ratio of 1.56 >= 1.3.
        result = generate_recommendations([appliance("冷氣機", 1400, 4, voltage=220)], month=8)
        item = find(result, "ac_power_high")
        assert "汰換" in item["suggestion_zh"]
        assert item["estimated_monthly_saving_kwh"] > 0

    def test_high_power_rule_does_not_fire_for_a_typical_unit(self):
        result = generate_recommendations([appliance("冷氣機", 900, 4, voltage=220)], month=8)
        assert "ac_power_high" not in ids(result)

    def test_refrigerator_always_on_rule_fires(self):
        result = generate_recommendations([appliance("冰箱", 130, 24)], month=8)
        item = find(result, "fridge_always_on")
        assert item["estimated_monthly_saving_kwh"] == pytest.approx(93.6 * 0.1, abs=0.01)

    def test_electric_pot_long_use_rule(self):
        result = generate_recommendations([appliance("電子鍋", 700, 4)], month=8)
        item = find(result, "cooker_hours_high")
        assert item["estimated_monthly_saving_kwh"] > 0
        assert item["severity"] == "medium"

    def test_washing_machine_frequency_rule(self):
        result = generate_recommendations([appliance("洗衣機", 500, 1, days=25)], month=8)
        item = find(result, "washer_days_high")
        assert item["estimated_monthly_saving_kwh"] > 0

    def test_lighting_long_hours_rule(self):
        result = generate_recommendations([appliance("照明", 20, 12)], month=8)
        item = find(result, "lighting_long_hours")
        assert item["estimated_monthly_saving_kwh"] > 0

    def test_matching_is_case_and_space_insensitive(self, room):
        result = generate_recommendations(
            [appliance("  AIR CONDITIONER ", 900, 9, voltage=220)], month=8
        )
        assert "ac_hours_high" in ids(result)

    def test_chinese_and_english_names_both_match(self):
        english = generate_recommendations([appliance("Refrigerator", 130, 24)], month=8)
        chinese = generate_recommendations([appliance("冰箱", 130, 24)], month=8)
        assert "fridge_always_on" in ids(english)
        assert "fridge_always_on" in ids(chinese)

    def test_explicit_category_selects_the_catalogue_entry(self):
        result = generate_recommendations(
            [appliance("My cooler", 130, 24, category="refrigerator")], month=8
        )
        assert "fridge_always_on" in ids(result)

    @pytest.mark.parametrize(
        "name,expected_key",
        [
            ("冰箱", "refrigerator"),
            ("電冰箱", "refrigerator"),
            ("小冰箱", "refrigerator"),
            ("冷氣機", "air_conditioner"),
            ("變頻冷氣機", "air_conditioner"),
            ("電視", "tv"),
            ("電視機", "tv"),
            ("照明", "lighting"),
            ("房間照明", "lighting"),
            ("吹風機", "hair_dryer"),
            ("洗衣機", "washing_machine"),
            ("微波爐", "microwave"),
            ("電熱水器", "electric_water_heater"),
            ("Refrigerator", "refrigerator"),
            ("Bedroom air conditioner", "air_conditioner"),
        ],
    )
    def test_chinese_and_decorated_names_resolve_to_the_catalogue(self, name, expected_key):
        """Regression: a name merely containing an alias must still match the catalogue.

        ``電冰箱`` contains ``冰箱``; the old implementation returned early from the exact
        alias loop and never reached the substring pass, so these all fell back to generic
        advice only.
        """

        result = generate_recommendations([appliance(name, 130, 24)], month=8)
        matched = {entry["matched_catalog_key"] for entry in result["per_appliance"]}
        assert expected_key in matched

    def test_generic_chinese_name_still_gets_specific_advice(self):
        """Only the name-based ids may differ (``top_consumer_*`` embeds the name)."""

        plain = generate_recommendations([appliance("冰箱", 130, 24)], month=8)
        decorated = generate_recommendations([appliance("電冰箱", 130, 24)], month=8)

        def rule_ids(result: dict) -> set[str]:
            return {item["id"] for item in result["recommendations"] if not item["id"].startswith("top_consumer")}

        assert rule_ids(plain) == rule_ids(decorated)
        assert {"fridge_always_on", "swap_refrigerator"} <= rule_ids(decorated)

    def test_unknown_name_is_not_force_matched(self):
        result = generate_recommendations([appliance("神祕家電", 100, 10)], month=8)
        assert result["per_appliance"][0]["matched_catalog_key"] is None

    def test_generic_rule_for_an_unknown_appliance(self):
        result = generate_recommendations([appliance("Mystery box", 100, 10)], month=8)
        generic = [item for item in result["recommendations"] if item["id"].startswith("generic")]
        assert generic
        assert generic[0]["confidence"] == "low"

    def test_unknown_appliance_with_short_usage_gets_no_generic_rule(self):
        # The unknown appliance is a small share of the household (about 10%), so
        # neither the top-consumer rule nor the long-hours generic rule applies.
        result = generate_recommendations(
            [appliance("Mystery box", 100, 2), appliance("電熱水器", 1000, 24, voltage=220)],
            month=8,
        )
        assert not any(item["id"].startswith("generic") for item in result["recommendations"])


class TestAdviceOnlyRules:
    def test_hair_dryer_gives_safety_advice_without_a_saving_claim(self):
        result = generate_recommendations([appliance("吹風機", 1200, 0.3)], month=8)
        item = find(result, "hair_dryer_load")
        assert item["advice_only"] is True
        assert item["estimated_monthly_saving_kwh"] == 0.0
        assert item["estimated_monthly_saving_twd"] == 0.0
        assert "跳電" in item["reason_zh"] or "電流" in item["reason_zh"]
        assert "未估算節省度數" in item["assumption_zh"]

    def test_electric_water_heater_appliance_rule_carries_its_own_saving(self):
        # This rule declares reduction_ratio 0.15, so it is a saving claim, not
        # advice-only: 4000W * 1h * 30d = 120 kWh base, 15% of it saved.
        result = generate_recommendations([appliance("電熱水器", 4000, 1, voltage=220)], month=8)
        item = find(result, "water_heater_high_power")
        assert item["severity"] == "high"
        assert item["priority"] == 1
        assert item["rule_id"] == "water_heater_high_power"
        assert item.get("advice_only") is None
        assert item["estimated_monthly_saving_kwh"] == pytest.approx(120 * 0.15)
        assert "迴路" in item["suggestion_zh"]


class TestPurchaseAdvice:
    def test_efficient_alternative_is_offered_for_a_high_power_ac(self):
        result = generate_recommendations([appliance("冷氣機", 1400, 8, voltage=220)], month=8)
        swap = find(result, "swap_air_conditioner")
        assert swap["is_purchase_advice"] is True
        assert swap["alternative_power_watts"] == 700
        assert "一級能效變頻冷氣" in swap["title_zh"]
        assert swap["estimated_monthly_saving_kwh"] > 0

    def test_high_efficiency_appliance_gets_no_swap_advice(self):
        # Already at/below the efficient alternative's rating.
        result = generate_recommendations([appliance("冷氣機", 600, 6, voltage=220)], month=8)
        assert "swap_air_conditioner" not in ids(result)

    def test_swap_saving_uses_the_alternative_power(self):
        result = generate_recommendations([appliance("冷氣機", 1400, 8, voltage=220)], month=8)
        swap = find(result, "swap_air_conditioner")
        expected = ((1400 - 700) / 1000) * 8 * 30
        assert swap["estimated_monthly_saving_kwh"] == pytest.approx(expected, abs=0.01)
        assert "使用時數" in swap["assumption_zh"]


class TestSavingAggregation:
    def test_headline_total_counts_only_the_best_suggestion_per_appliance(self, room):
        result = generate_recommendations(room, month=8)
        best: dict[str, float] = {}
        for item in result["recommendations"]:
            best[item["appliance"]] = max(
                best.get(item["appliance"], 0.0), item["estimated_monthly_saving_kwh"]
            )
        assert result["total_potential_monthly_saving_kwh"] == pytest.approx(
            sum(best.values()), abs=0.01
        )

    def test_comprehensive_total_is_the_sum_of_all_suggestions(self, room):
        result = generate_recommendations(room, month=8)
        assert result["comprehensive_monthly_saving_kwh"] == pytest.approx(
            sum(item["estimated_monthly_saving_kwh"] for item in result["recommendations"]),
            abs=0.01,
        )
        assert result["comprehensive_monthly_saving_twd"] == pytest.approx(
            sum(item["estimated_monthly_saving_twd"] for item in result["recommendations"]),
            abs=0.01,
        )

    def test_comprehensive_total_is_at_least_the_headline_total(self, room):
        result = generate_recommendations(room, month=8)
        assert result["comprehensive_monthly_saving_kwh"] >= result[
            "total_potential_monthly_saving_kwh"
        ]

    def test_overlapping_appliance_advice_is_not_double_counted(self):
        """An inefficient AC triggers "use less" and "buy efficient" at once."""

        result = generate_recommendations(
            [appliance("冷氣機", 1400, 9, voltage=220)], month=8
        )
        ac_savings = [
            item["estimated_monthly_saving_kwh"]
            for item in result["recommendations"]
            if item["appliance"] == "冷氣機" and item["estimated_monthly_saving_kwh"] > 0
        ]
        assert len(ac_savings) >= 2  # overlapping advice exists
        assert result["total_potential_monthly_saving_kwh"] == pytest.approx(
            max(ac_savings), abs=0.01
        )
        assert result["comprehensive_monthly_saving_kwh"] == pytest.approx(
            sum(ac_savings), abs=0.01
        )

    def test_aggregation_note_is_exposed(self, room):
        result = generate_recommendations(room, month=8)
        assert "重複" in result["aggregation_note_zh"]

    def test_annual_saving_is_twelve_times_the_monthly_saving(self, room):
        result = generate_recommendations(room, month=8)
        assert result["total_potential_annual_saving_twd"] == pytest.approx(
            result["total_potential_monthly_saving_twd"] * 12, abs=0.05
        )

    def test_potential_percentage_is_reported(self, room):
        result = generate_recommendations(room, month=8)
        assert 0 < result["potential_saving_percent_of_usage"] <= 100

    def test_savings_never_exceed_total_usage_implausibly(self, room):
        result = generate_recommendations(room, month=8)
        assert result["total_potential_monthly_saving_kwh"] < result["total_monthly_kwh"]

    def test_summer_savings_are_worth_more_than_winter_savings(self, room):
        summer = generate_recommendations(room, month=8)["total_potential_monthly_saving_twd"]
        winter = generate_recommendations(room, month=1)["total_potential_monthly_saving_twd"]
        assert summer > winter

    def test_max_recommendations_is_respected(self, room):
        result = generate_recommendations(room, month=8, max_recommendations=2)
        assert len(result["recommendations"]) <= 2
        assert result["recommendation_count"] <= 2

    def test_recommendations_are_deduplicated(self, room):
        result = generate_recommendations(room, month=8)
        keys = [item["recommendation_key"] for item in result["recommendations"]]
        assert len(keys) == len(set(keys))
        pairs = [(item["appliance"], item["id"]) for item in result["recommendations"]]
        assert len(pairs) == len(set(pairs))

    def test_two_identical_appliances_both_receive_advice(self):
        """Regression: dedup keyed on the rule id alone dropped the second appliance."""

        result = generate_recommendations(
            [
                appliance("冷氣機", 900, 9, voltage=220, appliance_id="a1"),
                appliance("冷氣機", 900, 12, voltage=220, appliance_id="a2"),
            ],
            month=8,
        )
        matching = [item for item in result["recommendations"] if item["id"] == "ac_hours_high"]
        assert len(matching) == 2, [item["id"] for item in result["recommendations"]]
        # Each carries its own context, not the other appliance's hours.
        assumptions = sorted(item["assumption_zh"] for item in matching)
        assert any("原 9.0 小時" in text for text in assumptions)
        assert any("原 12.0 小時" in text for text in assumptions)
        # And the unique keys differ.
        assert len({item["recommendation_key"] for item in matching}) == 2

    def test_stable_rule_id_is_preserved_alongside_the_unique_key(self):
        result = generate_recommendations(
            [
                appliance("冷氣機", 900, 9, voltage=220, appliance_id="a1"),
                appliance("冷氣機", 900, 12, voltage=220, appliance_id="a2"),
            ],
            month=8,
        )
        matching = [item for item in result["recommendations"] if item["id"] == "ac_hours_high"]
        assert matching
        keys = {item["recommendation_key"] for item in matching}
        # The unique key combines the stable rule id with the appliance identity.
        assert keys == {"ac_hours_high::a1", "ac_hours_high::a2"}
        assert {item["appliance_key"] for item in matching} == {"a1", "a2"}

    def test_appliance_key_falls_back_to_position_when_id_is_absent(self):
        result = generate_recommendations(
            [
                appliance("冷氣機", 900, 9, voltage=220),
                appliance("冷氣機", 900, 12, voltage=220),
            ],
            month=8,
        )
        matching = [item for item in result["recommendations"] if item["id"] == "ac_hours_high"]
        assert len(matching) == 2
        assert len({item["appliance_key"] for item in matching}) == 2

    def test_headline_total_counts_same_named_appliances_separately(self):
        """Regression: grouping savings by name collapsed two identical appliances."""

        one = generate_recommendations(
            [appliance("冷氣機", 900, 12, voltage=220, appliance_id="a1")], month=8
        )
        two = generate_recommendations(
            [
                appliance("冷氣機", 900, 12, voltage=220, appliance_id="a1"),
                appliance("冷氣機", 900, 12, voltage=220, appliance_id="a2"),
            ],
            month=8,
        )
        assert two["total_potential_monthly_saving_kwh"] > one["total_potential_monthly_saving_kwh"]

    def test_ranking_puts_high_severity_first(self, room):
        result = generate_recommendations(room, month=8)
        severities = [item["severity"] for item in result["recommendations"]]
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        assert severities == sorted(severities, key=lambda value: order[value])

    def test_every_recommendation_has_a_reason_and_suggestion(self, room):
        result = generate_recommendations(room, month=8)
        for item in result["recommendations"]:
            assert item["reason_zh"].strip()
            assert item["suggestion_zh"].strip()
            assert item["title_zh"].strip()
            assert item["assumption_zh"].strip()
            assert item["confidence"] in ("high", "medium", "low")

    def test_per_appliance_report_covers_every_input(self, room):
        result = generate_recommendations(room, month=8)
        assert len(result["per_appliance"]) == 3
        assert all(entry["matched_catalog_key"] for entry in result["per_appliance"])

    def test_per_appliance_counts_match_the_returned_list(self, room):
        """The summary must not disagree with the recommendations it summarises."""

        result = generate_recommendations(room, month=8)
        counted: dict[str, int] = {}
        for item in result["recommendations"]:
            counted[item["appliance_key"]] = counted.get(item["appliance_key"], 0) + 1
        for entry in result["per_appliance"]:
            assert entry["recommendation_count"] == counted.get(entry["appliance_key"], 0), entry
        assert sum(entry["recommendation_count"] for entry in result["per_appliance"]) == len(
            result["recommendations"]
        )

    def test_per_appliance_count_includes_household_swap_advice(self):
        """A high-power AC gets a catalogue rule AND a swap recommendation."""

        result = generate_recommendations(
            [appliance("冷氣機", 1400, 9, voltage=220, appliance_id="a1")], month=8
        )
        entry = result["per_appliance"][0]
        swap_count = len(
            [item for item in result["recommendations"] if item["id"].startswith("swap_")]
        )
        assert swap_count >= 1
        assert entry["recommendation_count"] == len(result["recommendations"])

    def test_plan_id_can_be_forced(self):
        result = generate_recommendations(
            [appliance("冷氣機", 900, 9, voltage=220)],
            plan_id="flat_rate_resell_reference",
        )
        assert result["blended_rate_per_kwh"] == pytest.approx(5.5)

    def test_disclaimer_states_savings_are_estimates(self, room):
        result = generate_recommendations(room, month=8)
        assert "不保證" in result["disclaimer_zh"]
        assert "estimates" in result["disclaimer_en"]

    def test_result_is_json_serialisable(self, room):
        import json

        result = generate_recommendations(room, month=8)
        assert json.loads(json.dumps(result))["recommendation_count"] >= 0


class TestValidation:
    def test_zero_usage_appliance_yields_no_saving_claims(self):
        result = generate_recommendations([appliance("Idle", 100, 0)], month=8)
        assert result["total_monthly_kwh"] == 0.0
        assert all(
            item["estimated_monthly_saving_kwh"] == 0.0 for item in result["recommendations"]
        )

    def test_invalid_appliance_is_rejected(self):
        from app.calculators.consumption import ValidationError

        with pytest.raises(ValidationError):
            generate_recommendations([appliance("Bad", 0, 3)], month=8)

    def test_empty_list_is_handled(self):
        result = generate_recommendations([], month=8)
        assert result["total_monthly_kwh"] == 0.0
        assert result["recommendations"] == []

    def test_savings_are_never_negative(self):
        result = generate_recommendations(
            [
                appliance("冷氣機", 2500, 24, voltage=220),
                appliance("電熱水器", 8800, 3, voltage=220),
                appliance("冰箱", 300, 24),
            ],
            month=8,
        )
        for item in result["recommendations"]:
            assert item["estimated_monthly_saving_kwh"] >= 0
            assert item["estimated_monthly_saving_twd"] >= 0
