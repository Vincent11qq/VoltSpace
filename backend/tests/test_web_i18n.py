"""Checks for the bilingual UI.

The language switcher is only as good as its dictionary, so these tests assert that the
two dictionaries stay in step and that the markup does not reference a key that does not
exist. They run offline; app.js is evaluated in Node with the DOM parts never reached.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
WEB = BACKEND / "web"
APP_JS = WEB / "app.js"
INDEX = WEB / "index.html"

# Keys whose value is legitimately identical in both languages: proper nouns, and the
# quantity suffix which is just a multiplication sign plus a number.
SAME_IN_BOTH = {"lang.button", "plug.qty"}


def _node() -> str | None:
    for name in ("node", "node.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _extract_dictionary() -> dict:
    """Pull the I18N object out of app.js and evaluate it in Node.

    A regex would break on nested braces, so this counts them.
    """

    node = _node()
    if node is None:
        pytest.skip("node is not installed")

    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const I18N = {")
    index = source.index("{", start)
    depth = 0
    end = None
    in_string = False
    escaped = False
    for position in range(index, len(source)):
        char = source[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = position + 1
                break
    assert end, "could not find the end of the I18N object"

    literal = source[index:end]
    script = f"process.stdout.write(JSON.stringify(({literal})))"
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        # Decode as UTF-8 explicitly: the default is the system code page (cp950 here),
        # which cannot represent the Chinese values and raises UnicodeDecodeError.
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def code_without_dictionary() -> str:
    """app.js with the I18N block removed, so only executable code remains."""

    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const I18N = {")
    index = source.index("{", start)
    depth = 0
    for position in range(index, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + source[position + 1 :]
    raise AssertionError("could not find the end of the I18N object")


@pytest.fixture(scope="module")
def dictionary() -> dict:
    return _extract_dictionary()


class TestDictionaries:
    def test_both_languages_present(self, dictionary):
        assert set(dictionary) >= {"zh", "en"}

    def test_same_keys_in_both_languages(self, dictionary):
        zh, en = set(dictionary["zh"]), set(dictionary["en"])
        assert zh - en == set(), f"missing from en: {sorted(zh - en)}"
        assert en - zh == set(), f"missing from zh: {sorted(en - zh)}"

    def test_no_empty_values(self, dictionary):
        for language, table in dictionary.items():
            empty = [key for key, value in table.items() if not str(value).strip()]
            assert empty == [], f"{language} has empty values: {empty}"

    def test_english_actually_differs(self, dictionary):
        """A copy-pasted Chinese string would silently pass as English."""

        identical = [
            key
            for key in dictionary["zh"]
            if dictionary["zh"][key] == dictionary["en"].get(key) and key not in SAME_IN_BOTH
        ]
        assert identical == [], f"en still identical to zh for: {identical}"

    def test_placeholders_match(self, dictionary):
        """A {placeholder} present in one language but not the other breaks formatting."""

        problems = []
        for key, zh_value in dictionary["zh"].items():
            en_value = dictionary["en"].get(key, "")
            zh_slots = set(re.findall(r"\{(\w+)\}", zh_value))
            en_slots = set(re.findall(r"\{(\w+)\}", en_value))
            if zh_slots != en_slots:
                problems.append(f"{key}: zh={sorted(zh_slots)} en={sorted(en_slots)}")
        assert problems == [], "\n".join(problems)


class TestMarkupKeys:
    def test_every_data_i18n_key_exists(self, dictionary):
        html = INDEX.read_text(encoding="utf-8")
        attributes = re.findall(r'data-i18n(?:-ph|-title)?="([^"]+)"', html)
        assert attributes, "the markup should carry translation attributes"

        missing = [
            name for name in attributes
            if name not in dictionary["zh"] or name not in dictionary["en"]
        ]
        assert missing == [], f"markup references unknown keys: {sorted(set(missing))}"

    def test_language_toggle_exists(self):
        html = INDEX.read_text(encoding="utf-8")
        assert 'id="langToggle"' in html
        assert "app.js" in html

    def test_switcher_is_wired_up(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert 'getElementById("langToggle")' in source or '$("langToggle")' in source
        assert "setLanguage(" in source
        assert "localStorage" in source, "the choice should be remembered"


def _checker():
    """Import tools/check_web_i18n.py (it must stay importable without running)."""

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_web_i18n", BACKEND / "tools" / "check_web_i18n.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rendered() -> dict:
    """What the real app.js would show, rendered once for the whole module."""

    if _node() is None:
        pytest.skip("node is not installed")
    return _checker().render()


class TestRenderedOutput:
    """Run the real app.js in Node and check what the UI would actually show."""

    def test_both_languages_render_actual_text(self, rendered):
        for language in ("zh", "en"):
            section = rendered[language]
            for key in ("tagline", "save", "emptyStatus", "month7", "pick", "saving"):
                assert str(section.get(key, "")).strip(), f"{language}.{key} is empty"

    def test_the_two_languages_differ(self, rendered):
        for key in ("tagline", "save", "emptyStatus", "month7", "saving"):
            assert rendered["zh"][key] != rendered["en"][key], f"{key} is not translated"

    def test_month_labels_are_localised(self, rendered):
        assert rendered["zh"]["month7"] == "7 月"
        assert rendered["en"]["month7"] == "July"

    def test_switching_updates_the_page_language_and_toggle(self, rendered):
        assert rendered["en"]["documentLang"] == "en"
        assert rendered["en"]["toggleLabel"] == "中文", "the toggle offers the other language"

    def test_missing_translation_falls_back_instead_of_blanking(self, rendered):
        fallback = rendered["fallback"]
        assert fallback["missingEn"] == "只有中文"
        assert fallback["missingZh"] == "English only"

    def test_no_reported_problems(self, rendered):
        assert _checker().problems(rendered) == []

    def test_clicking_the_button_switches_the_language(self, rendered):
        """The user-visible behaviour: the toggle must do something when clicked."""

        click = rendered["click"]
        assert click["handlers"] >= 1, "no click handler attached"
        assert click["fired"] >= 1, "the handler never ran"
        assert click["before"] == "EN"
        assert click["after"] == "中文", "the label did not change"
        assert click["langAfter"] == "en"
        assert click["documentLangAfter"] == "en"
        assert click["taglineAfter"] == rendered["en"]["tagline"]

    def test_clicking_again_switches_back(self, rendered):
        click = rendered["click"]
        assert click["backTo"] == "zh"
        assert click["backLabel"] == "EN"


class TestBackendEnglishThroughHttp:
    """The English text must survive the response model.

    Regression guard: the recommendation service returned title_en/reason_en, but the
    Pydantic response model did not declare them, so FastAPI silently dropped them from
    /household/dashboard. Testing the service function alone did not catch it - only an
    HTTP call does.
    """

    ROOM = [
        {
            "name": "冷氣機",
            "power_watts": 900,
            "hours_per_day": 9,
            "days_per_month": 30,
            "quantity": 1,
            "voltage": 220,
        }
    ]

    def _dashboard(self) -> dict:
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            response = client.post(
                "/household/dashboard", json={"appliances": self.ROOM, "month": 8}
            )
        assert response.status_code == 200, response.text
        return response.json()

    def test_recommendations_carry_english_text(self):
        data = self._dashboard()
        recommendations = data["recommendations"]["recommendations"]
        assert recommendations, "expected at least one recommendation"

        for item in recommendations:
            for key in ("title_en", "reason_en", "suggestion_en", "assumption_en"):
                assert str(item.get(key) or "").strip(), (
                    f"{key} missing from the HTTP response (a response model probably "
                    f"does not declare it)"
                )

    def test_english_is_not_just_the_chinese_text(self):
        data = self._dashboard()
        item = data["recommendations"]["recommendations"][0]
        assert item["title_en"] != item["title_zh"]

    def test_summary_and_warnings_are_bilingual(self):
        data = self._dashboard()
        assert data["summary"].get("season_label_en")
        assert data["summary"].get("season_label_zh")
        warning = data["bill"]["warnings"][0]
        assert warning.get("message_en")
        assert warning.get("message_zh")

    def test_disclaimers_are_bilingual(self):
        data = self._dashboard()
        assert data["load"].get("disclaimer_en")
        assert data["recommendations"].get("disclaimer_en")

    def test_reference_data_has_english_names(self):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            presets = client.get("/appliances/presets").json()
        assert presets["presets"][0].get("name_en")
        assert presets["circuits"][0].get("label_en")


class TestNoLeftovers:
    @pytest.mark.parametrize(
        "chinese",
        [
            "尚未接上電器",
            "已儲存 {n} 台家電",
            "計算失敗：",
            "後端未連線",
            "請填「名稱」",
        ],
    )
    def test_hardcoded_chinese_moved_into_the_dictionary(self, chinese):
        """These used to be inline literals in the render code.

        The I18N block is stripped first, so an occurrence there is expected and only a
        leftover in the code itself fails.
        """

        code = code_without_dictionary()
        assert chinese not in code, f"{chinese!r} is still inline in the render code"
