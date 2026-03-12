#!/usr/bin/env python
"""
Bump the API version used by FastAPI and OpenAPI.

Usage:
    python scripts/bump_version.py            # bump patch (default)
    python scripts/bump_version.py --part minor
    python scripts/bump_version.py --dry-run
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Literal


VERSION_FILE = Path(__file__).resolve().parents[1] / "backend" / "version.py"
VERSION_PATTERN = re.compile(r'(__version__\s*=\s*["\'])(?P<version>\d+\.\d+\.\d+)(["\'])')


def parse_current_version() -> tuple[str, str]:
    content = VERSION_FILE.read_text()
    match = VERSION_PATTERN.search(content)
    if not match:
        raise RuntimeError(f"Could not find __version__ in {VERSION_FILE}")
    return match.group("version"), content


def bump(version: str, part: Literal["major", "minor", "patch"]) -> str:
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def write_version(content: str, new_version: str) -> None:
    updated = VERSION_PATTERN.sub(fr'\g<1>{new_version}\g<3>', content, count=1)
    VERSION_FILE.write_text(updated)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump API version.")
    parser.add_argument(
        "--part",
        choices=["major", "minor", "patch"],
        default="patch",
        help="Which component of semver to bump (default: patch).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate the next version without writing it to disk.",
    )
    args = parser.parse_args()

    current, content = parse_current_version()
    next_version = bump(current, args.part)

    if args.dry_run:
        print(f"[dry-run] {current} -> {next_version}")
        return

    write_version(content, next_version)
    print(f"Bumped version: {current} -> {next_version}")


if __name__ == "__main__":
    main()

