"""Keep the three documents telling the same story.

The test count went stale in ``docs/server-status.md`` while ``README.md`` was correct,
because only one file was edited. These checks compare the documents against each other,
which is fast; ``tools/check_docs_numbers.py`` compares them against the real code and is
the authoritative check (it runs pytest, so it is not part of this suite).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent

DOCS = {
    "README.md": REPO / "README.md",
    "server-status.md": REPO / "docs" / "server-status.md",
    "integration.md": REPO / "server" / "docs" / "integration.md",
}

# A claim about how many tests there are. Historical notes ("在 371 個測試全過的版本上")
# are excluded: they describe a past state on purpose.
COUNT_PATTERNS = [
    r"(\d{3,4})\s*passed",
    r"(\d{3,4})\s*個測試",
    r"測試（(\d{3,4})\s*個）",
    r"\*\*(\d{3,4}) 個\*\*",
]
HISTORY = ("版本上", "舊版", "先前", "歷史")


def _text(name: str) -> str:
    path = DOCS[name]
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_docs_exist():
    for name, path in DOCS.items():
        assert path.exists(), f"{name} is missing"


def test_all_docs_state_the_same_test_count():
    """One doc must not claim a different number than the others."""

    claims: dict[str, set[int]] = {}
    for name in DOCS:
        found: set[int] = set()
        for line in _text(name).splitlines():
            if any(marker in line for marker in HISTORY):
                continue
            for pattern in COUNT_PATTERNS:
                found.update(int(value) for value in re.findall(pattern, line))
        claims[name] = found

    numbers = {name: sorted(values) for name, values in claims.items()}
    all_values = {value for values in claims.values() for value in values}
    assert len(all_values) <= 1, f"documents disagree on the test count: {numbers}"


@pytest.mark.parametrize("name", list(DOCS))
def test_no_doc_quotes_an_old_count(name: str):
    """535 was the count for a while; it must not come back."""

    text = _text(name)
    for stale in ("535 passed", "535 個測試", "測試（535 個）", "**535 個**", "528 passed", "500 個測試"):
        assert stale not in text, f"{name} still says {stale!r}"


def test_python_share_is_quoted_the_same_way_in_both_docs():
    """The share moves on every edit, so both docs quote it rounded to a whole percent."""

    readme = _text("README.md")
    status = _text("server-status.md")

    def shares(text: str) -> set[str]:
        return set(re.findall(r"\*\*(\d{2})%\*\*", text))

    if not shares(readme) or not shares(status):
        pytest.skip("one of the documents does not quote the share")

    assert shares(readme) & shares(status), (
        f"README quotes {sorted(shares(readme))} but server-status quotes "
        f"{sorted(shares(status))}"
    )


def test_no_doc_points_at_a_missing_relative_link():
    """Links are relative to the document that contains them."""

    problems = []
    for name, path in DOCS.items():
        if not path.exists():
            continue
        for match in re.finditer(r"\]\((?!https?:|#|mailto:)([^)#]+)", path.read_text(encoding="utf-8")):
            target = (path.parent / match.group(1)).resolve()
            if not target.exists():
                problems.append(f"{name} -> {match.group(1)}")
    assert problems == [], problems
