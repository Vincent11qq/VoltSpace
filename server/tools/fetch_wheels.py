"""Minimal PEP 503 wheel resolver/downloader used to bootstrap the dev environment.

``pip install`` from any index hung in this sandbox, so this script resolves each
requirement (plus its dependencies) against a PEP 503 simple index, downloads the
best-matching wheel into a local cache directory, and prints the paths. The wheels are
then installed with ``pip install --no-index --find-links <cache>`` which needs no
network and no index resolution.

Usage::

    python tools/fetch_wheels.py --index https://pypi.tuna.tsinghua.edu.cn/simple \
        --dest .wheels fastapi pydantic pytest httpx uvicorn
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

# Only the versions we care about; avoids pulling a huge version graph.
PIN: dict[str, str] = {
    "fastapi": "0.115.6",
    "starlette": "0.41.3",
    "pydantic": "2.10.4",
    "pydantic-core": "2.27.2",
    "annotated-types": "0.7.0",
    "typing-extensions": "4.12.2",
    "anyio": "4.7.0",
    "idna": "3.10",
    "sniffio": "1.3.1",
    "uvicorn": "0.34.0",
    "click": "8.1.8",
    "h11": "0.14.0",
    "pytest": "8.3.4",
    "iniconfig": "2.0.0",
    "packaging": "24.2",
    "pluggy": "1.5.0",
    "httpx": "0.28.1",
    "httpcore": "1.0.7",
    "certifi": "2024.12.14",
    "colorama": "0.4.6",
    "exceptiongroup": "1.2.2",
    "tomli": "2.2.1",
}

# Runtime dependencies we must also fetch (kept explicit so nothing is guessed).
DEPS: dict[str, list[str]] = {
    "fastapi": ["starlette", "pydantic", "typing-extensions"],
    "starlette": ["anyio", "typing-extensions"],
    "pydantic": ["annotated-types", "pydantic-core", "typing-extensions"],
    "pydantic-core": ["typing-extensions"],
    "anyio": ["idna", "sniffio", "typing-extensions", "exceptiongroup"],
    "uvicorn": ["click", "h11", "typing-extensions"],
    "click": ["colorama"],
    "pytest": ["iniconfig", "packaging", "pluggy", "exceptiongroup", "tomli", "colorama"],
    "httpx": ["httpcore", "idna", "certifi", "anyio"],
    "httpcore": ["h11", "certifi"],
}


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def fetch_index(index: str, package: str) -> str:
    url = f"{index.rstrip('/')}/{package}/"
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8", "replace")


def is_prerelease(filename: str) -> bool:
    return bool(re.search(r"-\d+(?:\.\d+)*[ab]|rc\d+-", filename))


def version_key(filename: str) -> tuple:
    match = re.search(r"-(\d+(?:\.\d+)*)((?:a|b|rc)\d+)?-", filename)
    if not match:
        return (0,)
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts


def platform_tags() -> list[str]:
    """Wheel platform substrings acceptable on this machine, best first."""

    if sys.platform == "win32":
        return ["win_amd64"] if sys.maxsize > 2 ** 32 else ["win32"]
    if sys.platform == "darwin":
        return ["macosx"]
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return ["manylinux", "linux_x86_64"]
    if machine in ("aarch64", "arm64"):
        return ["manylinux", "linux_aarch64"]
    return ["manylinux"]


def pick_wheel(
    links: list[str],
    package: str,
    python_tag: str,
    *,
    ignore_pins: bool = False,
    also_tag: str | None = None,
) -> str | None:
    """Choose the best wheel link for the requested interpreter.

    ``ignore_pins`` selects the newest release instead of the pinned one.
    ``also_tag`` additionally requires that the same release ships a wheel for another
    interpreter (e.g. cp314), so one pin set works on both.
    """

    wheels = [link for link in links if link.endswith(".whl")]
    wanted = None if ignore_pins else PIN.get(package)
    platforms = platform_tags()

    def matches_pin(link: str) -> bool:
        if not wanted:
            return True
        return f"-{wanted}-" in link or f"-{wanted}.post" in link

    def binary_for_platform(link: str) -> bool:
        return any(tag in link for tag in platforms)

    tiers = [
        # Exact pin + binary wheel for THIS platform and interpreter
        [
            link
            for link in wheels
            if matches_pin(link) and python_tag in link and binary_for_platform(link)
        ],
        # Exact pin + binary wheel for this platform (any interpreter tag)
        [link for link in wheels if matches_pin(link) and binary_for_platform(link)],
        # Exact pin + pure python wheel
        [link for link in wheels if matches_pin(link) and "py3-none-any" in link],
        # Anything pure python, else newest binary for this platform
        [link for link in wheels if "py3-none-any" in link],
        [link for link in wheels if binary_for_platform(link)],
    ]
    for tier in tiers:
        if not tier:
            continue
        candidates = sorted(tier, key=version_key)
        if not also_tag:
            return candidates[-1]
        # Walk newest-first until one whose release also has a wheel for the other tag.
        for link in reversed(candidates):
            version = wheel_version(link)
            if version and any(
                other.endswith(".whl")
                and wheel_version(other) == version
                and (
                    also_tag in other
                    or "py3-none-any" in other  # pure python works everywhere
                )
                for other in wheels
            ):
                return link
    return None


def wheel_version(link: str) -> str | None:
    name = link.rsplit("/", 1)[-1].split("#", 1)[0]
    match = re.match(r"[^-]+-(\d[^-]*)-", name)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--dest", default=".wheels")
    parser.add_argument("--python-tag", default=f"cp{sys.version_info.major}{sys.version_info.minor}")
    parser.add_argument(
        "--newest",
        action="store_true",
        help="ignore the built-in pin table and take the newest available release",
    )
    parser.add_argument(
        "--also-tag",
        default=None,
        help="additionally require that the release ships a wheel for this tag (e.g. cp314), "
        "so the same pin set works on two interpreters",
    )
    parser.add_argument("packages", nargs="+")
    args = parser.parse_args()

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    # Accept "name" or "name==version"; an explicit version overrides the pin table.
    overrides: dict[str, str] = {}
    queue: list[str] = []
    for package in args.packages:
        raw_name, _, raw_version = package.partition("==")
        name = normalise(raw_name)
        if raw_version:
            overrides[name] = raw_version.strip()
        if name not in queue:
            queue.append(name)
    PIN.update(overrides)

    resolved: dict[str, str] = {}
    failed: list[str] = []

    while queue:
        name = queue.pop(0)
        if name in resolved or name in failed:
            continue
        try:
            html = fetch_index(args.index, name)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name}: index error {type(exc).__name__}", flush=True)
            failed.append(name)
            continue

        links = re.findall(r'href="([^"#]+)(?:#[^"]*)?"', html)
        chosen = pick_wheel(
            links,
            name,
            args.python_tag,
            ignore_pins=args.newest,
            also_tag=args.also_tag,
        )
        if not chosen:
            print(f"  ! {name}: no wheel found", flush=True)
            failed.append(name)
            continue

        url = urllib.parse.urljoin(f"{args.index.rstrip('/')}/{name}/", chosen)
        filename = Path(urllib.parse.urlparse(chosen).path).name
        target = dest / filename
        if not target.exists():
            try:
                with urllib.request.urlopen(url) as response:
                    target.write_bytes(response.read())
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {name}: download error {type(exc).__name__}", flush=True)
                failed.append(name)
                continue
        resolved[name] = filename
        print(f"  + {name} -> {filename}", flush=True)

        for dependency in DEPS.get(name, []):
            dependency = normalise(dependency)
            if dependency not in resolved and dependency not in failed and dependency not in queue:
                queue.append(dependency)

    print(json.dumps({"resolved": resolved, "failed": failed}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
