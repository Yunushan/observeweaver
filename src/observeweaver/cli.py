"""ObserveWeaver command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from observeweaver import __version__
from observeweaver.config import ConfigError, load_config, validate_config
from observeweaver.render import render
from observeweaver.secrets import write_secret_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="owctl",
        description="Validate and render ObserveWeaver deployment configuration.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a canonical config file.")
    validate.add_argument("--config", required=True, type=Path)

    render_command = subparsers.add_parser(
        "render", help="Render non-secret deployment artifacts."
    )
    render_command.add_argument("--config", required=True, type=Path)
    render_command.add_argument("--output", default=Path("build"), type=Path)

    secret_command = subparsers.add_parser(
        "secrets", help="Generate a gitignored deployment secret file."
    )
    secret_command.add_argument("--output", required=True, type=Path)
    secret_command.add_argument("--force", action="store_true")
    return parser


def _validated_config(path: Path) -> tuple[dict, int]:
    try:
        config = load_config(path)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return {}, 2
    result = validate_config(config)
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return config, 0 if result.valid else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "secrets":
        try:
            path = write_secret_file(args.output, force=args.force)
        except FileExistsError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"Created secret file: {path}")
        return 0

    config, status = _validated_config(args.config)
    if status:
        return status
    if args.command == "validate":
        print(f"Configuration is valid: {args.config}")
        return 0
    if args.command == "render":
        created = render(config, args.output)
        print(f"Rendered {len(created)} files:")
        for path in created:
            print(f"  {path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
