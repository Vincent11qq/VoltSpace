"""Tests for the tariff import tool and the currency of the shipped rate table."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TARIFF_FILE = BACKEND_ROOT / "app" / "data" / "tariffs.json"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "import_tariff", BACKEND_ROOT / "tools" / "import_tariff.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestImportTool:
    def test_table_keys_map_onto_six_tiers(self):
        tool = _load_tool()
        assert len(tool.TIER_KEYS) == 6
        assert tool.TIER_CEILINGS == [120, 330, 500, 700, 1000, None]

    def test_converts_the_group_rate_table(self):
        tool = _load_tool()
        assert tool.to_rates(tool.SUMMER) == [1.78, 2.55, 3.80, 5.14, 6.44, 8.86]
        assert tool.to_rates(tool.NON_SUMMER) == [1.78, 2.26, 3.13, 4.24, 5.27, 7.03]

    def test_missing_key_is_rejected(self):
        tool = _load_tool()
        broken = dict(tool.SUMMER)
        broken.pop("next_170_kwh")
        with pytest.raises(SystemExit):
            tool.to_rates(broken)

    def test_a_decreasing_rate_is_rejected(self):
        """A tier that costs less than the one below it is a typo, not a policy."""

        tool = _load_tool()
        with pytest.raises(SystemExit):
            tool.verify_structure([1.78, 2.55, 1.00, 5.14, 6.44, 8.86], "summer")

    def test_a_non_positive_rate_is_rejected(self):
        tool = _load_tool()
        with pytest.raises(SystemExit):
            tool.verify_structure([1.78, 2.55, 3.80, 0, 6.44, 8.86], "summer")

    def test_the_shipped_file_matches_the_tool_table(self):
        """Guard rail: the JSON and the tool's table must never drift apart."""

        tool = _load_tool()
        data = json.loads(TARIFF_FILE.read_text(encoding="utf-8"))
        plan = data["plans"]["tw_residential_tiered"]
        assert [t["rate"] for t in plan["seasons"]["summer"]["tiers"]] == tool.to_rates(
            tool.SUMMER
        )
        assert [t["rate"] for t in plan["seasons"]["non_summer"]["tiers"]] == tool.to_rates(
            tool.NON_SUMMER
        )

    def test_shipped_ceilings_match_the_tool(self):
        tool = _load_tool()
        data = json.loads(TARIFF_FILE.read_text(encoding="utf-8"))
        plan = data["plans"]["tw_residential_tiered"]
        for season in ("summer", "non_summer"):
            assert [t["up_to_kwh"] for t in plan["seasons"][season]["tiers"]] == tool.TIER_CEILINGS
