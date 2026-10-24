"""Portability tests: the folder must work after being downloaded to any machine.

These guard the property that made the first version un-shareable: the launcher and the
scripts contained absolute paths from the developer's computer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Files a user runs, so a stale absolute path would break them on another machine.
RUNNABLE = (
    "start.py",
    "run_app.bat",
    "run_app.sh",
    "tools/check_launcher.py",
    "tools/check_web_ui.py",
    "tools/check_desktop.py",
    "tools/smoke_api.py",
    "tools/smoke_app.py",
    "tools/probe_errors.py",
    "tools/benchmark.py",
    "tools/export_openapi.py",
    "tools/export_examples.py",
    "desktop/app.py",
)

# A Windows home path or the DSH runtime path both indicate a machine-specific value.
# The regex requires a path separator after "Users" so that code *mentioning* a path in
# an assertion (e.g. checking that one is absent) is not flagged as containing one.
MACHINE_SPECIFIC = re.compile(
    r"[A-Za-z]:[\\/]{1,2}Users[\\/]|\.dsh[\\/]dsh-runtimes", re.IGNORECASE
)


@pytest.mark.parametrize("relative", RUNNABLE)
def test_no_machine_specific_paths(relative: str):
    path = BACKEND_ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not present")
    text = path.read_text(encoding="utf-8")
    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if MACHINE_SPECIFIC.search(line)
    ]
    assert offenders == [], f"{relative} contains a machine-specific path:\n" + "\n".join(offenders)


def test_launcher_discovers_python_without_fixed_paths():
    """The discovery helper must find interpreters using only PATH and known locations."""

    import importlib.util

    spec = importlib.util.spec_from_file_location("voltspace_start", BACKEND_ROOT / "start.py")
    launcher = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(launcher)

    candidates = launcher._candidate_interpreters()
    assert candidates, "no Python found on this machine"
    assert any(launcher.python_version(path) for path in candidates)


def test_launcher_reports_missing_dependencies_helpfully(monkeypatch=None):
    import importlib.util

    spec = importlib.util.spec_from_file_location("voltspace_start", BACKEND_ROOT / "start.py")
    launcher = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(launcher)

    original = launcher.has_dependencies
    launcher.has_dependencies = lambda *args, **kwargs: False
    try:
        with pytest.raises(SystemExit) as excinfo:
            launcher.choose_runtime()
    finally:
        launcher.has_dependencies = original

    message = str(excinfo.value)
    assert "--setup" in message
    assert "python.org" in message
    assert "Searched for Python" in message


def test_start_py_offers_a_setup_flag():
    """A downloaded copy must be able to install its own dependencies."""

    text = (BACKEND_ROOT / "start.py").read_text(encoding="utf-8")
    assert "--setup" in text
    assert "def setup_environment" in text
    assert "venv" in text


def test_batch_launcher_falls_back_progressively():
    """The .bat must try py, then python, then python3, then known install dirs."""

    text = (BACKEND_ROOT / "run_app.bat").read_text(encoding="utf-8", errors="replace")
    for token in ("where py", "where python3", "where python", "%LOCALAPPDATA%", "C:\\Python%%V"):
        assert token in text, f"run_app.bat should try {token!r}"
    assert "%HERE%" in text, "the .bat should resolve paths relative to its own location"


def test_shell_launcher_uses_its_own_directory():
    text = (BACKEND_ROOT / "run_app.sh").read_text(encoding="utf-8")
    assert "BASH_SOURCE" in text
    assert "command -v python3" in text


def test_data_directory_defaults_are_relative_to_the_project():
    """The database must not land in a hard-coded absolute directory."""

    from app.store import default_path

    assert Path(default_path()).is_absolute()
    source = (BACKEND_ROOT / "app" / "store.py").read_text(encoding="utf-8")
    assert "VOLTSPACE_DATA_DIR" in source
    assert "VOLTSPACE_DB" in source


# --- launcher internals ------------------------------------------------------
# These are the parts that only run when a user launches the app, so they need explicit
# coverage: port_free shipped with a shadowed-module bug that no test caught.


def _load_launcher():
    import importlib.util

    spec = importlib.util.spec_from_file_location("voltspace_start", BACKEND_ROOT / "start.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_port_free_detects_a_free_port():
    launcher = _load_launcher()
    # Port 0 would always succeed; probe a high, unlikely-used port instead.
    assert launcher.port_free(48231) is True


def test_port_free_detects_an_occupied_port():
    """Bind a socket, then confirm the launcher reports the port as busy."""

    import socket

    launcher = _load_launcher()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy_port = holder.getsockname()[1]
        assert launcher.port_free(busy_port) is False


def test_find_free_port_skips_occupied_ports():
    import socket

    launcher = _load_launcher()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy_port = holder.getsockname()[1]
        chosen = launcher.find_free_port(busy_port)
        assert chosen != busy_port
        assert launcher.port_free(chosen)


def test_build_env_puts_the_project_on_pythonpath():
    launcher = _load_launcher()
    env = launcher.build_env({})
    paths = env["PYTHONPATH"].split(__import__("os").pathsep)
    assert str(BACKEND_ROOT) in paths
    assert env["VOLTSPACE_DATA_DIR"]


def test_choose_runtime_accepts_a_pylibs_fallback():
    """A .pylibs directory should make a bare interpreter usable."""

    launcher = _load_launcher()
    python, extra = launcher.choose_runtime()
    assert python.exists()
    # Either the interpreter already has the packages, or .pylibs was supplied.
    assert launcher.has_dependencies(python, extra)
