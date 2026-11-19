"""Install already-downloaded wheels into a target directory without using pip.

``pip install`` could not write its temporary unpack directories in this sandbox, so
this script performs the equivalent work with the standard library: a wheel is a ZIP
archive whose ``*.data/purelib`` (or ``platlib``) members go to the target root and
whose remaining members map onto the target root as-is.

Usage::

    python tools/install_wheels.py --src .wheels --dest .pylibs
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

# Members that must never overwrite the target root.
SKIP_PREFIXES = ("_dsh_",)


def distribution_name(wheel: Path) -> tuple[str, str]:
    stem = wheel.name[: -len(".whl")]
    parts = stem.split("-")
    return parts[0], parts[1]


def install_wheel(wheel: Path, dest: Path) -> tuple[str, int]:
    name, version = distribution_name(wheel)
    written = 0
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            raw = member.filename
            if raw.endswith("/") or raw.startswith(SKIP_PREFIXES):
                continue
            # ``<name>-<version>.data/<scheme>/<path>`` -> ``<dest>/<path>``
            parts = raw.split("/")
            if len(parts) > 2 and parts[0].endswith(".data"):
                scheme, relative = parts[1], "/".join(parts[2:])
                if scheme not in ("purelib", "platlib"):
                    # scripts/headers/data are not needed for this project.
                    continue
                target = dest / relative
            else:
                target = dest / raw

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as output:
                shutil.copyfileobj(source, output)
            written += 1
    return f"{name}=={version}", written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=".wheels")
    parser.add_argument("--dest", default=".pylibs")
    parser.add_argument("--clean", action="store_true", help="remove the target first")
    args = parser.parse_args()

    src = Path(args.src).resolve()
    dest = Path(args.dest).resolve()
    if args.clean and dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    wheels = sorted(src.glob("*.whl"))
    if not wheels:
        print(f"no wheels in {src}", file=sys.stderr)
        return 1

    for wheel in wheels:
        label, written = install_wheel(wheel, dest)
        print(f"installed {label} ({written} files)", flush=True)

    print(f"\ntarget: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
