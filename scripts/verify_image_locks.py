#!/usr/bin/env python3
"""Fail if a Docker image tag no longer resolves to its approved digest."""

from __future__ import annotations

import subprocess
import sys
from shutil import which

from observeweaver.render import DOCKER_IMAGE_LOCKS, DOCKER_IMAGE_TAGS


def resolve_digest(image: str) -> str:
    docker = which("docker")
    if docker is None:
        raise RuntimeError("docker is required to verify immutable image locks")
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
    failures: list[str] = []
    for name, tagged_image in sorted(DOCKER_IMAGE_TAGS.items()):
        expected = DOCKER_IMAGE_LOCKS[name].split("@", 1)[1]
        try:
            actual = resolve_digest(tagged_image)
        except (RuntimeError, subprocess.CalledProcessError) as error:
            if isinstance(error, subprocess.CalledProcessError):
                detail = error.stderr.strip()
            else:
                detail = str(error)
            failures.append(
                f"{name}: cannot resolve {tagged_image}: {detail}"
            )
            continue
        if actual != expected:
            failures.append(
                f"{name}: {tagged_image} resolved to {actual}, expected {expected}"
            )
        else:
            print(f"PASS {name}: {actual}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
