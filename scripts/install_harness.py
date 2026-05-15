#!/usr/bin/env python3
"""Human-facing installer for the generalized harness source tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import harness


def prompt_value(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def prompt_interactive(args: argparse.Namespace) -> argparse.Namespace:
    scopes = harness.available_scopes(harness.repo_root())
    print("Interactive harness install")
    args.target = Path(prompt_value("Target path", str(args.target) if args.target else None))
    args.adapters = prompt_value("Adapters (roo, opencode, both, none)", args.adapters)
    args.profiles = prompt_value("Profiles (" + ", ".join(scopes["profiles"]) + ")", args.profiles)
    print("Available skill packs:")
    for index, pack in enumerate(scopes["packs"], start=1):
        marker = " (recommended)" if pack == "workflow-core" else ""
        print(f"  {index}. {pack}{marker}")
    raw_packs = prompt_value("Packs by name or comma-separated number", args.packs)
    selected: list[str] = []
    for item in [part.strip() for part in raw_packs.split(",") if part.strip()]:
        if item.isdigit() and 1 <= int(item) <= len(scopes["packs"]):
            selected.append(scopes["packs"][int(item) - 1])
        else:
            selected.append(item)
    args.packs = ",".join(selected) if selected else args.packs
    dry_answer = prompt_value("Dry-run first? (yes/no)", "yes").lower()
    args.dry_run = dry_answer not in {"n", "no"}
    return args


def build_harness_argv(args: argparse.Namespace) -> list[str]:
    argv: list[str] = []
    if args.release_version:
        argv.extend(["--version", args.release_version])
    argv.extend(["init", "--target", str(args.target)])
    if args.dry_run:
        argv.append("--dry-run")
    argv.extend(["--adapters", args.adapters, "--profiles", args.profiles, "--packs", args.packs])
    return argv


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--adapters", default="roo")
    parser.add_argument("--profiles", default="generic")
    parser.add_argument("--packs", default="workflow-core")
    parser.add_argument("--version", dest="release_version", default=None)
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    if args.interactive:
        args = prompt_interactive(args)
    if args.target is None:
        parser.error("--target is required unless --interactive supplies it")
    delegated = build_harness_argv(args)
    print("Equivalent command: python3 scripts/harness.py " + " ".join(delegated))
    return harness.run(delegated)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
