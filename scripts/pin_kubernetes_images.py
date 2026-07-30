#!/usr/bin/env python3
"""Helm post-renderer that replaces every known chart image with a digest lock."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

LOCKFILE = Path(__file__).resolve().parents[1] / "versions" / "kubernetes-images.lock.yml"
IMAGE_LINE = re.compile(
    r"^(?P<prefix>\s*image:\s*)(?P<quote>[\"']?)(?P<image>[^\s\"']+)(?P=quote)(?P<suffix>\s*(?:#.*)?\n?)$"
)


def load_locks() -> dict[str, str]:
    content = yaml.safe_load(LOCKFILE.read_text(encoding="utf-8"))
    locks = content.get("chartImages")
    if not isinstance(locks, dict) or not locks:
        raise RuntimeError(f"{LOCKFILE} has no chartImages lock map")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in locks.items()):
        raise RuntimeError(f"{LOCKFILE} contains a non-string image lock")
    return locks


def main() -> int:
    locks = load_locks()
    known_digests = set(locks.values())
    unknown: list[str] = []
    output: list[str] = []
    for line in sys.stdin:
        match = IMAGE_LINE.match(line)
        if match is None:
            output.append(line)
            continue
        image = match.group("image")
        if image in known_digests:
            output.append(line)
            continue
        pinned = locks.get(image)
        if pinned is None:
            unknown.append(image)
            output.append(line)
            continue
        output.append(
            f"{match.group('prefix')}{match.group('quote')}{pinned}"
            f"{match.group('quote')}{match.group('suffix')}"
        )

    if unknown:
        unexpected = ", ".join(sorted(set(unknown)))
        print(f"ERROR: unpinned Kubernetes chart image(s): {unexpected}", file=sys.stderr)
        return 1
    sys.stdout.write("".join(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
