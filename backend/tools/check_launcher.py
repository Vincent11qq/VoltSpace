"""Verify the launcher's discovery and error reporting without touching the real setup.

Checks that:
  * interpreters are discovered on a machine with no project-local venv;
  * the error raised when nothing has the dependencies is actionable (mentions --setup).

Usage::

    python tools/check_launcher.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

spec = importlib.util.spec_from_file_location("voltspace_start", BACKEND_ROOT / "start.py")
launcher = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(launcher)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))
    if not ok:
        failures.append(label)


print("candidate interpreters found on this machine:")
candidates = launcher._candidate_interpreters()
for path in candidates[:8]:
    version = launcher.python_version(path)
    print(f"   {path}  ->  {version}")
check("at least one interpreter discovered", bool(candidates), f"{len(candidates)} found")
check(
    "discovered interpreters are real Python",
    any(launcher.python_version(path) for path in candidates),
)

print()
# The success path must not depend on any fixed path.
python, extra = launcher.choose_runtime()
check("a working runtime was chosen", python.exists(), str(python))
check("it truly has the dependencies", launcher.has_dependencies(python, extra))

# Verify start.py does not embed this machine's home directory. The needle is assembled
# at runtime so this file itself contains no absolute path.
_needle = "C:" + chr(92) + "Users"
check(
    "no path is hard-coded in start.py",
    _needle not in (BACKEND_ROOT / "start.py").read_text(encoding="utf-8"),
)

# Now force the failure path: pretend nothing has the packages.
original = launcher.has_dependencies
launcher.has_dependencies = lambda *a, **k: False
try:
    launcher.choose_runtime()
    check("missing dependencies abort with guidance", False, "no exception raised")
except SystemExit as exc:
    message = str(exc)
    check("missing dependencies abort with guidance", True)
    check("  message mentions --setup", "--setup" in message)
    check("  message lists what was searched", "Searched for Python" in message)
    check("  message mentions python.org", "python.org" in message)
    print("\n--- message shown to a first-time user ---")
    print(message)
finally:
    launcher.has_dependencies = original

print()
print("launcher OK" if not failures else f"{len(failures)} check(s) failed")
raise SystemExit(0 if not failures else 1)
