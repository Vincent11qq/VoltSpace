"""Count authored lines by language, for the course's Python-share question.

The TA example deck reports "Local: 51.84% including tests/tooling; 42.16%
production-only", so this computes both views for VoltSpace.

Usage::

    python tools/python_share.py
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent

# Never authored by us, or generated.
SKIP_DIRS = {
    ".git", ".venv", ".venv314", ".pylibs", ".wheels", ".wheels-flet", ".flet-home",
    ".data", ".test-data", "__pycache__", "node_modules",
}
SKIP_PREFIXES = ("pytest-cache-files-",)

# Directories that are test/tooling rather than shipped product code.
TEST_DIRS = {"tests", "tools"}

LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".css": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".bat": "Batch",
    ".sh": "Shell",
}

# Third-party snapshots kept for reference, not authored by this team.
REFERENCE_DIRS = {"prototype", "Python", "Supabase"}


def counted_lines(path: Path) -> int:
    """Non-blank, non-comment-only lines."""

    count = 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # crude block-comment tracking for Python/CSS docstrings
        if in_block:
            if line.endswith('"""') or line.endswith("'''"):
                in_block = False
            continue
        if line.startswith('"""') or line.startswith("'''"):
            if not (line.endswith('"""') and len(line) > 3):
                in_block = True
            continue
        if line.startswith(("#", "//", "/*", "*", "--")):
            continue
        count += 1
    return count


def main() -> int:
    buckets: dict[str, dict[str, int]] = {
        "production": {},
        "test_tooling": {},
        "reference": {},
    }

    for path in BACKEND.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if parts & SKIP_DIRS:
            continue
        if any(part.startswith(SKIP_PREFIXES) for part in path.parts):
            continue
        language = LANGUAGES.get(path.suffix.lower())
        if not language:
            continue
        relative = path.relative_to(BACKEND)
        if relative.parts and relative.parts[0] in TEST_DIRS:
            bucket = "test_tooling"
        else:
            bucket = "production"
        buckets[bucket][language] = buckets[bucket].get(language, 0) + counted_lines(path)

    for reference_dir in REFERENCE_DIRS:
        for path in (PROJECT / reference_dir).rglob("*"):
            if not path.is_file():
                continue
            language = LANGUAGES.get(path.suffix.lower())
            if not language:
                continue
            buckets["reference"][language] = (
                buckets["reference"].get(language, 0) + counted_lines(path)
            )

    def report(name: str, table: dict[str, int]) -> tuple[int, int]:
        total = sum(table.values())
        python = table.get("Python", 0)
        print(f"\n{name}")
        for language, lines in sorted(table.items(), key=lambda kv: -kv[1]):
            share = (lines / total * 100) if total else 0
            print(f"  {language:12} {lines:6} lines  {share:5.1f}%")
        print(f"  {'TOTAL':12} {total:6} lines")
        if total:
            print(f"  -> Python share: {python / total * 100:.2f}%")
        return python, total

    prod_py, prod_total = report("backend/ production code (shipped)", buckets["production"])
    test_py, test_total = report("backend/ tests + tools", buckets["test_tooling"])

    combined = dict(buckets["production"])
    for language, lines in buckets["test_tooling"].items():
        combined[language] = combined.get(language, 0) + lines
    all_py, all_total = report("backend/ production + tests + tools", combined)

    report("reference snapshots (teammates' originals, not authored here)", buckets["reference"])

    print("\n--- the two numbers the course asks for ---")
    print(f"including tests/tooling : {all_py / all_total * 100:.2f}%  ({all_py}/{all_total})")
    print(f"production-only         : {prod_py / prod_total * 100:.2f}%  ({prod_py}/{prod_total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
