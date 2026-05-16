#!/usr/bin/env python3
"""Install, upgrade, and validate the generalized low-reasoning harness."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from lib.planning_status import ProjectionError, load_projection
from lib.version import (
    repo_root,
    upgrade_source_root,
    normalize_release_version,
    git_output,
    is_git_worktree_dirty,
    exact_release_tag_version,
    development_version,
    git_source_provenance,
    source_provenance,
    resolve_harness_version,
    release_check,
    readme_release_versions,
    check_readme_release_versions,
    README_RELEASE_VERSION,
)
from lib.profiles import (
    KNOWN_PROFILES,
    LEGACY_PROFILE_ALIASES,
    PROFILE_MODE_OWNERS,
    default_packs_for_profile,
    db_packs,
    normalize_profiles,
)
from lib.workflow_static_checks import (
    installed_scope_issues,
    optional_phase_pointer_keys,
    verification_contract_issues,
    verification_placeholder_reason,
)
import lib.manifest as _manifest
from lib.manifest import (
    ManifestEntry,
    KNOWN_ADAPTERS,
    KNOWN_POLICIES,
    KNOWN_PACKS,
    MANIFEST_PATH,
    MANIFEST_SOURCE_VERSION,
    load_manifest,
    load_manifest_data,
    selected_pack_metadata,
    select_entries,
    validate_scope_names,
    infer_adapter,
    infer_pack,
    infer_owner,
    source_path,
    destination_path,
    validate_managed_append_destinations,
)
from lib.state import (
    INSTALL_STATE,
    scope_record,
    delegated_source_provenance,
    installed_scope,
    available_scopes,
    parse_optional_scope,
    parse_scope,
    write_install_state,
    read_install_state,
    validate_installed_scope_names,
    validate_installed_managed_append,
    required_phrase_scope,
    write_json,
    file_hash,
    file_state,
    now_utc,
    manifest_sha256,
    sha256_text,
    normalize_payload,
)
from lib.roadmap_state import (
    RoadmapPhase,
    StateSnapshot,
    normalize_path,
    parse_roadmap_phases,
    parse_state_snapshot,
    parse_frontmatter,
    split_frontmatter_pair,
    int_value,
    markdown_section,
    check_roadmap_state_sync,
    roadmap_state_sync_applicable,
    find_roadmap_state_sync_findings,
)


HARNESS_VERSION = "0.0.0-dev+unknown"
CLEAN_SKELETON = Path("harness/skeleton/clean")
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
VERIFICATION_PREFIXES = (
    "python3 ",
    "git ",
    "jq ",
    "npx ",
    "Validate ",
    "Review ",
    "Inspect ",
    "Confirm ",
    "core-only ",
    "OpenCode-only ",
    "Roo",
)
REQUIRED_TARGET_PHRASES = {
    "AGENTS.md": (
        "Karpathy-Inspired Coding Guidelines",
        "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`",
        "Every roadmap phase starts with its own `discuss` pass",
    ),
}
CONTAMINATION_PATTERNS = (
    re.compile(r"\bPR\s*#\d+\b", re.IGNORECASE),
    re.compile(r"\bDB context snapshot\b", re.IGNORECASE),
    re.compile(r"\bhjung3113/new-project\b", re.IGNORECASE),
    re.compile(r"\bPhase\s+[0-9]+.*(?:implemented|complete|완료)", re.IGNORECASE),
    re.compile(r"\bunder PR review\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class DoctorFinding:
    severity: str
    code: str
    path: str
    cause: str
    impact: str
    fix: str
    evidence: str
    connects_to_db: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "cause": self.cause,
            "impact": self.impact,
            "fix": self.fix,
            "evidence": self.evidence,
            "connects_to_db": self.connects_to_db,
        }


@dataclass(frozen=True)
class AdoptionConflict:
    path_text: str
    content: str


@dataclass(frozen=True)
class AdoptionPlan:
    installed: dict[str, object]
    conflicts: list[AdoptionConflict]
    backups: list[AdoptionConflict]


def run(argv: list[str] | None = None) -> int:
    global HARNESS_VERSION

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        dest="release_version",
        default=None,
        help="Release tooling override. Accepts vMAJOR.MINOR.PATCH and stamps init/upgrade state with MAJOR.MINOR.PATCH.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Install the clean harness skeleton into a target project.")
    init_parser.add_argument("--target", required=True, type=Path)
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.add_argument(
        "--adapters",
        default="roo",
        help="Comma-separated adapters to install: none, roo, opencode, or both. Defaults to roo for compatibility.",
    )
    init_parser.add_argument(
        "--profiles",
        default="generic",
        help="Comma-separated active profiles. Defaults to generic; stack profiles must be confirmed before use.",
    )
    init_parser.add_argument(
        "--packs",
        default=None,
        help="Comma-separated optional skill/capability packs to install. Defaults to profile-appropriate packs.",
    )
    init_parser.add_argument(
        "--db",
        choices=("mssql", "postgresql", "none"),
        default=None,
        help="Optional database axis. Ignored when profile is 'generic'.",
    )

    upgrade_parser = subparsers.add_parser("upgrade", help="Update harness-owned files in a target project.")
    upgrade_parser.add_argument("--target", required=True, type=Path)
    upgrade_parser.add_argument("--dry-run", action="store_true")
    upgrade_parser.add_argument("--force", action="store_true", help="Overwrite locally modified harness-owned files.")
    upgrade_parser.add_argument(
        "--adopt-existing",
        action="store_true",
        help="Create install state for an existing manual harness target before upgrading.",
    )
    upgrade_parser.add_argument("--adapters", default=None, help="Adapter scope for upgrade. Defaults to installed adapters.")
    upgrade_parser.add_argument("--profiles", default=None, help="Profile scope for upgrade. Defaults to installed profiles.")
    upgrade_parser.add_argument("--packs", default=None, help="Pack scope for upgrade. Defaults to installed packs.")

    check_parser = subparsers.add_parser("check", help="Validate harness structure and policy.")
    check_parser.add_argument("--target", type=Path, default=None)
    check_parser.add_argument("--adapter", default=None, help="Validate a specific adapter in addition to installed adapters.")
    check_parser.add_argument("--base", default=None, help="Optional git base ref for changed-path checks.")
    check_parser.add_argument("--worktree", action="store_true", help="Check staged and unstaged paths against allowed_paths.")

    doctor_parser = subparsers.add_parser("doctor", help="Diagnose planning, Roo, and harness environment drift.")
    doctor_parser.add_argument("--target", type=Path, default=None)
    doctor_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")

    uninstall_parser = subparsers.add_parser("uninstall", help="Remove selected installed harness scopes from a target.")
    uninstall_parser.add_argument("--target", type=Path, default=None)
    uninstall_parser.add_argument("--select", default="")
    uninstall_parser.add_argument("--dry-run", action="store_true")
    uninstall_parser.add_argument("--interactive", action="store_true")
    uninstall_parser.add_argument("--remove-install-state", action="store_true")

    release_parser = subparsers.add_parser("release-check", help="Verify release version, tag, and worktree gates.")
    release_parser.add_argument("--expected-version", default=None, help="Optional expected vMAJOR.MINOR.PATCH release tag.")
    release_parser.add_argument(
        "--require-origin-main",
        action="store_true",
        help="Fail unless the tagged commit equals origin/main.",
    )

    args = parser.parse_args(argv)
    root = repo_root()
    command_root = root
    if args.command == "upgrade":
        command_root = upgrade_source_root(root, args.target)
    HARNESS_VERSION = resolve_harness_version(command_root, explicit=args.release_version)

    if args.command == "init":
        raw_profiles = parse_scope(args.profiles, default={"generic"})
        profiles_resolved = normalize_profiles(list(raw_profiles))
        if args.packs is not None:
            # User explicitly provided --packs: honour it as-is.
            final_packs: set[str] = parse_scope(args.packs, default={"workflow-core"})
        else:
            # Auto-derive packs from profile defaults + optional db axis.
            auto_packs: set[str] = set()
            for profile in profiles_resolved:
                auto_packs.update(default_packs_for_profile(profile))
            db = args.db
            if db is not None:
                if profiles_resolved == ["generic"]:
                    print("NOTE: --db is ignored for the 'generic' profile.", file=sys.stderr)
                else:
                    auto_packs.update(db_packs(db))
            final_packs = auto_packs
        install(
            root=root,
            target=args.target,
            dry_run=args.dry_run,
            adapters=parse_scope(args.adapters, default={"roo"}),
            profiles=set(profiles_resolved),
            packs=final_packs,
        )
        return 0
    if args.command == "upgrade":
        raw_upgrade_profiles = parse_optional_scope(args.profiles)
        return upgrade(
            root=command_root,
            target=args.target,
            dry_run=args.dry_run,
            force=args.force,
            adopt_existing=args.adopt_existing,
            adapters=parse_optional_scope(args.adapters),
            profiles=set(normalize_profiles(list(raw_upgrade_profiles))) if raw_upgrade_profiles is not None else None,
            packs=parse_optional_scope(args.packs),
        )
    if args.command == "check":
        command = [sys.executable, str(root / "scripts/check_harness.py")]
        if args.target:
            command.extend(["--target", str(args.target)])
        if args.adapter:
            command.extend(["--adapter", args.adapter])
        if args.base:
            command.extend(["--base", args.base])
        if args.worktree:
            command.append("--worktree")
        return run_delegated_command(command, root)
    if args.command == "doctor":
        command = [sys.executable, str(root / "scripts/doctor_harness.py"), "--format", args.format]
        if args.target:
            command.extend(["--target", str(args.target)])
        return run_delegated_command(command, root)
    if args.command == "uninstall":
        command = [
            sys.executable,
            str(root / "scripts/uninstall_harness.py"),
        ]
        if args.target:
            command.extend(["--target", str(args.target)])
        if args.select:
            command.extend(["--select", args.select])
        if args.dry_run:
            command.append("--dry-run")
        if args.interactive:
            command.append("--interactive")
        if args.remove_install_state:
            command.append("--remove-install-state")
        return run_delegated_command(command, root)
    if args.command == "release-check":
        release_version = release_check(
            root=root,
            expected_version=args.expected_version,
            require_origin_main=args.require_origin_main,
        )
        print(f"release-check PASS v{release_version}")
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


def run_delegated_command(command: list[str], cwd: Path) -> int:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        message = (result.stderr or result.stdout).strip()
        raise SystemExit(message or result.returncode)
    return 0


def sync_roomodes_profile_modes(target: Path, profiles: Iterable[str], source_root: Path) -> None:
    """Replace the profile-modes section of target/.roomodes with the modes
    contributed by the currently installed profiles.

    If target/.roomodes does not exist (e.g. opencode-only install) this is a
    no-op. Profile-owned modes are read from
    ``<source_root>/harness/profiles/<profile>/modes/*.json``.
    """
    from lib import roomodes_writer

    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return
    profile_modes: list[dict] = []
    for profile in profiles:
        modes_dir = source_root / "harness/profiles" / profile / "modes"
        if not modes_dir.exists():
            continue
        for mode_file in sorted(modes_dir.glob("*.json")):
            profile_modes.append(json.loads(mode_file.read_text(encoding="utf-8")))
    roomodes_writer.set_profile_modes(roomodes_path, profile_modes)


def install(
    *,
    root: Path,
    target: Path,
    dry_run: bool = False,
    adapters: set[str] | None = None,
    profiles: set[str] | None = None,
    packs: set[str] | None = None,
) -> None:
    adapters = adapters if adapters is not None else {"roo"}
    profiles = profiles if profiles is not None else {"generic"}
    packs = packs if packs is not None else set()
    all_entries = load_manifest(root)
    validate_scope_names(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    entries = select_entries(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    target = target.resolve()
    destinations = [
        (entry, source_path(root, entry), destination_path(target, entry))
        for entry in entries
        if entry.policy != "exclude"
    ]
    existing = [
        str(entry.path)
        for entry, _, destination in destinations
        if entry.policy not in {"managed-append", "project-owned"} and (destination.exists() or destination.is_symlink())
    ]
    if existing:
        raise SystemExit("Refusing to overwrite existing files during init: " + ", ".join(existing))

    if dry_run:
        print("init dry-run")
        print(f"target={target}")
        print(f"source={root.resolve()}")
        print(f"version={HARNESS_VERSION}")
        print("adapters=" + ",".join(sorted(adapters)))
        print("profiles=" + ",".join(sorted(profiles)))
        print("packs=" + ",".join(sorted(packs)))
        print(f"planned_writes={len(destinations)}")
        print("no mutation performed")
        return

    target.mkdir(parents=True, exist_ok=True)
    for entry, source, destination in destinations:
        if not dry_run:
            if entry.policy == "managed-append":
                write_managed_append(source=source, destination=destination, entry=entry)
            elif entry.policy == "project-owned" and destination.exists():
                continue
            else:
                write_copy(source, destination)

    sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
    write_install_state(root=root, target=target, entries=entries, adapters=adapters, profiles=profiles, packs=packs)


def migrate_install_state(state: dict) -> dict:
    """Rewrite a v0.6.0-style install record to the post-unification shape.

    Returns the (possibly mutated) state. Also returns it through the in-place
    dict for callers that prefer the side-effect.
    """
    options = state.setdefault("init_options", {})
    profiles = list(options.get("profiles") or [])
    new_profiles: list[str] = []
    added_packs: set[str] = set()
    for p in profiles:
        if p == "dotnet-etl-mssql":
            new_profiles.append("dotnet-etl")
            added_packs.update(("tech-mssql", "workflow-db-context"))
        elif p in LEGACY_PROFILE_ALIASES:
            new_profiles.append(LEGACY_PROFILE_ALIASES[p])
        else:
            new_profiles.append(p)
    if new_profiles != profiles:
        options["profiles"] = new_profiles
        state["profiles"] = new_profiles
    if added_packs:
        packs = set(state.get("packs") or [])
        packs.update(added_packs)
        state["packs"] = sorted(packs)
        opt_packs = set(options.get("packs") or [])
        opt_packs.update(added_packs)
        options["packs"] = sorted(opt_packs)
    return state


def install_state_migration_report(before: dict, after: dict) -> list[str]:
    """Return human-readable lines describing what migrate_install_state changed."""
    lines: list[str] = []
    before_profiles = list((before.get("init_options") or {}).get("profiles") or [])
    after_profiles = list((after.get("init_options") or {}).get("profiles") or [])
    if before_profiles != after_profiles:
        lines.append(f"profiles: {before_profiles} -> {after_profiles}")
    before_packs = set(before.get("packs") or [])
    after_packs = set(after.get("packs") or [])
    added = sorted(after_packs - before_packs)
    if added:
        lines.append(f"packs added: {', '.join(added)}")
    return lines


def upgrade(
    *,
    root: Path,
    target: Path,
    dry_run: bool = False,
    force: bool = False,
    adopt_existing: bool = False,
    adapters: set[str] | None = None,
    profiles: set[str] | None = None,
    packs: set[str] | None = None,
) -> int:
    import copy

    if not (root / MANIFEST_PATH).exists():
        raise SystemExit("Upgrade must be run from a harness source tree with harness/manifest.json.")
    target = target.resolve()
    installed = read_install_state(target)
    before_migration = copy.deepcopy(installed)
    migrate_install_state(installed)
    report = install_state_migration_report(before_migration, installed)
    if report:
        print("MIGRATION:")
        for line in report:
            print(f"  {line}")
    adapters = adapters if adapters is not None else installed_scope(installed, "adapters", default={"roo"})
    profiles = profiles if profiles is not None else installed_scope(installed, "profiles", default={"generic"})
    packs = packs if packs is not None else installed_scope(installed, "packs", default=set())
    all_entries = load_manifest(root)
    validate_scope_names(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    entries = select_entries(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    installed_paths = installed.get("files", {})
    adopting_missing_state = False
    if installed.get("version") is None:
        if not adopt_existing:
            raise SystemExit("Target is not initialized. Run init before upgrade.")
        adopting_missing_state = True
        adoption_plan = build_adopted_install_state(
            root=root,
            target=target,
            entries=entries,
            adapters=adapters,
            profiles=profiles,
            packs=packs,
            force=force,
        )
        installed = adoption_plan.installed
        if adoption_plan.conflicts:
            if not dry_run:
                for conflict in adoption_plan.conflicts:
                    write_text_conflict(target, conflict.path_text, conflict.content)
            return 1
        if not dry_run:
            for backup in adoption_plan.backups:
                write_text_conflict(target, backup.path_text, backup.content)
        installed_paths = installed.get("files", {})
    conflicts = 0
    conflict_paths: list[str] = []
    planned_writes = 0
    planned_removals = 0
    current_paths = {str(entry.path) for entry in entries if entry.policy != "exclude"}

    for entry in entries:
        if entry.policy not in {"harness-owned", "managed", "managed-append"}:
            continue

        source = source_path(root, entry)
        destination = destination_path(target, entry)
        new_hash = file_hash(source)

        if entry.policy == "managed-append":
            result = plan_managed_append(
                source=source,
                destination=destination,
                entry=entry,
                installed_info=installed_paths.get(str(entry.path), {}),
            )
            if result.conflict:
                conflicts += 1
                conflict_paths.append(f"{entry.path}.new")
                if not dry_run:
                    write_text_conflict(target, f"{entry.path}.new", result.proposed_block)
                continue
            if not dry_run and result.updated_text is not None:
                write_text_file(destination, result.updated_text)
            if result.updated_text is not None:
                planned_writes += 1
            if not dry_run:
                installed.setdefault("files", {})[str(entry.path)] = file_state(
                    root=root,
                    target=target,
                    entry=entry,
                    source=source,
                    applied_sha256=result.applied_sha256,
                )
            continue

        if destination.exists() and not force:
            old_hash = installed_paths.get(str(entry.path), {}).get("sha256")
            current_hash = file_hash(destination)
            if not old_hash or current_hash != old_hash:
                conflicts += 1
                conflict_paths.append(f"{entry.path}.new")
                conflict_path = target / ".harness/conflicts" / f"{entry.path}.new"
                if not dry_run:
                    write_copy(source, conflict_path)
                continue

        planned_writes += 1
        if not dry_run:
            write_copy(source, destination)
            installed.setdefault("files", {})[str(entry.path)] = file_state(
                root=root,
                target=target,
                entry=entry,
                source=source,
            )

    for path_text, info in list(installed_paths.items()):
        if path_text in current_paths:
            continue
        if not isinstance(info, dict) or info.get("policy") not in {"harness-owned", "managed", "managed-append"}:
            continue
        destination = target / normalize_path(path_text)
        if info.get("policy") == "managed-append":
            result = plan_managed_append_retirement(destination=destination, path_text=path_text, installed_info=info)
            if result.conflict:
                conflicts += 1
                conflict_paths.append(f"{path_text}.retired")
                if not dry_run:
                    write_text_conflict(target, f"{path_text}.retired", result.proposed_block)
                continue
            if not dry_run:
                if result.updated_text is not None:
                    write_text_file(destination, result.updated_text)
                installed.setdefault("files", {}).pop(path_text, None)
            if result.updated_text is not None:
                planned_removals += 1
            continue
        old_hash = info.get("sha256")
        if destination.exists() and old_hash and file_hash(destination) != old_hash:
            conflicts += 1
            conflict_paths.append(f"{path_text}.retired")
            conflict_path = target / ".harness/conflicts" / f"{path_text}.retired"
            if not dry_run:
                write_copy(destination, conflict_path)
            continue
        if not dry_run:
            if destination.exists():
                destination.unlink()
                remove_empty_parents(destination.parent, target)
                installed.setdefault("files", {}).pop(path_text, None)
        if destination.exists():
            planned_removals += 1

    if not dry_run:
        normalize_selected_project_owned_state(root=root, target=target, entries=entries, installed=installed)

    installed["version"] = HARNESS_VERSION
    installed["adapters"] = sorted(adapters)
    installed["profiles"] = sorted(profiles)
    installed["packs"] = sorted(packs)
    installed["init_options"] = scope_record(adapters=adapters, profiles=profiles, packs=packs)
    installed["pack_metadata"] = selected_pack_metadata(root, packs)
    installed["available_scopes"] = available_scopes(root)
    installed["state_schema_version"] = 2
    installed["manifest_sha256"] = manifest_sha256(root)
    installed["source"] = str(root.resolve())
    provenance = source_provenance(root)
    if provenance:
        installed["source_provenance"] = provenance
    if not dry_run:
        sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
        roomodes_path = target / ".roomodes"
        if roomodes_path.exists() and isinstance(installed.get("files"), dict) and ".roomodes" in installed["files"]:
            installed["files"][".roomodes"]["sha256"] = file_hash(roomodes_path)
    if not dry_run and not (adopting_missing_state and conflicts):
        write_json(target / INSTALL_STATE, installed)
    if dry_run:
        print("upgrade dry-run")
        print(f"target={target}")
        print(f"source={root.resolve()}")
        print(f"version={HARNESS_VERSION}")
        print("adapters=" + ",".join(sorted(adapters)))
        print("profiles=" + ",".join(sorted(profiles)))
        print("packs=" + ",".join(sorted(packs)))
        print(f"planned_writes={planned_writes}")
        print(f"planned_removals={planned_removals}")
        print(f"conflicts={conflicts}")
        for path in conflict_paths:
            print(f"conflict={path}")
        print("no mutation performed")
    return 1 if conflicts else 0


def check(
    *,
    root: Path,
    target: Path | None = None,
    base: str | None = None,
    worktree: bool = False,
    adapter: str | None = None,
) -> None:
    root = root.resolve()
    if not (root / MANIFEST_PATH).exists() or should_check_as_installed_target(root):
        check_installed_target(root)
        if base:
            check_changed_paths(root, base)
        if worktree:
            check_worktree_paths(root)
        return

    manifest = load_manifest_data(root)
    if manifest.get("version") != HARNESS_VERSION:
        raise SystemExit(f"Manifest version mismatch: expected {HARNESS_VERSION}")

    all_entries = load_manifest(root)
    entries = all_entries
    missing = [str(entry.source) for entry in entries if entry.policy != "exclude" and not source_path(root, entry).exists()]
    if missing:
        raise SystemExit(f"Manifest sources missing: {', '.join(missing)}")

    check_clean_skeleton(root)
    if (root / ".roomodes").exists():
        check_json(root / ".roomodes")
    check_json(root / ".scratch/phase-state.schema.json")
    check_json(root / ".scratch/phase-state.example.json")
    check_json(root / ".scratch/phase-state.json")
    check_phase_state_semantics(root / ".scratch/phase-state.json")
    check_phase_state_semantics(root / ".scratch/phase-state.example.json")
    if (root / ".roo").exists() and (root / ".roomodes").exists():
        check_command_modes(root)
    check_phase_state_paths(root)
    check_roadmap_state_sync(root)
    check_phase_reference_drift(root)

    check_target = (target or root).resolve()
    if target:
        installed = read_install_state(check_target)
        adapters = set(installed.get("adapters", ["roo"]))
        profiles = set(installed.get("profiles", ["generic"]))
        packs = set(installed.get("packs", []))
        if adapter:
            adapters.add(adapter)
        validate_scope_names(all_entries, adapters=adapters, profiles=profiles, packs=packs)
        expected = select_entries(all_entries, adapters=adapters, profiles=profiles, packs=packs)
        check_installed_target(check_target, expected_entries=expected)
    if base:
        check_changed_paths(check_target, base)
    if worktree:
        check_worktree_paths(check_target)


def should_check_as_installed_target(root: Path) -> bool:
    if not (root / INSTALL_STATE).exists() or not (root / MANIFEST_PATH).exists():
        return False
    try:
        manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    version = manifest.get("version") if isinstance(manifest, dict) else None
    return version not in {MANIFEST_SOURCE_VERSION, HARNESS_VERSION}


def write_copy(source: Path, destination: Path) -> None:
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def write_text_file(destination: Path, text: str) -> None:
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


from lib.append_block import (
    AppendBlockPlan,
    ParsedAppendBlock,
    marker_start,
    marker_end,
    marker_end_for_path,
    render_append_block,
    parse_append_block,
    append_block_to_text,
    replace_block,
    write_managed_append,
    plan_managed_append,
    plan_managed_append_retirement,
)


def write_text_conflict(target: Path, path_text: str, content: str) -> None:
    destination = target / ".harness/conflicts" / normalize_path(path_text)
    write_text_file(destination, content)



def normalize_selected_project_owned_state(
    *,
    root: Path,
    target: Path,
    entries: Iterable[ManifestEntry],
    installed: dict[str, object],
) -> None:
    files = installed.setdefault("files", {})
    if not isinstance(files, dict):
        return
    for entry in entries:
        if entry.policy != "project-owned":
            continue
        path_text = str(entry.path)
        destination = destination_path(target, entry)
        if not destination.exists():
            continue
        files[path_text] = file_state(
            root=root,
            target=target,
            entry=entry,
            source=source_path(root, entry),
        )


def build_adopted_install_state(
    *,
    root: Path,
    target: Path,
    entries: Iterable[ManifestEntry],
    adapters: set[str],
    profiles: set[str],
    packs: set[str],
    force: bool,
) -> AdoptionPlan:
    files: dict[str, object] = {}
    conflicts: list[AdoptionConflict] = []
    backups: list[AdoptionConflict] = []
    selected_entries = [entry for entry in entries if entry.policy != "exclude"]
    required_project_owned = [
        entry
        for entry in selected_entries
        if entry.policy == "project-owned" and is_required_adoption_project_owned_path(entry.path.as_posix())
    ]
    missing_project_owned = [
        str(entry.path) for entry in required_project_owned if not destination_path(target, entry).exists()
    ]
    if missing_project_owned:
        raise SystemExit(
            "Cannot adopt target missing required project-owned files: " + ", ".join(sorted(missing_project_owned))
        )
    has_existing_harness_artifact = any(
        is_existing_harness_artifact(root=root, target=target, entry=entry) for entry in selected_entries
    )
    if not has_existing_harness_artifact:
        raise SystemExit("Cannot adopt target without existing selected harness files. Run init instead.")

    for entry in selected_entries:
        destination = destination_path(target, entry)
        assert_safe_write_destination(destination)

    for entry in selected_entries:
        path_text = str(entry.path)
        source = source_path(root, entry)
        destination = destination_path(target, entry)

        if entry.policy == "project-owned":
            if destination.exists():
                files[path_text] = file_state(root=root, target=target, entry=entry, source=source)
            continue

        if entry.policy == "managed-append":
            block = render_append_block(source, entry)
            if not destination.exists():
                continue
            text = destination.read_text(encoding="utf-8")
            try:
                parsed = parse_append_block(text, entry.path.as_posix())
            except ValueError:
                conflicts.append(AdoptionConflict(f"{entry.path}.new", block))
                continue
            if parsed is None:
                continue
            block_hash = sha256_text(block)
            current_hash = sha256_text(parsed.text)
            source_payload = source.read_text(encoding="utf-8")
            if current_hash != block_hash and normalize_payload(parsed.payload) != normalize_payload(source_payload):
                conflicts.append(AdoptionConflict(f"{entry.path}.new", block))
                continue
            files[path_text] = file_state(
                root=root,
                target=target,
                entry=entry,
                source=source,
                applied_sha256=current_hash,
            )
            continue

        if entry.policy in {"harness-owned", "managed"}:
            if not destination.exists():
                continue
            if file_hash(destination) == file_hash(source):
                files[path_text] = file_state(root=root, target=target, entry=entry, source=source)
                continue
            if force:
                backups.append(AdoptionConflict(f"{entry.path}.adopted", destination.read_text(encoding="utf-8")))
                continue
            conflicts.append(AdoptionConflict(f"{entry.path}.new", source.read_text(encoding="utf-8")))

    return AdoptionPlan(
        installed={
            "state_schema_version": 2,
            "version": HARNESS_VERSION,
            "manifest_sha256": manifest_sha256(root),
            "source": str(root),
            "adapters": sorted(adapters),
            "profiles": sorted(profiles),
            "packs": sorted(packs),
            "init_options": scope_record(adapters=adapters, profiles=profiles, packs=packs),
            "pack_metadata": selected_pack_metadata(root, packs),
            "available_scopes": available_scopes(root),
            "files": files,
        },
        conflicts=conflicts,
        backups=backups,
    )


def is_required_adoption_project_owned_path(path_text: str) -> bool:
    return path_text in {
        ".planning/STATE.md",
        ".planning/ROADMAP.md",
        ".scratch/phase-state.json",
    } or path_text.startswith(".planning/codebase/")


def is_optional_project_owned_path(path_text: str) -> bool:
    return path_text == "README.md"


def is_existing_harness_artifact(*, root: Path, target: Path, entry: ManifestEntry) -> bool:
    if entry.policy not in {"harness-owned", "managed", "managed-append"}:
        return False
    destination = destination_path(target, entry)
    if not destination.exists():
        return False
    if entry.policy != "managed-append":
        return True
    try:
        return parse_append_block(destination.read_text(encoding="utf-8"), entry.path.as_posix()) is not None
    except ValueError:
        return True


def remove_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.resolve()
    current = path.resolve()
    while current != stop and is_relative_to(current, stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def assert_safe_write_destination(destination: Path) -> None:
    for candidate in (destination, *destination.parents):
        if candidate.is_symlink():
            raise SystemExit(f"Refusing to write through symlink: {candidate}")
        if candidate == candidate.parent:
            break


def check_installed_target(target: Path, expected_entries: list[ManifestEntry] | None = None) -> None:
    installed_path = target / INSTALL_STATE
    if not installed_path.exists():
        raise SystemExit(f"Target is missing {INSTALL_STATE}")
    installed = json.loads(installed_path.read_text(encoding="utf-8"))
    if installed.get("version") is None:
        raise SystemExit("Target install state is missing version.")
    validate_installed_scope_names(installed)
    profile_sync_errs = _check_roomodes_profile_sync(target, installed)
    if profile_sync_errs:
        raise SystemExit("Profile-mode sync errors: " + "; ".join(profile_sync_errs))
    missing = []
    for path_text in installed.get("files", {}):
        destination = target / normalize_path(path_text)
        if not destination.exists():
            info = installed.get("files", {}).get(path_text)
            if (
                isinstance(info, dict)
                and info.get("policy") == "project-owned"
                and is_optional_project_owned_path(path_text)
            ):
                continue
            missing.append(path_text)
            continue
        info = installed.get("files", {}).get(path_text)
        if isinstance(info, dict) and info.get("policy") == "managed-append":
            validate_installed_managed_append(destination=destination, path_text=path_text, info=info)
    if missing:
        raise SystemExit("Installed target is missing files: " + ", ".join(missing))
    if expected_entries is not None:
        expected_by_path = {str(entry.path): entry for entry in expected_entries if entry.policy != "exclude"}
        policy_mismatches = []
        for path_text, entry in expected_by_path.items():
            info = installed.get("files", {}).get(path_text)
            if not isinstance(info, dict):
                continue
            if info.get("policy") != entry.policy:
                policy_mismatches.append(f"{path_text}: installed {info.get('policy')} != current {entry.policy}")
                continue
            if entry.policy == "managed-append":
                destination = target / normalize_path(path_text)
                if destination.exists():
                    validate_installed_managed_append(destination=destination, path_text=path_text, info=info)
        if policy_mismatches:
            raise SystemExit("Installed policy mismatch: " + "; ".join(policy_mismatches))
        expected_paths = {
            str(entry.path) for entry in expected_entries if entry.policy not in {"exclude", "project-owned"}
        }
        missing_current = [
            path_text for path_text in sorted(expected_paths) if not (target / normalize_path(path_text)).exists()
        ]
        if missing_current:
            raise SystemExit("Current harness files missing from target: " + ", ".join(missing_current))
        retired = [
            path_text
            for path_text, info in sorted(installed.get("files", {}).items())
            if path_text not in expected_paths
            and isinstance(info, dict)
            and info.get("policy") != "project-owned"
        ]
        if retired:
            raise SystemExit("Retired harness files remain installed: " + ", ".join(retired))
    missing_phrases = []
    for relative, phrases in REQUIRED_TARGET_PHRASES.items():
        path = target / relative
        if not path.exists():
            missing_phrases.append(f"{relative}: missing file")
            continue
        text = required_phrase_scope(path=path, relative=relative)
        for phrase in phrases:
            if phrase not in text:
                missing_phrases.append(f"{relative}: {phrase}")
    if missing_phrases:
        raise SystemExit("Required guardrail phrases missing: " + "; ".join(missing_phrases))
    for relative in (
        ".roomodes",
        ".scratch/phase-state.schema.json",
        ".scratch/phase-state.example.json",
        ".scratch/phase-state.json",
    ):
        path = target / relative
        if path.exists():
            check_json(path)
    for relative in (".scratch/phase-state.json", ".scratch/phase-state.example.json"):
        path = target / relative
        if path.exists():
            check_phase_state_semantics(path)
    if roadmap_state_sync_applicable(target):
        check_roadmap_state_sync(target)


def _check_roomodes_profile_sync(target: Path, installed: dict) -> list[str]:
    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return []
    try:
        from lib import roomodes_writer
        profile_modes = roomodes_writer.read(roomodes_path).profile_modes
    except ImportError:
        # roomodes_writer is not installed to targets; parse directly using the
        # same slug-based classification as the writer.
        _BASE_SLUGS = {
            "orchestrator", "architect", "tdd-code", "diagnose", "review",
            "docs-issues", "ops-observability", "harness-maintainer",
        }
        _KNOWN_PROFILE_SLUGS = frozenset(PROFILE_MODE_OWNERS.keys())
        data = json.loads(roomodes_path.read_text(encoding="utf-8"))
        profile_modes = [
            m for m in data.get("customModes", [])
            if m.get("slug") not in _BASE_SLUGS and m.get("slug") in _KNOWN_PROFILE_SLUGS
        ]
    installed_profiles = set((installed.get("init_options") or {}).get("profiles") or [])
    errs: list[str] = []
    for mode in profile_modes:
        slug = mode.get("slug")
        owner = PROFILE_MODE_OWNERS.get(slug)
        if owner and owner not in installed_profiles:
            errs.append(
                f".roomodes contains profile-contributed mode {slug!r} but "
                f"owning profile {owner!r} is not installed"
            )
    return errs


def check_clean_skeleton(root: Path) -> None:
    skeleton = root / CLEAN_SKELETON
    if not skeleton.exists():
        raise SystemExit(f"Missing clean skeleton: {CLEAN_SKELETON}")
    offenders: list[str] = []
    for path in skeleton.rglob("*"):
        if path.is_file() and is_text_file(path):
            text = path.read_text(encoding="utf-8")
            if any(pattern.search(text) for pattern in CONTAMINATION_PATTERNS):
                offenders.append(str(path.relative_to(root)))
    if offenders:
        raise SystemExit("Clean skeleton contamination detected: " + ", ".join(offenders))


def check_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))

def check_phase_state_semantics(path: Path) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    for key in ("updated_at",):
        if not UTC_TIMESTAMP.fullmatch(str(state.get(key, ""))):
            raise SystemExit(f"{path} {key} must be an ISO-8601 UTC timestamp.")
    if not isinstance(state.get("updated_by"), str) or not state.get("updated_by"):
        raise SystemExit(f"{path} updated_by is required.")
    automation_mode = state.get("automation_mode")
    if automation_mode not in {"manual", "auto", "chain"}:
        raise SystemExit(f"{path} automation_mode must be manual, auto, or chain.")
    auto_selected = state.get("auto_selected")
    if not isinstance(auto_selected, list):
        raise SystemExit(f"{path} auto_selected must be an array.")
    if automation_mode in {"auto", "chain"} and not auto_selected:
        raise SystemExit(f"{path} auto_selected must record choices when automation_mode={automation_mode}.")
    required = {
        "choice": str,
        "selected_value": str,
        "reason": str,
        "evidence_path": str,
        "risk_level": str,
        "reversible": bool,
        "inside_allowed_paths": bool,
        "stop_conditions_checked": list,
    }
    for index, item in enumerate(auto_selected):
        if not isinstance(item, dict):
            raise SystemExit(f"{path} auto_selected[{index}] must be an object.")
        for key, expected_type in required.items():
            if key not in item or not isinstance(item[key], expected_type):
                raise SystemExit(f"{path} auto_selected[{index}].{key} is required.")
        if item["risk_level"] not in {"low", "medium", "high"}:
            raise SystemExit(f"{path} auto_selected[{index}].risk_level must be low, medium, or high.")
        if not item["stop_conditions_checked"]:
            raise SystemExit(f"{path} auto_selected[{index}].stop_conditions_checked must be non-empty.")
    phase = state.get("phase")
    if phase not in {"discuss", "plan", "execute", "done"}:
        raise SystemExit(f"{path} phase must be discuss, plan, execute, or done.")
    if phase == "discuss" and state.get("approved") is not False:
        raise SystemExit(f"{path} discuss phase requires approved=false.")
    if phase == "plan":
        required_plan = (
            "plan_id",
            "summary",
            "plan_path",
            "state_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
            "acceptance_criteria",
            "verification",
        )
        missing = [key for key in required_plan if not state.get(key)]
        if state.get("approved") is not False:
            missing.append("approved=false")
        if missing:
            raise SystemExit(f"{path} plan phase requires {', '.join(missing)}.")
    if phase == "execute":
        required_execute = (
            "plan_id",
            "allowed_paths",
            "verification",
            "state_path",
            "plan_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
            "approved_by",
            "approved_at",
        )
        missing = [key for key in required_execute if not state.get(key)]
        if state.get("approved") is not True:
            missing.append("approved=true")
        if missing:
            raise SystemExit(f"{path} execute approval requires {', '.join(missing)}.")
        if not UTC_TIMESTAMP.fullmatch(str(state.get("approved_at", ""))):
            raise SystemExit(f"{path} approved_at must be an ISO-8601 UTC timestamp.")
    if phase == "done":
        required_done = (
            "plan_id",
            "verification",
            "state_path",
            "plan_path",
            "checkpoint_path",
            "current_checkpoint",
            "next_action",
        )
        missing = [key for key in required_done if not state.get(key)]
        if state.get("approved") is not False:
            missing.append("approved=false")
        if missing:
            raise SystemExit(f"{path} done phase requires {', '.join(missing)}.")
    verification = state.get("verification", [])
    if verification:
        if not isinstance(verification, list):
            raise SystemExit(f"{path} verification must be an array.")
        for index, command in enumerate(verification):
            if not isinstance(command, str) or not command.strip():
                raise SystemExit(f"{path} verification[{index}] must be a non-empty string.")
            placeholder_reason = verification_placeholder_reason(command)
            if placeholder_reason:
                raise SystemExit(f"{path} verification[{index}] is a {placeholder_reason}.")
            if not command.startswith(VERIFICATION_PREFIXES):
                raise SystemExit(f"{path} verification[{index}] must start with an allowed command or review verb.")


def check_command_modes(root: Path) -> None:
    modes = json.loads((root / ".roomodes").read_text(encoding="utf-8"))
    known = {mode["slug"] for mode in modes.get("customModes", [])}
    unknown: list[str] = []
    for command in (root / ".roo/commands").glob("*.md"):
        text = command.read_text(encoding="utf-8")
        match = re.search(r"^mode:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
        if match and match.group(1) not in known:
            unknown.append(f"{command.relative_to(root)} -> {match.group(1)}")
    if unknown:
        raise SystemExit("Commands reference unknown Roo modes: " + ", ".join(unknown))


def check_phase_reference_drift(root: Path) -> None:
    stale = (
        "Phase 2 should add mechanical",
        "Future mechanical enforcement belongs to Phase 2",
        "Phase 3 for consumer onboarding",
        "Phase 4 is reserved for a project-specific example slice",
    )
    offenders = []
    for path in (root / ".planning").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for phrase in stale:
            if phrase in text:
                offenders.append(f"{path.relative_to(root)}: {phrase}")
    if offenders:
        raise SystemExit("Stale phase reference detected: " + "; ".join(offenders))


def check_phase_state_paths(root: Path) -> None:
    state_path = root / ".scratch/phase-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    missing = []
    for key in ("state_path", "plan_path", "checkpoint_path"):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            missing.append(f"{key}={value}")
    if missing:
        raise SystemExit("Phase-state paths are missing: " + ", ".join(missing))


def doctor(*, root: Path, output_format: str) -> None:
    sys.stdout.write(render_doctor_report(collect_doctor_findings(root), output_format=output_format))


def collect_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    findings.extend(phase_status_projection_doctor_findings(root))
    findings.extend(roadmap_state_doctor_findings(root))
    findings.extend(phase_state_path_doctor_findings(root))
    findings.extend(verification_contract_doctor_findings(root))
    findings.extend(installed_scope_doctor_findings(root))
    findings.extend(command_mode_doctor_findings(root))
    findings.extend(db_context_doctor_findings(root))
    findings.extend(opencode_profile_rules_doctor_findings(root))
    findings.append(
        DoctorFinding(
            severity="P3",
            code="diff_before_mutation",
            path="scripts/harness.py",
            cause="Harness mutation commands can change many files when init or upgrade runs against a target.",
            impact="A low-reasoning agent may apply changes before the user has reviewed the affected files.",
            fix="Run dry-run or diagnostic commands first, inspect the diff or conflict report, then mutate only after review.",
            evidence="Use `python3 scripts/harness.py upgrade --target <path> --dry-run` before upgrade and `git diff` before commit.",
        )
    )
    return sorted(findings, key=lambda item: (item.severity, item.code, item.path, item.cause))


def phase_status_projection_doctor_findings(root: Path) -> list[DoctorFinding]:
    try:
        projection = load_projection(root)
    except ProjectionError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="phase_status_projection_failed",
                path=".scratch/phase-state.json",
                cause=str(exc),
                impact="Low-reasoning preflight must fall back to the legacy durable planning read order.",
                fix="Repair the planning state files or use the legacy read order until `show_phase_status.py` succeeds.",
                evidence=str(exc),
            )
        ]

    findings: list[DoctorFinding] = []
    if not getattr(projection, "required_reads", []):
        findings.append(
            DoctorFinding(
                severity="P2",
                code="phase_status_required_reads_empty",
                path=".scratch/phase-state.json",
                cause="Phase-status projection succeeded but returned no required reads.",
                impact="A resumed low-reasoning agent may not know the minimum durable planning files to hydrate.",
                fix="Inspect `scripts/lib/planning_status.py` and the live planning pointers; do not add required_reads to phase-state by hand.",
                evidence="projection.required_reads is empty",
            )
        )
    for warning in projection.warnings:
        findings.append(
            DoctorFinding(
                severity=projection_warning_severity(warning.severity),
                code=f"phase_status_{warning.code}",
                path=warning.paths[0] if warning.paths else ".scratch/phase-state.json",
                cause=warning.message,
                impact="Low-reasoning workflow preflight cannot trust the status projection without the required reads.",
                fix="Inspect the warning paths and reconcile `.planning/**` with `.scratch/phase-state.json`.",
                evidence=", ".join(warning.paths) if warning.paths else warning.code,
            )
        )
    return findings


def projection_warning_severity(severity: str) -> str:
    if severity == "blocking":
        return "P1"
    if severity == "warning":
        return "P2"
    return "P3"


def roadmap_state_doctor_findings(root: Path) -> list[DoctorFinding]:
    return [
        DoctorFinding(
            severity="P1",
            code="roadmap_state_sync",
            path=".planning/ROADMAP.md",
            cause=finding,
            impact="Agents may execute the wrong phase, compute progress incorrectly, or trust stale approval pointers.",
            fix="Update `.planning/ROADMAP.md`, `.planning/STATE.md`, the active checkpoint, and `.scratch/phase-state.json` together.",
            evidence=finding,
        )
        for finding in find_roadmap_state_sync_findings(root)
    ]


def phase_state_path_doctor_findings(root: Path) -> list[DoctorFinding]:
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return [
            DoctorFinding(
                severity="P1",
                code="phase_state_missing",
                path=".scratch/phase-state.json",
                cause="Live phase gate file is missing.",
                impact="Implementation workflows cannot prove phase, plan_id, approved state, allowed paths, or verification.",
                fix="Create `.scratch/phase-state.json` from schema/example and point it at durable `.planning/` files.",
                evidence="missing file",
            )
        ]
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="phase_state_invalid_json",
                path=".scratch/phase-state.json",
                cause=str(exc),
                impact="Harness checks and workflow gates cannot parse the live phase state.",
                fix="Repair JSON syntax and validate with `.scratch/phase-state.schema.json`.",
                evidence=f"line {exc.lineno} column {exc.colno}",
            )
        ]
    findings: list[DoctorFinding] = []
    for key in ("state_path", "plan_path", "checkpoint_path"):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            findings.append(
                DoctorFinding(
                    severity="P1",
                    code="phase_state_pointer_missing",
                    path=".scratch/phase-state.json",
                    cause=f"{key} points to missing path {value!r}.",
                    impact="Fresh sessions may restart from a non-existent plan or checkpoint.",
                    fix="Update the pointer to an existing durable planning file or restore the missing file.",
                    evidence=f"{key}={value}",
                )
            )
    phase = state.get("phase")
    for key in optional_phase_pointer_keys(phase):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="phase_state_optional_pointer_missing",
                    path=".scratch/phase-state.json",
                    cause=f"{key} points to missing path {value!r}.",
                    impact="Workflow reports may omit verification or closure evidence, but the live gate remains controlled by required phase pointers.",
                    fix="Restore the missing artifact or remove the optional pointer until the artifact exists.",
                    evidence=f"{key}={value}",
                )
            )
    return findings


def verification_contract_doctor_findings(root: Path) -> list[DoctorFinding]:
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    findings: list[DoctorFinding] = []
    for issue in verification_contract_issues(state):
        findings.append(
            DoctorFinding(
                severity="P2",
                code="verification_placeholder",
                path=".scratch/phase-state.json",
                cause=f"verification[{issue['index']}] is a {issue['reason']}.",
                impact="A low-reasoning agent may claim done without concrete evidence.",
                fix="Replace the placeholder with an exact command or an observable review action that already fits the phase.",
                evidence=issue["command"],
            )
        )
    return findings


def installed_scope_doctor_findings(root: Path) -> list[DoctorFinding]:
    return [
        DoctorFinding(
            severity="P2",
            code=issue["code"],
            path=str(INSTALL_STATE),
            cause=issue["cause"],
            impact=issue["impact"],
            fix=issue["fix"],
            evidence=issue["evidence"],
        )
        for issue in installed_scope_issues(root / INSTALL_STATE)
    ]


def command_mode_doctor_findings(root: Path) -> list[DoctorFinding]:
    roomodes_path = root / ".roomodes"
    commands_dir = root / ".roo/commands"
    if not roomodes_path.exists() or not commands_dir.exists():
        return []
    try:
        modes = json.loads(roomodes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="roomodes_invalid_json",
                path=".roomodes",
                cause=str(exc),
                impact="Roo cannot reliably load project-local modes.",
                fix="Repair `.roomodes` JSON and run `jq . .roomodes >/dev/null`.",
                evidence=f"line {exc.lineno} column {exc.colno}",
            )
        ]
    known = {mode["slug"] for mode in modes.get("customModes", []) if isinstance(mode, dict) and "slug" in mode}
    findings: list[DoctorFinding] = []
    for command in commands_dir.glob("*.md"):
        text = command.read_text(encoding="utf-8")
        match = re.search(r"^mode:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
        if match and match.group(1) not in known:
            relative = str(command.relative_to(root))
            findings.append(
                DoctorFinding(
                    severity="P1",
                    code="command_unknown_mode",
                    path=relative,
                    cause=f"Command references unknown Roo mode {match.group(1)!r}.",
                    impact="The slash command may route to a mode that Roo cannot start.",
                    fix="Update the command frontmatter or add the missing mode to `.roomodes`.",
                    evidence=f"{relative} -> {match.group(1)}",
                )
            )
    return findings


def db_context_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    gitignore_path = root / ".gitignore"
    gitignore = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    required_patterns = [".db-context/", "db-context.config.json", "*.db-context.config.json", ".env", ".env.*", "!.env.example"]
    for pattern in required_patterns:
        if pattern not in gitignore:
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="db_context_secret_ignore_missing",
                    path=".gitignore",
                    cause=f"Secret-bearing DB context pattern {pattern!r} is not ignored.",
                    impact="Connection strings or generated DB context artifacts may be committed accidentally.",
                    fix=f"Add `{pattern}` to `.gitignore`.",
                    evidence=pattern,
                )
            )
    snapshot_path = root / ".db-context/latest.json"
    if snapshot_path.exists():
        try:
            report = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="db_context_snapshot_invalid_json",
                    path=".db-context/latest.json",
                    cause=str(exc),
                    impact="DB-dependent workflows cannot safely read cached database context.",
                    fix="Refresh the DB context snapshot after explicit user approval or repair the JSON.",
                    evidence=f"line {exc.lineno} column {exc.colno}",
                )
            )
        else:
            options = report.get("collection_options", {})
            if options.get("snapshot_scope") == "selected" and not any(
                options.get(key) for key in ("include_tables", "include_procedures", "include_jobs")
            ):
                findings.append(
                    DoctorFinding(
                        severity="P2",
                        code="db_context_selected_empty",
                        path=".db-context/latest.json",
                        cause="Snapshot scope is selected but no selected objects are recorded.",
                        impact="Agents may believe the snapshot is intentionally narrow while it contains no target object list.",
                        fix="Refresh with `--snapshot-scope selected` plus `--include-tables`, `--include-procedures`, or `--include-jobs`.",
                        evidence="collection_options.snapshot_scope=selected",
                    )
                )
            if options.get("include_jobs") and "agent_jobs" not in report:
                findings.append(
                    DoctorFinding(
                        severity="P2",
                        code="db_context_jobs_requested_not_collected",
                        path=".db-context/latest.json",
                        cause="Selected jobs are recorded but SQL Agent job metadata is absent.",
                        impact="Workflow review may miss job commands or schedules.",
                        fix="Refresh with `--include-agent-jobs --include-jobs <names>` after explicit user approval.",
                        evidence="include_jobs present; agent_jobs missing",
                    )
                )
    return findings


def opencode_profile_rules_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    cmd_dir = root / ".opencode/commands"
    if not cmd_dir.exists():
        return findings
    for name in ("discuss.md", "plan.md", "execute.md", "done.md"):
        path = cmd_dir / name
        if not path.exists():
            continue
        if ".opencode/profile-rules/" not in path.read_text(encoding="utf-8"):
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="opencode_profile_rules_missing",
                    path=f".opencode/commands/{name}",
                    cause=f"{name} is missing the .opencode/profile-rules/ read instruction.",
                    impact="Profile-specific rules will not be loaded when the command is invoked.",
                    fix=f"Add the profile-rules read instruction to .opencode/commands/{name}.",
                    evidence=f"{name}: missing .opencode/profile-rules/ read instruction",
                )
            )
    return findings


def render_doctor_report(findings: list[DoctorFinding], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps({"findings": [finding.to_dict() for finding in findings]}, indent=2, sort_keys=True) + "\n"
    if output_format != "markdown":
        raise SystemExit("doctor format must be markdown or json")
    if not findings:
        return "# Harness Doctor\n\nNo findings.\n"
    lines = ["# Harness Doctor", ""]
    for finding in findings:
        lines.extend(
            [
                f"## {finding.severity} {finding.code}",
                "",
                f"- Path: `{finding.path}`",
                f"- Cause: {finding.cause}",
                f"- Impact: {finding.impact}",
                f"- Fix: {finding.fix}",
                f"- Evidence: {finding.evidence}",
                f"- Connects to DB: `{str(finding.connects_to_db).lower()}`",
                "",
            ]
        )
    return "\n".join(lines)


def check_changed_paths(target: Path, base: str) -> None:
    state_path = target / ".scratch/phase-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not changed_path_gate_allows_state(state):
        raise SystemExit("Changed-path check requires phase=execute with approved=true or phase=done with approved=false")
    changed = git_changed_paths(target, base)
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Changed paths outside allowed_paths: " + ", ".join(denied))


def check_worktree_paths(target: Path) -> None:
    state = json.loads((target / ".scratch/phase-state.json").read_text(encoding="utf-8"))
    if not changed_path_gate_allows_state(state):
        raise SystemExit("Worktree changed-path check requires phase=execute with approved=true or phase=done with approved=false")
    changed = sorted(set(git_worktree_paths(target)))
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Worktree paths outside allowed_paths: " + ", ".join(denied))


def changed_path_gate_allows_state(state: dict[str, object]) -> bool:
    return (state.get("phase") == "execute" and state.get("approved") is True) or (
        state.get("phase") == "done" and state.get("approved") is False
    )


def git_changed_paths(target: Path, base: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=target,
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def git_worktree_paths(target: Path) -> list[str]:
    outputs = [
        subprocess.check_output(["git", "diff", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=target, text=True),
    ]
    return [line.strip() for output in outputs for line in output.splitlines() if line.strip()]


def path_allowed(path: str, allowed: Iterable[str], blocked: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    if matches_any(normalized, blocked):
        return False
    return matches_any(normalized, allowed)


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        normalized = normalize_path(pattern)
        if normalized.endswith("/"):
            if path.startswith(normalized):
                return True
        elif path == normalized:
            return True
    return False


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_text_file(path: Path) -> bool:
    return path.suffix in {".md", ".json", ".txt", ".yml", ".yaml", ".toml", ".sh", ".py"} or path.name in {
        "AGENTS.md",
        ".roomodes",
        ".gitignore",
    }


if __name__ == "__main__":
    raise SystemExit(run())
