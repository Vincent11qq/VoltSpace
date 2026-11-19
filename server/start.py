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
from functools import lru_cache
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parent
# The Flet client lives beside the server; only the server half is in this folder.
FRONTEND_ROOT = SERVER_ROOT.parent / "frontend"
HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# Hosts that need the app reachable from outside the machine. A platform sets $PORT and
# routes traffic to 0.0.0.0, so binding the loopback address there accepts no requests.
PUBLIC_HOST = "0.0.0.0"

# Minimum Python the dependencies support.
MIN_PYTHON = (3, 10)

# A healthy interpreter answers a version probe in well under a second. A Windows Store
# app-execution alias can hang forever, so probes get a short, hard limit.
DISCOVERY_TIMEOUT = 5.0

# Names this project's virtualenv may have. ".venv" is what the docs and setup use.
VENV_CANDIDATES = (".venv", ".venv314", "venv")

# Optional project-local library directory (used when a machine has no pip at all).
PYLIBS = SERVER_ROOT / ".pylibs"


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
            SERVER_ROOT / name / "Scripts" / "python.exe",  # Windows
            SERVER_ROOT / name / "bin" / "python",          # macOS / Linux
            SERVER_ROOT / name / "bin" / "python3",
        ):
            if candidate.exists():
                return candidate
    return None


@lru_cache(maxsize=1)
def _discover_interpreters() -> tuple[Path, ...]:
    """Every plausible Python on this machine, in preference order."""

    found: list[Path] = []

    def add(path: Path | str | None) -> None:
        if not path:
            return
        candidate = Path(path)
        # Windows ships "app execution aliases" (WindowsApps\python.exe) that are stubs:
        # running one can block for a long time while it tries to open the Store, and it
        # is not a usable interpreter. Skip them so startup never hangs on one.
        if "windowsapps" in str(candidate).lower():
            return
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
                path = _run_and_capture(args, timeout=DISCOVERY_TIMEOUT)
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

    return tuple(found)


def _candidate_interpreters() -> list[Path]:
    """A fresh list of the interpreters found on this machine.

    The discovery itself is cached: it spawns the ``py`` launcher several times and can
    take seconds on Windows, and it is called more than once (choose_runtime, then again
    when building the failure message).
    """

    return list(_discover_interpreters())


def _run_and_capture(args: list[str], timeout: float = DISCOVERY_TIMEOUT) -> str | None:
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


@lru_cache(maxsize=None)
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
    """True when this interpreter can see the stack AND this project's app package.

    This deliberately checks that the packages are *present* rather than importing them.
    Importing FastAPI, Pydantic, Starlette and this app takes several seconds on a cold
    cache, and it runs once per candidate interpreter - which made the launcher sit there
    for 30+ seconds before the server even started.

    A missing module is what this is for. A module that is present but broken (syntax
    error, bad data file) is diagnosed much better by uvicorn's own traceback than by a
    "no packages found" message, which would point at the wrong problem.
    """

    probe = (
        "import importlib.util as u, sys\n"
        "missing = [n for n in ('fastapi', 'pydantic', 'uvicorn') if u.find_spec(n) is None]\n"
        "if u.find_spec('app') is None:\n"
        "    missing.append('app')\n"
        "print(','.join(missing))\n"
        "sys.exit(1 if missing else 0)\n"
    )
    env = {**os.environ, **extra_env}
    paths = [str(SERVER_ROOT)]
    extra_libs = extra_env.get("EXTRA_LIBS")
    if extra_libs and (Path(extra_libs) / "fastapi").is_dir():
        paths.insert(0, extra_libs)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.pop("EXTRA_LIBS", None)
    try:
        result = subprocess.run(
            [str(python), "-c", probe],
            cwd=str(SERVER_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
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
    paths = [str(SERVER_ROOT)]
    extra_libs = extra.get("EXTRA_LIBS")
    if extra_libs and (Path(extra_libs) / "fastapi").is_dir():
        paths.insert(0, extra_libs)
    existing = env.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    # Keep the demo's data out of the repository root unless the user chose a path.
    env.setdefault("VOLTSPACE_DATA_DIR", str(SERVER_ROOT / ".data"))
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


def flet_cache_env(base: dict[str, str]) -> dict[str, str]:
    """Point Flet's client cache inside the project instead of the user's home.

    ``flet-desktop`` unpacks its Flutter client into a ``.flet`` folder under
    ``Path.home()``. On machines where the home directory is not writable - sandboxes,
    managed devices, some corporate profiles - that unpack fails with a ``PermissionError``
    on the client directory and the window never opens.

    Redirecting the home directory for *this child process only* keeps the download inside
    the project, so the desktop UI works without writing anything outside it. The folder is
    git-ignored and the download (about 100 MB) happens once.
    """

    home = SERVER_ROOT / ".flet-home"
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        return base
    return {**base, "USERPROFILE": str(home), "HOME": str(home)}


def run_flet(python: Path, env: dict[str, str]) -> int:
    """Try the Flet desktop UI; returns a process exit code."""

    flet_app = FRONTEND_ROOT / "desktop" / "app.py"
    if not flet_app.exists():
        print(f"Flet UI not found at {flet_app}")
        return 1

    # `flet` alone is not enough to open a window: the window comes from the separate
    # `flet-desktop` package (which also needs `rich`). Checking both here turns a
    # confusing runtime "Unable to install flet-desktop" into an actionable message.
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util as u\n"
            "missing = [n for n in ('flet', 'flet_desktop', 'rich') if u.find_spec(n) is None]\n"
            "print(','.join(missing))\n"
            "raise SystemExit(1 if missing else 0)\n",
        ],
        cwd=str(SERVER_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        missing = (probe.stdout or "").strip()
        print("\nThe desktop window needs more than the `flet` package itself.")
        if missing:
            print(f"Missing for this interpreter: {missing}")
        print("The web UI is unaffected — it is already running at the URL above.\n")
        print("Install the desktop extras once (needs pip):")
        print(f"    {python} -m pip install -r requirements-desktop.txt")
        print("\nNo pip on this machine? Install the wheels without it:")
        print(f"    {python} tools\\fetch_wheels.py --dest .wheels flet-desktop==1.0.5 rich")
        print(f"    {python} tools\\install_wheels.py --src .wheels --dest <site-packages>")
        print("\nNote: the first window launch downloads the Flutter client (~100 MB) into")
        print("~/.flet — a one-time step, it needs internet that one time.")
        print("\nServing only the web UI in the meantime.")
        return 0

    banner("Starting the Flet desktop UI")
    print(f"client cache: {SERVER_ROOT / '.flet-home' / '.flet' / 'client'}")
    print("(first launch downloads ~100 MB there; one time only)\n")
    try:
        return subprocess.call(
            [str(python), str(flet_app)],
            cwd=str(flet_app.parent),  # assets/ and desktop_prefs.json live there
            env=flet_cache_env(env),
        )
    except OSError as exc:
        print(f"could not start Flet: {exc}")
        return 1


def lan_address() -> str:
    """This machine's address on the local network, for phones on the same Wi-Fi.

    Opening a UDP socket to a public IP sends no packets; it just makes the OS pick the
    interface that would be used, whose address is the one a phone can reach.
    """

    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return HOST
    finally:
        sock.close()


def run_flet_web(python: Path, env: dict[str, str], port: int) -> int:
    """Serve the Flet UI as a web page so a phone can open it in a browser.

    The Python side keeps running here - the phone only renders - so the app can still talk
    to the backend on the loopback address. Only this one port needs to be reachable.
    """

    flet_app = FRONTEND_ROOT / "desktop" / "app.py"
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util as u\n"
            "missing = [n for n in ('flet', 'flet_web') if u.find_spec(n) is None]\n"
            "print(','.join(missing))\n"
            "raise SystemExit(1 if missing else 0)\n",
        ],
        cwd=str(SERVER_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        print("\nWeb mode needs the flet-web package (a browser tab instead of a window).")
        if (probe.stdout or "").strip():
            print(f"Missing: {(probe.stdout or '').strip()}")
        print(f"    {python} -m pip install flet-web==1.0.5")
        print("\nThe web UI at the URL above still works, and needs none of this.")
        return 0

    address = lan_address()
    print()
    banner("Flet UI as a web page (open it on your phone)")
    print(f"  this machine : http://{HOST}:{port}/")
    if address != HOST:
        print(f"  same Wi-Fi   : http://{address}:{port}/    <- 手機用這個")
    print("\n  Phone and computer must be on the same network.")
    print("  The Python side runs here, so the backend URL does not change.")
    print("  Press Ctrl+C to stop.\n")

    child_env = {
        **flet_cache_env(env),
        "VOLTSPACE_FLET_WEB": "1",
        "VOLTSPACE_FLET_HOST": PUBLIC_HOST,
        "VOLTSPACE_FLET_PORT": str(port),
    }
    return subprocess.call(
        [str(python), str(flet_app)], cwd=str(flet_app.parent), env=child_env
    )


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
    venv_dir = SERVER_ROOT / ".venv"

    if not venv_dir.exists():
        print(f"creating     : {venv_dir}")
        result = subprocess.run(
            [str(base), "-m", "venv", str(venv_dir)], cwd=str(SERVER_ROOT)
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

    requirements = SERVER_ROOT / "requirements.txt"
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
        result = subprocess.run(command, cwd=str(SERVER_ROOT))
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


def load_dotenv(path: Path | None = None) -> list[str]:
    """Read ``server/.env`` into the environment, without overriding what is already set.

    Deliberately dependency-free and deliberately *not* a full dotenv implementation:
    ``KEY=VALUE`` per line, ``#`` comments, optional surrounding quotes. Real environment
    variables always win, so a hosting platform's settings are never silently replaced by
    a file that happened to be copied along.

    Returns the names it set, so the caller can print them.
    """

    env_file = path or (SERVER_ROOT / ".env")
    if not env_file.is_file():
        return []

    applied: list[str] = []
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied


def resolve_bind(
    host: str | None = None, port: int | None = None
) -> tuple[str, int, bool]:
    """Work out which address to bind, honouring the conventions of hosting platforms.

    Returns ``(host, port, is_public)``.

    Locally the app should listen on the loopback address so it is not exposed to the
    network by accident. A hosting platform (Render, Railway, Fly, Hugging Face, ...)
    instead injects a ``PORT`` environment variable and expects the process to listen on
    ``0.0.0.0``; binding 127.0.0.1 there makes the health check fail even though the log
    looks healthy. An explicit ``--host`` / ``--port`` always wins over the environment.
    """

    env_port = os.environ.get("PORT", "").strip()
    platform_port = int(env_port) if env_port.isdigit() else None

    resolved_port = port or platform_port or DEFAULT_PORT

    explicit_host = host or os.environ.get("HOST", "").strip() or None
    if explicit_host:
        resolved_host = explicit_host
    elif platform_port is not None:
        resolved_host = PUBLIC_HOST
    else:
        resolved_host = HOST

    is_public = resolved_host not in {HOST, "localhost", "::1"}
    return resolved_host, resolved_port, is_public


def display_url(host: str, port: int) -> str:
    """The URL to print and open in a browser (0.0.0.0 is not clickable)."""

    shown = HOST if host in {PUBLIC_HOST, "::"} else host
    return f"http://{shown}:{port}/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the VoltSpace app",
        epilog="First run on a new machine: python start.py --setup",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="連接埠（預設 8000；雲端平台會用 $PORT）",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="綁定位址（預設 127.0.0.1；有 $PORT 時自動用 0.0.0.0）",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--flet", action="store_true", help="also launch the Flet desktop UI")
    parser.add_argument(
        "--flet-web",
        nargs="?",
        type=int,
        const=8550,
        default=None,
        metavar="PORT",
        help="把 Flet 介面開成網頁（手機/平板可用瀏覽器開），預設埠 8550",
    )
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
    # Loading .env before build_env means the storage backend is chosen from it too.
    dotenv_keys = load_dotenv()
    python, extra = choose_runtime()
    env = build_env(extra)
    print(f"python : {python}")
    if extra.get("EXTRA_LIBS"):
        print(f"libs   : {extra['EXTRA_LIBS']}")
    print(f"data   : {env['VOLTSPACE_DATA_DIR']}")
    if dotenv_keys:
        print(f".env   : loaded {', '.join(sorted(dotenv_keys))}")

    if args.check:
        from_check = subprocess.run(
            [str(python), "-m", "app.data_check"], cwd=str(SERVER_ROOT), env=env
        )
        print("\nenvironment OK" if from_check.returncode == 0 else "\nenvironment has problems")
        return from_check.returncode

    host, port, is_public = resolve_bind(args.host, args.port)
    env_port = os.environ.get("PORT", "").strip()
    if not port_free(port):
        if env_port.isdigit():
            # The platform routes this exact port; picking another one would silently
            # break the deployment, so fail loudly instead.
            print(f"\nport {port} is busy, but $PORT is set - not switching ports")
            return 1
        replacement = find_free_port(port + 1)
        print(f"\nport {port} is busy; using {replacement} instead")
        port = replacement

    url = display_url(host, port)
    command = [
        str(python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
        # Behind a reverse proxy the client address arrives in X-Forwarded-*, so the
        # request URL in the logs and in /docs is right.
        "--proxy-headers",
    ]
    if args.reload:
        command.append("--reload")

    banner(f"Serving the app on {url}")
    if is_public:
        print(f"listening on {host}:{port} - reachable from other machines\n")
    print("Press Ctrl+C to stop.\n")
    server = subprocess.Popen(command, cwd=str(SERVER_ROOT), env=env)

    try:
        if wait_for_health(f"http://{HOST}:{port}/health"):
            print(f"backend ready -> {url}")
            print(f"API docs      -> {url}docs")
            if not args.no_browser and not is_public:
                open_browser_later(url)
        else:
            print("backend did not become ready in time; check the log above")
            return server.wait(timeout=1)

        if args.flet:
            return run_flet(python, env)

        if args.flet_web:
            return run_flet_web(python, env, args.flet_web)

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
