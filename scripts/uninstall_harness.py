#!/usr/bin/env python3
"""Remove selected parts of an installed low-reasoning harness target."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import harness

from lib.operational_paths import (
    STATE_FILE_PATHS,
    OPERATIONAL_PATHS,
    INSTALL_PATHS,
)


CHOICES = {
    "1": "roo",
    "2": "opencode",
    "3": "runtime",
    "4": "core",
    "5": "docs",
}

DOCS_WARNING = "WARNING: removing planning/docs is not recommended; project planning history will be deleted."
INSTALL_STATE_WARNING = (
    "WARNING: removing .harness/installed-manifest.json disables normal harness upgrade/adopt tracking."
)


@dataclass(frozen=True)
class RemovalPlan:
    remove_paths: list[str]
    remove_blocks: list[str]
    conflicts: list[str]
    warnings: list[str]


def prompt_value(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def prompt_interactive(args: argparse.Namespace) -> argparse.Namespace:
    print("Interactive harness uninstall")
    args.target = Path(prompt_value("Target path", str(args.target) if args.target else None))
    print("Select one or more comma-separated uninstall scopes:")
    print("  1. Roo environment only")
    print("  2. OpenCode environment only")
    print("  3. Runtime harness only, excluding adapters and core protocol")
    print("  4. Core protocol only, excluding adapters, runtime, and docs")
    print("  5. Planning/docs only (not recommended)")
    args.select = prompt_value("Selection", args.select)
    selected = parse_selection(args.select)
    if selects_all_scopes(selected):
        manifest_answer = prompt_value("Also remove .harness/installed-manifest.json? (yes/no)", "no").lower()
        args.remove_install_state = manifest_answer in {"y", "yes"}
    dry_answer = prompt_value("Dry-run first? (yes/no)", "yes").lower()
    args.dry_run = dry_answer not in {"n", "no"}
    return args


def parse_selection(value: str) -> set[str]:
    selected: set[str] = set()
    for item in [part.strip() for part in value.split(",") if part.strip()]:
        if item not in CHOICES:
            raise SystemExit("Unknown uninstall selection: " + item)
        selected.add(CHOICES[item])
    if not selected:
        raise SystemExit("--select is required")
    return selected


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument(
        "--select",
        default="",
        help=(
            "Comma-separated uninstall scopes (numeric codes): "
            "1=roo, 2=opencode, 3=runtime, 4=core, 5=docs. "
            "Example: --select 1,3"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument(
        "--remove-install-state",
        action="store_true",
        help="Also remove .harness/installed-manifest.json. Requires selecting all uninstall scopes.",
    )
    # T0-3 flag split (CONTRACT-PIN §5.3). These flags iterate the
    # operational_paths.py tuples and remove only those artifacts; they do
    # NOT require --select.
    parser.add_argument(
        "--remove-state",
        action="store_true",
        help="Remove STATE_FILE_PATHS (e.g. .scratch/phase-state.json). T0-3.",
    )
    parser.add_argument(
        "--remove-operational",
        action="store_true",
        help="Remove OPERATIONAL_PATHS (.harness/audit.log + .harness/session.lock + .harness/backups/). T0-3.",
    )
    parser.add_argument(
        "--remove-install-state-only",
        action="store_true",
        help="Remove INSTALL_PATHS (.harness/installed-manifest.json) only. T0-3.",
    )
    parser.add_argument(
        "--remove-all",
        action="store_true",
        help="Remove STATE + OPERATIONAL + INSTALL paths (union of T0-3 flags).",
    )
    args = parser.parse_args(argv)
    # Honour the T0-3 flag split first; bypass the --select gate when any
    # path-tuple flag is set.
    if args.remove_all or args.remove_state or args.remove_operational or args.remove_install_state_only:
        if args.target is None:
            parser.error("--target is required for path-tuple removal flags")
        return _remove_path_tuples(
            target=args.target,
            remove_state=args.remove_state or args.remove_all,
            remove_operational=args.remove_operational or args.remove_all,
            remove_install_state=args.remove_install_state_only or args.remove_all,
        )
    if args.interactive:
        args = prompt_interactive(args)
    if args.target is None:
        parser.error("--target is required unless --interactive supplies it")
    selected = parse_selection(args.select)
    if args.remove_install_state and not selects_all_scopes(selected):
        raise SystemExit("--remove-install-state requires selecting all uninstall scopes: 1,2,3,4,5")
    return uninstall(
        target=args.target,
        selected=selected,
        dry_run=args.dry_run,
        remove_install_state=args.remove_install_state,
    )


def uninstall(
    *,
    target: Path,
    selected: set[str],
    dry_run: bool = False,
    remove_install_state: bool = False,
) -> int:
    target = target.resolve()
    installed_path = target / harness.INSTALL_STATE
    if not installed_path.exists():
        raise SystemExit(f"Target is missing {harness.INSTALL_STATE}")
    installed = json.loads(installed_path.read_text(encoding="utf-8"))
    files = installed.get("files", {})
    if not isinstance(files, dict):
        raise SystemExit("Target install state has malformed files map.")

    plan = build_removal_plan(target=target, installed_files=files, selected=selected)
    for warning in plan.warnings:
        print(warning)
    if remove_install_state:
        print(INSTALL_STATE_WARNING)
    if plan.conflicts and not dry_run:
        print("uninstall conflicts")
        for path_text in plan.conflicts:
            print(f"conflict={path_text}")
        print("no mutation performed")
        return 1

    if dry_run:
        print("uninstall dry-run")
        print(f"target={target}")
        print("selected=" + ",".join(sorted(selected)))
        print(f"planned_file_removals={len(plan.remove_paths)}")
        print(f"planned_block_removals={len(plan.remove_blocks)}")
        print(f"planned_install_state_removal={str(remove_install_state).lower()}")
        print(f"conflicts={len(plan.conflicts)}")
        for path_text in plan.conflicts:
            print(f"conflict={path_text}")
        print("no mutation performed")
        return 1 if plan.conflicts else 0

    for path_text in plan.remove_blocks:
        info = files.get(path_text, {})
        destination = target / harness.normalize_path(path_text)
        result = harness.plan_managed_append_retirement(
            destination=destination,
            path_text=path_text,
            installed_info=info if isinstance(info, dict) else {},
        )
        if result.updated_text is not None:
            harness.write_text_file(destination, result.updated_text)
        files.pop(path_text, None)

    for path_text in plan.remove_paths:
        destination = target / harness.normalize_path(path_text)
        if destination.exists():
            destination.unlink()
            harness.remove_empty_parents(destination.parent, target)
        files.pop(path_text, None)

    update_installed_scopes(installed, selected)
    residual_profiles = installed.get("profiles") or []
    source_root_str = installed.get("source")
    if source_root_str:
        harness.sync_roomodes_profile_modes(
            target=target,
            profiles=residual_profiles,
            source_root=Path(source_root_str),
        )
    if remove_install_state:
        installed_path.unlink()
        harness.remove_empty_parents(installed_path.parent, target)
    else:
        harness.write_json(installed_path, installed)

    print("uninstall complete")
    print(f"removed_files={len(plan.remove_paths)}")
    print(f"removed_blocks={len(plan.remove_blocks)}")
    return 1 if plan.conflicts else 0


def _remove_path_tuples(
    *,
    target: Path,
    remove_state: bool,
    remove_operational: bool,
    remove_install_state: bool,
) -> int:
    """T0-3 flag-split removal: iterate STATE_FILE_PATHS/OPERATIONAL_PATHS/INSTALL_PATHS.

    Each entry is interpreted as a path relative to ``target``. Entries
    ending in ``/`` are removed as directory trees; other entries are
    unlinked. Missing paths are silently tolerated (idempotent).
    """
    import shutil

    target = target.resolve()
    # Safety guard: refuse to silently no-op on a non-harness directory.
    # Without this, `--remove-all` on an unrelated path prints "removed=0"
    # and returns success, masking user error.
    sentinel = target / harness.INSTALL_STATE
    if not sentinel.exists() and not (target / ".scratch/phase-state.json").exists():
        raise SystemExit(
            f"Refusing to run path-tuple uninstall: {target} does not look like "
            f"a harness install (no {harness.INSTALL_STATE} and no .scratch/phase-state.json). "
            f"Re-check --target."
        )
    selected: list[str] = []
    if remove_state:
        selected.extend(STATE_FILE_PATHS)
    if remove_operational:
        selected.extend(OPERATIONAL_PATHS)
    if remove_install_state:
        selected.extend(INSTALL_PATHS)

    removed = 0
    for rel in selected:
        path = target / rel
        if rel.endswith("/"):
            if path.exists():
                shutil.rmtree(path)
                removed += 1
        else:
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
    print("path-tuple uninstall complete")
    print(f"target={target}")
    print(f"removed={removed}")
    return 0


def selects_all_scopes(selected: set[str]) -> bool:
    return set(CHOICES.values()).issubset(selected)


def build_removal_plan(*, target: Path, installed_files: dict[str, object], selected: set[str]) -> RemovalPlan:
    remove_paths: list[str] = []
    remove_blocks: list[str] = []
    conflicts: list[str] = []
    warnings: list[str] = []
    if "docs" in selected:
        warnings.append(DOCS_WARNING)

    for path_text, info in sorted(installed_files.items()):
        if not isinstance(info, dict) or not selection_matches(path_text, info, selected):
            continue
        policy = info.get("policy")
        destination = target / harness.normalize_path(path_text)
        if policy == "managed-append":
            result = harness.plan_managed_append_retirement(
                destination=destination,
                path_text=path_text,
                installed_info=info,
            )
            if result.conflict:
                conflicts.append(path_text)
                continue
            if result.updated_text is not None:
                remove_blocks.append(path_text)
            else:
                installed_files.pop(path_text, None)
            continue
        if policy in {"harness-owned", "managed", "project-owned"}:
            # v0.9.12: previously refused to delete a locally-modified
            # harness-owned file as a "conflict". User explicitly asked
            # for uninstall; that refusal was paternalistic. Now: still
            # queue for delete, but warn so the user knows they're losing
            # local changes. (Local mods rarely matter for harness-owned
            # files; if they did, the user shouldn't have edited them.)
            if modified_harness_owned(destination, info) and scope_for_path(path_text, info) != "docs":
                warnings.append(
                    f"deleting locally-modified harness-owned file: {path_text}"
                )
            if destination.exists():
                remove_paths.append(path_text)
            else:
                installed_files.pop(path_text, None)
    return RemovalPlan(remove_paths=remove_paths, remove_blocks=remove_blocks, conflicts=conflicts, warnings=warnings)


def selection_matches(path_text: str, info: dict[str, object], selected: set[str]) -> bool:
    return scope_for_path(path_text, info) in selected


def scope_for_path(path_text: str, info: dict[str, object]) -> str | None:
    adapter = info.get("adapter")
    if adapter == "roo" or path_text == ".roomodes" or path_text == ".rooignore" or path_text.startswith(".roo/"):
        return "roo"
    if adapter == "opencode" or path_text.startswith(".opencode/"):
        return "opencode"
    if path_text.startswith(".agents/skills/") or path_text.startswith("scripts/"):
        return "runtime"
    if path_text.startswith(".planning/") or path_text.startswith("docs/"):
        return "docs"
    if path_text == "AGENTS.md" or path_text == ".gitignore" or path_text.startswith(".scratch/"):
        return "core"
    return None


def modified_harness_owned(destination: Path, info: dict[str, object]) -> bool:
    old_hash = info.get("sha256")
    return bool(destination.exists() and old_hash and harness.file_hash(destination) != old_hash)


def update_installed_scopes(installed: dict[str, object], selected: set[str]) -> None:
    if "roo" in selected or "opencode" in selected:
        adapters = [value for value in installed.get("adapters", []) if value not in selected]
        installed["adapters"] = adapters
        init_options = installed.get("init_options")
        if isinstance(init_options, dict):
            init_options["adapters"] = adapters
    if "runtime" in selected:
        installed["packs"] = []
        init_options = installed.get("init_options")
        if isinstance(init_options, dict):
            init_options["packs"] = []
        installed["pack_metadata"] = {}
    if "docs" in selected:
        installed["profiles"] = []
        init_options = installed.get("init_options")
        if isinstance(init_options, dict):
            init_options["profiles"] = []


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
