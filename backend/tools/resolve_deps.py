"""Resolve and download a complete, offline-installable wheel set for pinned top-level packages.

Unlike ``fetch_wheels.py`` (which uses a hand-maintained dependency map), this reads each
package's ``Requires-Dist`` metadata from PyPI and walks the real dependency graph, skipping
extras and environment markers that do not apply to this interpreter. That keeps the wheel
set correct when a dependency adds a new runtime requirement (for example
``fastapi 0.143`` pulling in ``annotated-doc``).

Usage::

    python tools/resolve_deps.py --dest .wheels --tag cp314 \
        fastapi==0.143.0 uvicorn==0.54.0 pydantic==2.14.1 pydantic-core==2.50.1 \
        pytest==9.1.1 httpx==0.28.1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PLATFORMS = {"win32": ["win_amd64", "win32"], "darwin": ["macosx"], "linux": ["manylinux"]}


def platform_tokens() -> list[str]:
    return PLATFORMS.get(sys.platform, ["manylinux"])


def fetch_json(package: str) -> dict:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as response:
        return json.load(response)


def stable(version: str) -> bool:
    return not re.search(r"(a|b|rc|\.dev)\d*$", version)


def version_key(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)


def choose_wheel(releases: dict, version: str, tags: list[str], platforms: list[str]) -> str | None:
    """Best wheel URL for this version, or None when only an sdist exists."""

    files = releases.get(version, [])
    wheels = [f for f in files if f.get("filename", "").endswith(".whl")]
    if not wheels:
        return None

    def rank(item: dict) -> tuple:
        name = item["filename"]
        exact = any(tag in name for tag in tags)
        plat = any(token in name for token in platforms)
        pure = "py3-none-any" in name
        return (exact or pure, plat or pure, version_key(version))

    # Prefer a wheel matching the target interpreter, then platform, then any.
    for predicate in (
        lambda n: any(t in n for t in tags) and any(p in n for p in platforms),
        lambda n: any(p in n for p in platforms),
        lambda n: "py3-none-any" in n,
    ):
        matches = [w for w in wheels if predicate(w["filename"])]
        if matches:
            return sorted(matches, key=rank)[-1]["url"]
    return None


def parse_requirement(requirement: str) -> tuple[str, str | None] | None:
    """Return ``(name, version)`` from a Requires-Dist entry, or None to skip it."""

    if ";" in requirement:
        marker = requirement.split(";", 1)[1].strip()
        # Skip extras (we only need the base install) and non-Windows-only markers.
        if "extra ==" in marker:
            return None
    core = requirement.split(";", 1)[0].strip()
    if "[" in core:  # drop extras like uvicorn[standard]
        core = core.split("[", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9._-]+)\s*(?:\(|==)?\s*([0-9][^,;\s)]*)?", core)
    if not match:
        return None
    return match.group(1), match.group(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=".wheels")
    parser.add_argument("--tag", action="append", default=None)
    parser.add_argument("--python-version", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    parser.add_argument("specs", nargs="+")
    args = parser.parse_args()

    tags = args.tag or [f"cp{sys.version_info.major}{sys.version_info.minor}"]
    platforms = platform_tokens()
    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    wanted: dict[str, str | None] = {}
    queue: list[str] = []
    for spec in args.specs:
        name, _, version = spec.partition("==")
        key = re.sub(r"[-_.]+", "-", name).lower()
        wanted[key] = version.strip() or None
        queue.append(key)

    installed: dict[str, str] = {}
    skipped: list[str] = []
    visited: set[str] = set()

    while queue:
        name = queue.pop(0)
        if name in visited:
            continue
        visited.add(name)

        try:
            data = fetch_json(name)
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print(f"  ! {name}: {type(exc).__name__}")
            skipped.append(name)
            continue

        releases = data["releases"]
        pinned = wanted.get(name)

        if pinned and pinned in releases:
            version = pinned
        else:
            candidates = sorted((v for v in releases if stable(v)), key=version_key)
            version = None
            for candidate in reversed(candidates):
                if choose_wheel(releases, candidate, tags, platforms):
                    version = candidate
                    break
            if version is None:
                print(f"  ! {name}: no wheel for tags {tags}")
                skipped.append(name)
                continue

        url = choose_wheel(releases, version, tags, platforms)
        if not url:
            print(f"  ! {name}=={version}: no usable wheel")
            skipped.append(name)
            continue

        filename = Path(urllib.parse.urlparse(url).path).name
        target = dest / filename
        if not target.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                target.write_bytes(response.read())
        installed[name] = version
        print(f"  + {name}=={version}  ({filename})", flush=True)

        # Recurse into this version's runtime requirements.
        info = fetch_json(f"{name}/{version}")["info"]
        for requirement in info.get("requires_dist") or []:
            parsed = parse_requirement(requirement)
            if not parsed:
                continue
            dep_name, dep_version = parsed
            dep_key = re.sub(r"[-_.]+", "-", dep_name).lower()
            if dep_key in visited:
                continue
            # Respect an exact pin from the metadata so the graph stays consistent.
            if dep_key not in wanted or wanted[dep_key] is None:
                wanted[dep_key] = dep_version
            queue.append(dep_key)

    print(f"\n{len(installed)} packages -> {dest}")
    if skipped:
        print(f"skipped: {', '.join(sorted(set(skipped)))}")
    print("\nresolved pins:")
    for name in sorted(installed):
        print(f"  {name}=={installed[name]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
