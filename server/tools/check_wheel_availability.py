"""Check which releases of a package ship a prebuilt wheel for a given Python version.

Queries the PyPI JSON API directly (the Tsinghua mirror's JSON endpoint is stale) and
reports, for each package, the newest versions that need **no** Rust/C toolchain.

Usage::

    python tools/check_wheel_availability.py                    # current interpreter
    python tools/check_wheel_availability.py --tag cp314        # specific ABI tag
    python tools/check_wheel_availability.py --index https://pypi.org/pypi
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

DEFAULT_INDEX = "https://pypi.org/pypi"
DEFAULT_PACKAGES = ["pydantic-core", "pydantic", "fastapi", "starlette", "uvicorn", "pytest", "httpx"]
PLATFORMS = {"win32": ["win_amd64", "win32"], "darwin": ["macosx"], "linux": ["manylinux", "linux_"]}


def platform_tokens() -> list[str]:
    if sys.platform == "win32":
        return PLATFORMS["win32"]
    if sys.platform == "darwin":
        return PLATFORMS["macosx"]
    return PLATFORMS["linux"]


def fetch(package: str, index: str) -> dict:
    with urllib.request.urlopen(f"{index}/{package}/json", timeout=30) as response:
        return json.load(response)


def stable(version: str) -> bool:
    return not re.search(r"(a|b|rc|\.dev)\d*$", version)


def version_key(version: str) -> tuple:
    return tuple(int(part) for part in re.findall(r"\d+", version)) or (0,)


def find_wheel(data: dict, version: str, tag: str, platforms: list[str]) -> str | None:
    for item in data.get("releases", {}).get(version, []):
        name = item.get("filename", "")
        if not name.endswith(".whl"):
            continue
        if "py3-none-any" in name:
            return name  # pure python, always fine
        if tag in name and any(token in name for token in platforms):
            return name
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default=f"cp{sys.version_info.major}{sys.version_info.minor}")
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--package", action="append")
    args = parser.parse_args()
    packages = args.package or DEFAULT_PACKAGES
    platforms = platform_tokens()

    print(f"target interpreter tag: {args.tag}   platforms: {', '.join(platforms)}")
    print(f"index: {args.index}\n")

    for package in packages:
        try:
            data = fetch(package, args.index)
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            print(f"== {package} ==\n   FAILED to query: {type(exc).__name__}\n")
            continue

        versions = sorted(
            (v for v in data.get("releases", {}) if stable(v)), key=version_key
        )
        latest = data["info"]["version"]
        ready = [v for v in versions if find_wheel(data, v, args.tag, platforms)]

        print(f"== {package} ==")
        print(f"   latest on PyPI      : {latest}")
        if ready:
            newest = ready[-1]
            print(f"   newest with wheel   : {newest}  ->  {find_wheel(data, newest, args.tag, platforms)}")
            print(f"   recent with wheel   : {', '.join(ready[-6:])}")
            if version_key(latest) > version_key(newest):
                print(f"   [!] {latest} needs a source build on {args.tag}")
        else:
            print(f"   [X] NO {args.tag} wheel for any release -> source build required")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
