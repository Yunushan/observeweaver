#!/usr/bin/env python3
"""Fail if a Kubernetes chart image tag no longer resolves to its digest lock."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

import yaml

LOCKFILE = Path(__file__).resolve().parents[1] / "versions" / "kubernetes-images.lock.yml"


def resolve_digest(docker: str, image: str) -> str:
    result = subprocess.run(
        [
            docker,
            "buildx",
            "imagetools",
            "inspect",
            image,
            "--format",
            "{{.Manifest.Digest}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    docker = which("docker")
    if docker is None:
        print("ERROR: docker is required to verify Kubernetes image locks", file=sys.stderr)
        return 2
    content = yaml.safe_load(LOCKFILE.read_text(encoding="utf-8"))
    locks = content.get("chartImages", {})
    failures: list[str] = []
    for image, locked_reference in sorted(locks.items()):
        expected = locked_reference.split("@", 1)[1]
        try:
            actual = resolve_digest(docker, image)
        except subprocess.CalledProcessError as error:
            failures.append(f"{image}: cannot resolve image: {error.stderr.strip()}")
            continue
        if actual != expected:
            failures.append(f"{image}: resolved to {actual}, expected {expected}")
        else:
            print(f"PASS {image}: {actual}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
