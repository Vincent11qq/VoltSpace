"""Determine a dependency set that installs WITHOUT a compiler on two Python versions.

For every package it finds the newest stable release that ships a prebuilt wheel for
each requested interpreter tag (pure-python wheels count for all of them), and it
resolves ``pydantic`` to a ``pydantic-core`` version that is itself available.

Usage::

    python tools/resolve_pins.py --tag cp312 --tag cp314
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

TAGS = {"win32": "win_amd64", "darwin": "macosx", "linux": "manylinux"}
DEFAULT_PACKAGES = ["fastapi", "uvicorn", "pydantic", "pytest", "httpx"]


def platform_token() -> str:
    return TAGS.get(sys.platform, "manylinux")


def fetch(package: str, version: str | None = None) -> dict:
    url = f"https://pypi.org/pypi/{package}"
    if version:
        url += f"/{version}"
    url += "/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def stable(version: str) -> bool:
    return not re.search(r"(a|b|rc|\.dev|\.post)\d*$", version)


def version_key(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)) or (0,)


def wheels_of(files: list[dict]) -> list[str]:
    return [f["filename"] for f in files if f.get("filename", "").endswith(".whl")]


def satisfies(files: list[dict], tags: list[str], platform: str) -> bool:
    """True when this release installs on every tag without building from source."""

    names = wheels_of(files)
    if any("py3-none-any" in name for name in names):
        return True  # pure python works on all tags
    for tag in tags:
        if not any(tag in name and platform in name for name in names):
            return False
    return True


def newest_ok(package: str, tags: list[str], platform: str) -> tuple[str | None, list[str]]:
    data = fetch(package)
    releases = data["releases"]
    candidates = sorted((v for v in releases if stable(v)), key=version_key)
    ok = [v for v in candidates if satisfies(releases[v], tags, platform)]
    return (ok[-1] if ok else None), ok[-6:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", action="append", default=None)
    parser.add_argument("--package", action="append")
    args = parser.parse_args()

    tags = args.tag or [f"cp{sys.version_info.major}{sys.version_info.minor}"]
    platform = platform_token()
    packages = args.package or DEFAULT_PACKAGES

    print(f"tags={tags}  platform={platform}\n")

    chosen: dict[str, str] = {}
    for package in packages:
        newest, recent = newest_ok(package, tags, platform)
        chosen[package] = newest
        print(f"{package:16} newest installable: {newest}")
        print(f"{'':16} recent: {', '.join(recent)}")

    print("\n--- resolved set ---")
    for package, version in chosen.items():
        if version:
            print(f"{package}=={version}")

    # pydantic pins pydantic-core exactly; confirm that core is also installable.
    if chosen.get("pydantic"):
        info = fetch("pydantic", chosen["pydantic"])["info"]
        requires = [r for r in (info.get("requires_dist") or []) if "pydantic-core" in r]
        print(f"\npydantic {chosen['pydantic']} requires -> {requires}")
        core = requires[0].split("==")[-1].split(";")[0].strip() if requires else None
        if core:
            core_data = fetch("pydantic-core")
            ok = core in core_data["releases"] and satisfies(
                core_data["releases"][core], tags, platform
            )
            print(f"pydantic-core {core} installable on {tags}: {ok}")
            if not ok:
                print("  [!] that pydantic release needs a source build; step down")
                data = fetch("pydantic")
                for version in sorted(
                    (v for v in data["releases"] if stable(v)), key=version_key, reverse=True
                ):
                    info = fetch("pydantic", version)["info"]
                    req = [
                        r for r in (info.get("requires_dist") or []) if "pydantic-core" in r
                    ]
                    if not req:
                        continue
                    candidate_core = req[0].split("==")[-1].split(";")[0].strip()
                    if (
                        candidate_core in core_data["releases"]
                        and satisfies(core_data["releases"][candidate_core], tags, platform)
                        and satisfies(data["releases"][version], tags, platform)
                    ):
                        print(f"  -> use pydantic=={version} (pydantic-core=={candidate_core})")
                        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
