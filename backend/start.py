"""One-command launcher for the VoltSpace app.

Starts the FastAPI backend (which also serves the web UI) and opens a browser at the right
URL. Works on Windows, macOS and Linux, and picks the interpreter/package set that is
actually available on this machine.

Usage::

    python start.py                 # start on port 8000 and open the UI
    python start.py --port 8080
    python start.py --no-browser    # just serve
    python start.py --flet          # also try the Flet desktop UI
    python start.py --check         # verify the environment and exit

Why a launcher exists: the app needs (a) an interpreter that has the packages, (b) the
backend running, and (c) the browser pointed at the right port. Doing that by hand is the
single most common way a demo fails, so it is one command instead.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Minimum Python the dependencies support.
MIN_PYTHON = (3, 10)

# Names this project's virtualenv may have. ".venv" is what the docs and setup use.
VENV_CANDIDATES = (".venv", ".venv314", "venv")

# Optional project-local library directory (used when a machine has no pip at all).
PYLIBS = BACKEND_ROOT / ".pylibs"


def banner(text: str) -> None:
    print(f"\n=== {text} ===")


def port_free(port: int) -> bool:
    """True when nothing is listening on ``port``.

    Deliberately does NOT set ``SO_REUSEADDR``: on Windows that option lets a second bind
    succeed on a port that is already in use, which would make this check report every
    busy port as free and then have uvicorn fail to start.

    The context manager is not named ``socket`` so it cannot shadow the module constants.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
            return True
        except OSError:
            return False


def find_free_port(preferred: int, attempts: int = 20) -> int:
    for offset in range(attempts):
        candidate = preferred + offset
        if port_free(candidate):
            return candidate
    raise SystemExit(f"no free port found between {preferred} and {preferred + attempts - 1}")


# --------------------------------------------------------------------- discovery
# Nothing here hard-codes a path. The order is: this project's venv -> the interpreter
# running this script -> `py`/`python`/`python3` on PATH -> well-known install locations.
# That makes the downloaded folder work on any machine that has Python 3.10+.


def venv_python() -> Path | None:
    """A virtualenv that already lives inside this project, if any."""

    for name in VENV_CANDIDATES:
        for candidate in (
            BACKEND_ROOT / name / "Scripts" / "python.exe",  # Windows
            BACKEND_ROOT / name / "bin" / "python",          # macOS / Linux
            BACKEND_ROOT / name / "bin" / "python3",
        ):
            if candidate.exists():
                return candidate
    return None


def _candidate_interpreters() -> list[Path]:
    """Every plausible Python on this machine, in preference order."""

    found: list[Path] = []

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        try:
            if candidate.exists() and candidate not in found:
                found.append(candidate)
        except OSError:
            pass

    # 1. The interpreter already running (works when the user does `python start.py`).
    add(sys.executable)

    # 2. `py -V:3.x -c "import sys;print(sys.executable)"` (Windows launcher).
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher:
            for selector in ("-3", "-3.14", "-3.13", "-3.12", "-3.11", "-3.10", ""):
                args = [launcher]
                if selector:
                    args.append(selector)
                args += ["-c", "import sys;print(sys.executable)"]
                path = _run_and_capture(args)
                add(path)

    # 3. Whatever `python` / `python3` resolve to on PATH.
    for name in ("python", "python3", "python3.14", "python3.13", "python3.12", "python3.11", "python3.10"):
        resolved = shutil.which(name)
        if resolved:
            add(resolved)

    # 4. Common install locations (macOS/Linux usually covered by PATH above).
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for version in ("314", "313", "312", "311", "310"):
            add(local / "Programs" / "Python" / f"Python{version}" / "python.exe")
            add(Path(rf"C:\Python{version}") / "python.exe")
    else:
        for prefix in ("/usr/local/bin", "/usr/bin", "/opt/homebrew/bin"):
            for name in ("python3", "python3.13", "python3.12", "python3.11", "python3.10"):
                add(Path(prefix) / name)

    return found


def _run_and_capture(args: list[str], timeout: float = 30) -> str | None:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def python_version(python: Path) -> tuple[int, int] | None:
    raw = _run_and_capture(
        [str(python), "-c", "import sys;print('%d.%d' % sys.version_info[:2])"]
    )
    if not raw or "." not in raw:
        return None
    try:
        major, minor = raw.split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return None


def has_dependencies(python: Path, extra_env: dict[str, str]) -> bool:
    """True when this interpreter can import the stack AND this project's app package."""

    probe = "import fastapi, pydantic, uvicorn; import app.main; print('ok')"
    env = {**os.environ, **extra_env}
    paths = [str(BACKEND_ROOT)]
    extra_libs = extra_env.get("EXTRA_LIBS")
    if extra_libs and (Path(extra_libs) / "fastapi").is_dir():
        paths.insert(0, extra_libs)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.pop("EXTRA_LIBS", None)
    try:
        result = subprocess.run(
            [str(python), "-c", probe],
            cwd=str(BACKEND_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _describe(python: Path) -> str:
    version = python_version(python)
    return f"{python}  (Python {version[0]}.{version[1]})" if version else str(python)


def choose_runtime() -> tuple[Path, dict[str, str]]:
    """Return (python, extra_env) for the first working combination."""

    local_venv = venv_python()
    candidates: list[tuple[Path, dict[str, str]]] = []
    if local_venv:
        candidates.append((local_venv, {}))

    # A project-local .pylibs directory can supply the packages to any compatible Python.
    for python in _candidate_interpreters():
        candidates.append((python, {}))
        if PYLIBS.is_dir():
            candidates.append((python, {"EXTRA_LIBS": str(PYLIBS)}))

    seen: set[str] = set()
    for python, extra in candidates:
        key = f"{python}|{extra.get('EXTRA_LIBS', '')}"
        if key in seen:
            continue
        seen.add(key)
        if has_dependencies(python, extra):
            return python, extra

    raise SystemExit(
        "No Python with the required packages was found.\n\n"
        f"Searched for Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ here:\n"
        + "\n".join(f"  - {_describe(p)}" for p in _candidate_interpreters()[:8])
        + "\n\nFix it with one of these:\n"
        "  1) Automatic (recommended):\n"
        "         python start.py --setup\n"
        "  2) Manual:\n"
        "         python -m venv .venv\n"
        "         .venv\\Scripts\\pip install -r requirements.txt      (Windows)\n"
        "         .venv/bin/pip install -r requirements.txt           (macOS/Linux)\n\n"
        "If Python itself is missing, install it from https://www.python.org/downloads/\n"
        "If your Python has no pip (ensurepip missing), see README section 8.2."
    )


def build_env(extra: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUNBUFFERED", "1")
    paths = [str(BACKEND_ROOT)]
    extra_libs = extra.get("EXTRA_LIBS")
    if extra_libs and (Path(extra_libs) / "fastapi").is_dir():
        paths.insert(0, extra_libs)
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    # Keep the demo's data out of the repository root unless the user chose a path.
    env.setdefault("VOLTSPACE_DATA_DIR", str(BACKEND_ROOT / ".data"))
    return env


def wait_for_health(url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.4)
    return False


def open_browser_later(url: str, delay: float = 1.0) -> None:
    def worker() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - best effort
            print(f"open this URL in your browser: {url}")

    threading.Thread(target=worker, daemon=True).start()


def run_flet(python: Path, env: dict[str, str]) -> int:
    """Try the Flet desktop UI; returns a process exit code."""

    flet_app = BACKEND_ROOT / "desktop" / "app.py"
    if not flet_app.exists():
        print(f"Flet UI not found at {flet_app}")
        return 1

    probe = subprocess.run(
        [str(python), "-c", "import flet"], cwd=str(BACKEND_ROOT), env=env, capture_output=True
    )
    if probe.returncode != 0:
        print("\nFlet is not installed for this interpreter, so the desktop UI cannot start.")
        print("The web UI is unaffected — it is already running at the URL above.")
        print("\nTo use the desktop UI, install Flet once:")
        print(f"    {python} -m pip install -r requirements-desktop.txt")
        print("\nServing only the web UI in the meantime.")
        return 0

    banner("Starting the Flet desktop UI")
    try:
        return subprocess.call([str(python), str(flet_app)], cwd=str(BACKEND_ROOT), env=env)
    except OSError as exc:
        print(f"could not start Flet: {exc}")
        return 1


def setup_environment() -> int:
    """Create ``.venv`` and install the requirements — the portable, one-time setup.

    This is what makes a downloaded copy work on any machine: it uses whatever Python the
    user already has, creates the virtualenv *inside the project*, and installs the pinned
    requirements. No path is hard-coded anywhere.
    """

    banner("Setting up the environment")

    base = None
    for candidate in _candidate_interpreters():
        version = python_version(candidate)
        if version and version >= MIN_PYTHON:
            base = candidate
            break
    if base is None:
        print(
            f"No Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ was found on this machine.\n"
            "Install it from https://www.python.org/downloads/ and run this again.\n"
            "On Windows, tick 'Add python.exe to PATH' during installation."
        )
        return 1

    print(f"using Python : {_describe(base)}")
    venv_dir = BACKEND_ROOT / ".venv"

    if not venv_dir.exists():
        print(f"creating     : {venv_dir}")
        result = subprocess.run(
            [str(base), "-m", "venv", str(venv_dir)], cwd=str(BACKEND_ROOT)
        )
        if result.returncode != 0:
            print(
                "\nCould not create the virtualenv.\n"
                "On Debian/Ubuntu this usually means:  sudo apt install python3-venv\n"
                "On this machine the Python build may lack ensurepip; see README section 8.2."
            )
            return result.returncode

    target_python = venv_python()
    if target_python is None:
        print("the virtualenv was created but its interpreter could not be found")
        return 1
    print(f"venv python  : {_describe(target_python)}")

    requirements = BACKEND_ROOT / "requirements.txt"
    print(f"installing   : {requirements.name} (this can take a minute)")

    # Prefer `pip install -r`; fall back to `python -m pip` if pip is not on PATH.
    attempts: list[list[str]] = []
    for pip_exe in (
        target_python.parent / "pip.exe",
        target_python.parent / "pip",
        target_python.parent / "pip3",
    ):
        if pip_exe.exists():
            attempts.append([str(pip_exe), "install", "-r", str(requirements)])
            break
    attempts.append([str(target_python), "-m", "pip", "install", "-r", str(requirements)])

    last_error = 0
    for command in attempts:
        result = subprocess.run(command, cwd=str(BACKEND_ROOT))
        if result.returncode == 0:
            last_error = 0
            break
        last_error = result.returncode

    if last_error != 0:
        print(
            "\nPackage installation failed.\n"
            "If this machine has no internet access, use the offline path in README 8.2:\n"
            "    python tools/resolve_deps.py --dest .wheels fastapi==0.143.0 uvicorn==0.54.0 "
            "pydantic==2.14.1 pydantic-core==2.50.1 pytest==9.1.1 httpx==0.28.1\n"
            "    python tools/install_wheels.py --src .wheels --dest .pylibs"
        )
        return last_error

    banner("Setup complete")
    print("Start the app with:   python start.py")
    print("            or:       run_app.bat   (Windows)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the VoltSpace app",
        epilog="First run on a new machine: python start.py --setup",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--flet", action="store_true", help="also launch the Flet desktop UI")
    parser.add_argument("--check", action="store_true", help="verify the environment and exit")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="create .venv and install the requirements, then exit",
    )
    parser.add_argument(
        "--reload", action="store_true", help="auto-reload on code changes (development)"
    )
    args = parser.parse_args()

    if args.setup:
        return setup_environment()

    banner("VoltSpace")
    python, extra = choose_runtime()
    env = build_env(extra)
    print(f"python : {python}")
    if extra.get("EXTRA_LIBS"):
        print(f"libs   : {extra['EXTRA_LIBS']}")
    print(f"data   : {env['VOLTSPACE_DATA_DIR']}")

    if args.check:
        from_check = subprocess.run(
            [str(python), "-m", "app.data_check"], cwd=str(BACKEND_ROOT), env=env
        )
        print("\nenvironment OK" if from_check.returncode == 0 else "\nenvironment has problems")
        return from_check.returncode

    port = args.port
    if not port_free(port):
        replacement = find_free_port(port + 1)
        print(f"\nport {port} is busy; using {replacement} instead")
        port = replacement

    url = f"http://{HOST}:{port}/"
    command = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        HOST,
        "--port",
        str(port),
    ]
    if args.reload:
        command.append("--reload")

    banner(f"Serving the app on {url}")
    print("Press Ctrl+C to stop.\n")
    server = subprocess.Popen(command, cwd=str(BACKEND_ROOT), env=env)

    try:
        if wait_for_health(f"http://{HOST}:{port}/health"):
            print(f"backend ready -> {url}")
            print(f"API docs      -> {url}docs")
            if not args.no_browser:
                open_browser_later(url)
        else:
            print("backend did not become ready in time; check the log above")
            return server.wait(timeout=1)

        if args.flet:
            return run_flet(python, env)

        return server.wait()
    except KeyboardInterrupt:
        print("\nstopping…")
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
