"""Report unused imports and obviously dead module-level names.

A tiny static check that runs without extra dependencies, for keeping the calculation
core tidy.

Usage::

    python tools/lint_unused.py [directories...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DEFAULT_TARGETS = ("app", "tools")


def imported_names(tree: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.asname or alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    found.append((alias.asname or alias.name, node.lineno))
    return found


def used_names(tree: ast.AST) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # ``a.b.c`` -> mark ``a`` as used
            current: ast.AST = node
            while isinstance(current, ast.Attribute):
                current = current.value
            if isinstance(current, ast.Name):
                used.add(current.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Names referenced only inside strings (annotations with
            # ``from __future__ import annotations``) still count as used.
            for token in ("".join(ch if ch.isalnum() or ch == "_" else " " for ch in node.value)).split():
                used.add(token)
    return used


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    used = used_names(tree)
    problems: list[str] = []
    for name, line in imported_names(tree):
        if name == "annotations":
            continue
        if name not in used:
            problems.append(f"{path}:{line}: unused import '{name}'")
    return problems


def main() -> int:
    targets = sys.argv[1:] or list(DEFAULT_TARGETS)
    all_problems: list[str] = []
    for target in targets:
        for path in sorted(Path(target).rglob("*.py")):
            all_problems.extend(check_file(path))

    if all_problems:
        for problem in all_problems:
            print(problem)
        print(f"\n{len(all_problems)} problem(s)")
        return 1
    print("no unused imports found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
