"""The Flet UI must never compute a number or claim safety.

Member A's latest delivery (``voltspace_app.py``) had its own ``bill_of`` / ``kwh_of``
arithmetic, a hardcoded ``DEFAULT_TARIFF`` table (still carrying the old 8.46 top tier),
"SAFE / MODERATE / DANGER" labels and a ``voltspace_data.json`` store. Those are exactly the
things the integration removed, so they are pinned here: if a future delivery is pasted in
verbatim, these tests fail instead of the report quietly becoming untrue.
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
APP = FRONTEND / "desktop" / "app.py"

SOURCE = APP.read_text(encoding="utf-8")


class TestNoLocalArithmetic:
    def test_the_bill_is_not_calculated_here(self):
        """A tier loop in the UI would make the app disagree with /calculate/cost."""

        for forbidden in ("for limit, rate in", "min(kwh, limit)", "total += (upper - prev)"):
            assert forbidden not in SOURCE, f"the UI is computing a bill again ({forbidden!r})"

    def test_no_tariff_numbers_are_written_into_the_ui(self):
        rates = re.findall(r"\b(?:1\.78|2\.26|2\.55|3\.13|3\.80|4\.24|5\.14|5\.27|6\.44|7\.03|8\.46|8\.86)\b", SOURCE)
        assert rates == [], f"tariff rates belong in tariffs.json, found {rates}"

    def test_data_comes_from_the_api_helpers(self):
        for helper in ("def request(", "def safety_of(", "def make_suggestions(", "def load_line("):
            assert helper in SOURCE, f"missing API helper {helper!r}"
        assert "/household/dashboard" in SOURCE
        assert "/calculate/load" in SOURCE


class TestNeverClaimsSafety:
    def test_no_safe_moderate_danger_labels(self):
        for word in ("SAFE", "MODERATE", "DANGER"):
            assert f'"{word}"' not in SOURCE, f"the UI should not label a state {word!r}"

    def test_the_neutral_verdict_wording_is_used(self):
        for label in ("WITHIN MARGIN", "NEAR LIMIT", "OVER LIMIT", "NO LIMIT SET"):
            assert label in SOURCE, f"missing neutral label {label!r}"

    def test_the_disclaimer_stays_on_the_home_screen(self):
        assert "not a guarantee of electrical safety" in SOURCE

    def test_the_big_number_is_a_percentage_of_the_limit(self):
        assert "% of limit" in SOURCE
        # and it is not presented as a safety score out of 100
        assert "safety score" not in SOURCE.lower()


class TestNoSecondDataStore:
    def test_it_does_not_write_its_own_json_database(self):
        """The household lives in SQLite/Supabase behind the API, not in a local file."""

        assert "voltspace_data.json" not in SOURCE
        # desktop_prefs.json is allowed: it holds only the icon and the "on" switch.
        assert "desktop_prefs.json" in SOURCE

    def test_saving_goes_through_the_api(self):
        assert 'method="POST"' in SOURCE or "method='POST'" in SOURCE
        assert "/household/appliances" in SOURCE
