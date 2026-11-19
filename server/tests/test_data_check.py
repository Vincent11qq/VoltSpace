"""Tests for the data-file integrity checks (``app.data_check``).

These guard the contract that a broken ``tariffs.json`` or ``appliances.json`` fails at
startup instead of silently producing wrong numbers.
"""

from __future__ import annotations

import copy
import json

import pytest

from app.calculators.electricity_bill import load_tariffs
from app.data_check import (
    DataIntegrityError,
    validate_all,
    validate_catalog,
    validate_tariffs,
)
from app.services.recommendations import load_appliance_catalog


@pytest.fixture
def tariffs() -> dict:
    return copy.deepcopy(load_tariffs())


@pytest.fixture
def catalog() -> dict:
    return copy.deepcopy(load_appliance_catalog())


class TestRealDataIsValid:
    def test_shipped_data_files_pass(self):
        summary = validate_all()
        assert summary["plan_ids"] == sorted(summary["plan_ids"])
        assert len(summary["plan_ids"]) == 3
        assert summary["appliance_count"] == 12

    def test_tariff_validation_returns_plan_ids(self):
        assert validate_tariffs() == [
            "flat_rate_resell_reference",
            "tw_residential_tiered",
            "tw_residential_tou",
        ]

    def test_catalog_validation_returns_count(self):
        assert validate_catalog() == 12


class TestTariffValidation:
    def test_missing_plans_is_rejected(self, tariffs):
        tariffs["plans"] = {}
        with pytest.raises(DataIntegrityError, match="non-empty"):
            validate_tariffs(tariffs)

    def test_unknown_default_plan_is_rejected(self, tariffs):
        tariffs["default_plan_id"] = "nope"
        with pytest.raises(DataIntegrityError, match="default_plan_id"):
            validate_tariffs(tariffs)

    def test_missing_season_rules_is_rejected(self, tariffs):
        del tariffs["season_rules"]["summer"]
        with pytest.raises(DataIntegrityError, match="season_rules"):
            validate_tariffs(tariffs)

    def test_plan_id_key_mismatch_is_rejected(self, tariffs):
        tariffs["plans"]["tw_residential_tiered"]["id"] = "something_else"
        with pytest.raises(DataIntegrityError, match="must match its key"):
            validate_tariffs(tariffs)

    def test_unsupported_plan_type_is_rejected(self, tariffs):
        tariffs["plans"]["tw_residential_tiered"]["type"] = "mystery"
        with pytest.raises(DataIntegrityError, match="unsupported type"):
            validate_tariffs(tariffs)

    def test_missing_season_on_a_plan_is_rejected(self, tariffs):
        del tariffs["plans"]["tw_residential_tiered"]["seasons"]["summer"]
        with pytest.raises(DataIntegrityError, match="missing season"):
            validate_tariffs(tariffs)

    def test_zero_rate_is_rejected(self, tariffs):
        tariffs["plans"]["tw_residential_tiered"]["seasons"]["summer"]["tiers"][0]["rate"] = 0
        with pytest.raises(DataIntegrityError, match="rate must be > 0"):
            validate_tariffs(tariffs)

    def test_open_ended_last_tier_is_required(self, tariffs):
        """Without it, consumption above the last ceiling would have no price."""

        tariffs["plans"]["tw_residential_tiered"]["seasons"]["summer"]["tiers"][-1][
            "up_to_kwh"
        ] = 5000
        with pytest.raises(DataIntegrityError, match="last tier"):
            validate_tariffs(tariffs)

    def test_tier_ceilings_must_increase(self, tariffs):
        tiers = tariffs["plans"]["tw_residential_tiered"]["seasons"]["summer"]["tiers"]
        tiers[1]["up_to_kwh"] = 100  # lower than tier 1's 120
        with pytest.raises(DataIntegrityError, match="must increase"):
            validate_tariffs(tariffs)

    def test_flat_plan_needs_a_rate(self, tariffs):
        tariffs["plans"]["flat_rate_resell_reference"]["seasons"] = {"summer": {}, "non_summer": {}}
        tariffs["plans"]["flat_rate_resell_reference"].pop("rate", None)
        with pytest.raises(DataIntegrityError, match="flat rate must be > 0"):
            validate_tariffs(tariffs)

    def test_time_of_use_off_peak_must_not_exceed_peak(self, tariffs):
        tariffs["plans"]["tw_residential_tou"]["seasons"]["summer"]["off_peak"] = 9.9
        with pytest.raises(DataIntegrityError, match="off-peak"):
            validate_tariffs(tariffs)


class TestCatalogValidation:
    def test_missing_defaults_is_rejected(self, catalog):
        del catalog["defaults"]
        with pytest.raises(DataIntegrityError, match="defaults"):
            validate_catalog(catalog)

    def test_missing_default_key_is_rejected(self, catalog):
        del catalog["defaults"]["power_factor"]
        with pytest.raises(DataIntegrityError, match="power_factor"):
            validate_catalog(catalog)

    def test_empty_appliances_is_rejected(self, catalog):
        catalog["appliances"] = []
        with pytest.raises(DataIntegrityError, match="non-empty"):
            validate_catalog(catalog)

    def test_duplicate_key_is_rejected(self, catalog):
        catalog["appliances"].append(copy.deepcopy(catalog["appliances"][0]))
        with pytest.raises(DataIntegrityError, match="duplicate key"):
            validate_catalog(catalog)

    def test_typical_power_must_be_inside_the_range(self, catalog):
        catalog["appliances"][0]["typical_power_watts"] = 99999
        with pytest.raises(DataIntegrityError, match="within power_range_watts"):
            validate_catalog(catalog)

    def test_rule_without_an_id_is_rejected(self, catalog):
        del catalog["appliances"][0]["rules"][0]["id"]
        with pytest.raises(DataIntegrityError, match="missing 'id'"):
            validate_catalog(catalog)

    def test_rule_with_empty_text_is_rejected(self, catalog):
        catalog["appliances"][0]["rules"][0]["reason_zh"] = "   "
        with pytest.raises(DataIntegrityError, match="reason_zh"):
            validate_catalog(catalog)

    def test_rule_with_unsupported_condition_is_rejected(self, catalog):
        """A condition the engine does not understand would be silently ignored."""

        catalog["appliances"][0]["rules"][0]["when"] = {"temperature_celsius_gte": 30}
        with pytest.raises(DataIntegrityError, match="unsupported condition"):
            validate_catalog(catalog)

    def test_rule_with_empty_when_is_rejected(self, catalog):
        catalog["appliances"][0]["rules"][0]["when"] = {}
        with pytest.raises(DataIntegrityError, match="'when' is empty"):
            validate_catalog(catalog)

    def test_reduction_ratio_above_one_is_rejected(self, catalog):
        catalog["appliances"][0]["rules"][0]["reduction_ratio"] = 1.5
        with pytest.raises(DataIntegrityError, match="reduction_ratio"):
            validate_catalog(catalog)

    def test_alternative_needs_a_positive_power(self, catalog):
        for entry in catalog["appliances"]:
            if entry.get("efficient_alternative"):
                entry["efficient_alternative"]["power_watts"] = 0
                break
        with pytest.raises(DataIntegrityError, match="power_watts must be > 0"):
            validate_catalog(catalog)

    def test_alternative_needs_a_label(self, catalog):
        for entry in catalog["appliances"]:
            if entry.get("efficient_alternative"):
                entry["efficient_alternative"]["label_zh"] = ""
                break
        with pytest.raises(DataIntegrityError, match="label_zh"):
            validate_catalog(catalog)


class TestEveryCatalogueIsUsable:
    """The shipped catalogue must exercise only supported rules and valid numbers."""

    def test_every_rule_condition_is_supported(self):
        from app.data_check import SUPPORTED_RULE_CONDITIONS

        for entry in load_appliance_catalog()["appliances"]:
            for rule in entry.get("rules", []):
                assert set((rule.get("when") or {}).keys()) <= SUPPORTED_RULE_CONDITIONS, (
                    entry["key"],
                    rule.get("id"),
                )

    def test_alternatives_are_more_efficient_than_the_typical_appliance(self):
        for entry in load_appliance_catalog()["appliances"]:
            alternative = entry.get("efficient_alternative")
            if not alternative:
                continue
            assert alternative["power_watts"] <= entry["typical_power_watts"], entry["key"]

    def test_catalogue_is_json_round_trippable(self):
        catalog = load_appliance_catalog()
        assert json.loads(json.dumps(catalog))["appliances"] == catalog["appliances"]
