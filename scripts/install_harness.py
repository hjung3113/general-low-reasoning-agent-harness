#!/usr/bin/env python3
"""Human-facing installer for the generalized harness source tree."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import harness


PROFILE_PRESETS = {
    "minimal": {
        "description": "Core planning guardrails with the stack-neutral workflow core.",
        "profiles": "generic",
        "packs": ("workflow-core",),
    },
    "dotnet-etl": {
        "description": ".NET/C# ETL work without assuming a database engine.",
        "profiles": "generic",
        "packs": ("workflow-core", "tech-csharp", "workflow-etl", "workflow-data-processing", "workflow-tdd"),
    },
    "python-etl": {
        "description": "Python ETL and data pipeline work.",
        "profiles": "generic",
        "packs": ("workflow-core", "tech-python", "workflow-etl", "workflow-data-processing", "workflow-tdd"),
    },
    "react-tailwind-typescript-web": {
        "description": "React, TypeScript, and Tailwind web application work.",
        "profiles": "generic",
        "packs": (
            "workflow-core",
            "tech-react",
            "tech-typescript",
            "tech-tailwind",
            "workflow-web-development",
            "workflow-tdd",
        ),
    },
    "full": {
        "description": "All shipped skill packs. Adapters are still selected separately.",
        "profiles": "generic",
        "packs": "ALL",
    },
}

ADAPTER_OPTIONS = (
    ("roo", "Roo only"),
    ("opencode", "OpenCode only"),
    ("both", "Roo and OpenCode"),
    ("none", "Core planning files only"),
)


def prompt_value(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def prompt_existing_absolute_target(default: Path | None = None) -> Path:
    default_text = str(default.resolve()) if default else None
    while True:
        raw = prompt_value("Target path (absolute existing directory)", default_text)
        target = Path(raw).expanduser()
        if not target.is_absolute():
            print("Target path must be absolute. Try again.")
            continue
        if not target.exists():
            print("Target path does not exist. Create it first, then try again.")
            continue
        if not target.is_dir():
            print("Target path must be a directory. Try again.")
            continue
        return target


def prompt_choice(label: str, options: list[tuple[str, str]], default: str) -> str:
    print(label)
    for index, (value, description) in enumerate(options, start=1):
        marker = " (default)" if value == default else ""
        print(f"  {index}. {value} - {description}{marker}")
    raw = prompt_value("Choose by number or name", default)
    return parse_choice(raw, options)


def normalize_adapter_choice(value: str) -> str:
    parsed = harness.parse_scope(value, default={"roo"})
    if parsed == {"roo", "opencode"}:
        return "both"
    if parsed == {"roo"}:
        return "roo"
    if parsed == {"opencode"}:
        return "opencode"
    if not parsed:
        return "none"
    return value


def parse_choice(raw: str, options: list[tuple[str, str]]) -> str:
    values = [value for value, _ in options]
    item = raw.strip().lower()
    if item.isdigit() and 1 <= int(item) <= len(values):
        return values[int(item) - 1]
    if item in values:
        return item
    raise SystemExit(f"Unknown choice: {raw}. Expected one of: {', '.join(values)}")


def parse_pack_selection(raw: str, pack_options: list[str]) -> list[str]:
    selected: list[str] = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        normalized = item.lower()
        if normalized in {"none", "no", "skip"}:
            continue
        if normalized.isdigit() and 1 <= int(normalized) <= len(pack_options):
            selected.append(pack_options[int(normalized) - 1])
        elif normalized in pack_options:
            selected.append(normalized)
        else:
            raise SystemExit(f"Unknown skill pack: {item}. Expected a shown number or pack name.")
    return selected


def resolve_profile_preset(name: str, pack_names: list[str]) -> tuple[str, list[str]]:
    if name not in PROFILE_PRESETS:
        raise SystemExit(f"Unknown profile preset: {name}")
    preset = PROFILE_PRESETS[name]
    profiles = str(preset["profiles"])
    packs = pack_names if preset["packs"] == "ALL" else list(preset["packs"])
    missing = sorted(set(packs) - set(pack_names))
    if missing:
        raise SystemExit(f"Profile preset {name} references unknown skill packs: {', '.join(missing)}")
    return profiles, packs


def pack_capability_summary(scopes: dict[str, list[str]], pack: str) -> str:
    metadata = harness.load_manifest_data(harness.repo_root()).get("packs", {})
    if isinstance(metadata, dict):
        info = metadata.get(pack, {})
        if isinstance(info, dict):
            capabilities = info.get("capabilities", [])
            if isinstance(capabilities, list) and capabilities:
                return "; ".join(str(item) for item in capabilities[:3])
    return ""


def prompt_interactive(args: argparse.Namespace) -> argparse.Namespace:
    scopes = harness.available_scopes(harness.repo_root())
    pack_names = scopes["packs"]
    requested_packs = [] if args.packs is None else parse_pack_selection(args.packs, pack_names)
    print("Interactive harness install")
    args.target = prompt_existing_absolute_target(args.target)
    args.adapters = prompt_choice("Adapter", list(ADAPTER_OPTIONS), normalize_adapter_choice(args.adapters))
    preset_options = [(name, str(config["description"])) for name, config in PROFILE_PRESETS.items()]
    preset = prompt_choice("Profile", preset_options, "minimal")
    args.profiles, included_packs = resolve_profile_preset(preset, pack_names)
    print("Included skill packs:")
    for pack in included_packs:
        summary = pack_capability_summary(scopes, pack)
        suffix = f" - {summary}" if summary else ""
        print(f"  - {pack}{suffix}")
    extra_options = [pack for pack in pack_names if pack not in included_packs]
    default_extra = ",".join(pack for pack in requested_packs if pack in extra_options) or "none"
    if extra_options:
        print("Additional skill packs:")
        for index, pack in enumerate(extra_options, start=1):
            summary = pack_capability_summary(scopes, pack)
            suffix = f" - {summary}" if summary else ""
            print(f"  {index}. {pack}{suffix}")
        raw_packs = prompt_value("Additional packs by shown number or name (comma-separated, none to skip)", default_extra)
        extra_packs = parse_pack_selection(raw_packs, extra_options)
    else:
        print("Additional skill packs: none available")
        extra_packs = []
    args.packs = ",".join(dict.fromkeys([*included_packs, *extra_packs]))
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
    argv.extend(["--adapters", args.adapters])
    if args.profiles:
        argv.extend(["--profiles", args.profiles])
    if args.packs:
        argv.extend(["--packs", args.packs])
    return argv


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--adapters", default="roo")
    parser.add_argument("--profiles", default="generic")
    parser.add_argument("--packs", default=None)
    parser.add_argument("--version", dest="release_version", default=None)
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    if args.interactive:
        args = prompt_interactive(args)
    if args.target is None:
        parser.error("--target is required unless --interactive supplies it")
    delegated = build_harness_argv(args)
    print("Equivalent command: " + shlex.join(["python3", "scripts/harness.py", *delegated]))
    return harness.run(delegated)


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
