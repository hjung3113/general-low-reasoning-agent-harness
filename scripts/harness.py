#!/usr/bin/env python3
"""Thin CLI dispatcher for the harness.

All non-CLI logic lives under ``scripts.lib.*``. This module imports each
public symbol and re-exports it so existing callers — including the test
suite and target-installed wrappers — continue to import names from
``scripts.harness``.

When adding a new function or class, prefer placing it directly in the
appropriate ``scripts.lib`` module and adding a single import line here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

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
from lib.worktree import (
    check_changed_paths,
    check_worktree_paths,
    changed_path_gate_allows_state,
    git_changed_paths,
    git_worktree_paths,
    path_allowed,
    matches_any,
    is_relative_to,
    is_text_file,
)
from lib.adoption import (
    AdoptionConflict,
    AdoptionPlan,
    assert_safe_write_destination,
    normalize_selected_project_owned_state,
    build_adopted_install_state,
    is_required_adoption_project_owned_path,
    is_optional_project_owned_path,
    is_existing_harness_artifact,
)
from lib.check import (
    CLEAN_SKELETON,
    UTC_TIMESTAMP,
    VERIFICATION_PREFIXES,
    REQUIRED_TARGET_PHRASES,
    CONTAMINATION_PATTERNS,
    ManagedBlockWarning,
    managed_block_warnings,
    check_installed_target,
    _check_roomodes_profile_sync,
    check_clean_skeleton,
    check_json,
    check_phase_state_semantics,
    check_command_modes,
    check_phase_reference_drift,
    check_phase_state_paths,
)
import lib.check as _check_mod
from lib.doctor import (
    DoctorFinding,
    doctor,
    collect_doctor_findings,
    phase_status_projection_doctor_findings,
    projection_warning_severity,
    roadmap_state_doctor_findings,
    phase_state_path_doctor_findings,
    verification_contract_doctor_findings,
    installed_scope_doctor_findings,
    command_mode_doctor_findings,
    db_context_doctor_findings,
    opencode_profile_rules_doctor_findings,
    render_doctor_report,
)
from lib.install import (
    sync_roomodes_profile_modes,
    write_copy,
    write_text_file,
    write_text_conflict,
    remove_empty_parents,
)
from lib.upgrade import (
    migrate_install_state,
    install_state_migration_report,
)
from lib.planning_status import ProjectionError, load_projection
from lib.state_cli import run_show as state_run_show, run_repair as state_run_repair
from lib.state_repair import repair as state_repair_fn, RepairReport as StateRepairReport
from lib.managed_block import (
    render_block as managed_render_block,
    parse_blocks as managed_parse_blocks,
    replace_block as managed_replace_block,
    canonicalize as managed_canonicalize,
)
from lib.workflow_static_checks import (
    installed_scope_issues,
    optional_phase_pointer_keys,
    verification_contract_issues,
    verification_placeholder_reason,
)

# Module-level constant; set to the resolved version inside run().
HARNESS_VERSION = "0.0.0-dev+unknown"

__all__ = [
    # version
    "repo_root", "upgrade_source_root", "normalize_release_version", "git_output",
    "is_git_worktree_dirty", "exact_release_tag_version", "development_version",
    "git_source_provenance", "source_provenance", "resolve_harness_version",
    "release_check", "readme_release_versions", "check_readme_release_versions",
    "README_RELEASE_VERSION",
    # profiles
    "KNOWN_PROFILES", "LEGACY_PROFILE_ALIASES", "PROFILE_MODE_OWNERS",
    "default_packs_for_profile", "db_packs", "normalize_profiles",
    # manifest
    "ManifestEntry", "KNOWN_ADAPTERS", "KNOWN_POLICIES", "KNOWN_PACKS",
    "MANIFEST_PATH", "MANIFEST_SOURCE_VERSION",
    "load_manifest", "load_manifest_data", "selected_pack_metadata",
    "select_entries", "validate_scope_names", "infer_adapter", "infer_pack",
    "infer_owner", "source_path", "destination_path",
    "validate_managed_append_destinations",
    # append_block
    "AppendBlockPlan", "ParsedAppendBlock", "marker_start", "marker_end",
    "marker_end_for_path", "render_append_block", "parse_append_block",
    "append_block_to_text", "replace_block", "write_managed_append",
    "plan_managed_append", "plan_managed_append_retirement",
    # state
    "INSTALL_STATE", "scope_record", "delegated_source_provenance",
    "installed_scope", "available_scopes", "parse_optional_scope", "parse_scope",
    "write_install_state", "read_install_state", "validate_installed_scope_names",
    "validate_installed_managed_append", "required_phrase_scope",
    "write_json", "file_hash", "file_state", "now_utc", "manifest_sha256",
    "sha256_text", "normalize_payload",
    # roadmap_state
    "RoadmapPhase", "StateSnapshot", "normalize_path", "parse_roadmap_phases",
    "parse_state_snapshot", "parse_frontmatter", "split_frontmatter_pair",
    "int_value", "markdown_section", "check_roadmap_state_sync",
    "roadmap_state_sync_applicable", "find_roadmap_state_sync_findings",
    # worktree
    "check_changed_paths", "check_worktree_paths", "changed_path_gate_allows_state",
    "git_changed_paths", "git_worktree_paths", "path_allowed", "matches_any",
    "is_relative_to", "is_text_file",
    # adoption
    "AdoptionConflict", "AdoptionPlan", "normalize_selected_project_owned_state",
    "build_adopted_install_state", "is_required_adoption_project_owned_path",
    "is_optional_project_owned_path", "is_existing_harness_artifact",
    "assert_safe_write_destination",
    # check
    "check", "check_installed_target", "should_check_as_installed_target",
    "check_clean_skeleton", "check_json", "check_phase_state_semantics",
    "check_command_modes", "check_phase_reference_drift", "check_phase_state_paths",
    "ManagedBlockWarning", "managed_block_warnings",
    # doctor
    "DoctorFinding", "doctor", "collect_doctor_findings",
    "phase_status_projection_doctor_findings", "projection_warning_severity",
    "roadmap_state_doctor_findings", "phase_state_path_doctor_findings",
    "verification_contract_doctor_findings", "installed_scope_doctor_findings",
    "command_mode_doctor_findings", "db_context_doctor_findings",
    "opencode_profile_rules_doctor_findings", "render_doctor_report",
    # install
    "install", "sync_roomodes_profile_modes", "write_copy", "write_text_file",
    "write_text_conflict", "remove_empty_parents",
    # upgrade
    "upgrade", "migrate_install_state", "install_state_migration_report",
    # planning_status
    "ProjectionError", "load_projection",
    # workflow_static_checks
    "installed_scope_issues", "optional_phase_pointer_keys",
    "verification_contract_issues", "verification_placeholder_reason",
    # state CLI
    "state_run_show", "state_run_repair", "state_repair_fn", "StateRepairReport",
    "managed_render_block", "managed_parse_blocks", "managed_replace_block",
    "managed_canonicalize",
    # local
    "HARNESS_VERSION", "CLEAN_SKELETON", "UTC_TIMESTAMP", "VERIFICATION_PREFIXES",
    "REQUIRED_TARGET_PHRASES", "CONTAMINATION_PATTERNS",
    "run", "run_delegated_command",
]


def install(
    *,
    root: Path,
    target: Path,
    dry_run: bool = False,
    adapters: set[str] | None = None,
    profiles: set[str] | None = None,
    packs: set[str] | None = None,
) -> None:
    from lib.install import install as _install
    return _install(
        root=root,
        target=target,
        dry_run=dry_run,
        adapters=adapters,
        profiles=profiles,
        packs=packs,
        harness_version=HARNESS_VERSION,
    )


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
    from lib.upgrade import upgrade as _upgrade
    return _upgrade(
        root=root,
        target=target,
        dry_run=dry_run,
        force=force,
        adopt_existing=adopt_existing,
        adapters=adapters,
        profiles=profiles,
        packs=packs,
        harness_version=HARNESS_VERSION,
    )


def check(
    *,
    root: Path,
    target: Path | None = None,
    base: str | None = None,
    worktree: bool = False,
    adapter: str | None = None,
) -> None:
    _check_mod.check(
        root=root,
        target=target,
        base=base,
        worktree=worktree,
        adapter=adapter,
        harness_version=HARNESS_VERSION,
    )


def should_check_as_installed_target(root: Path) -> bool:
    return _check_mod.should_check_as_installed_target(root, harness_version=HARNESS_VERSION)


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

    install_parser = subparsers.add_parser(
        "install",
        help="Install harness add-ons such as the pre-commit scope-check hook (T1-1).",
    )
    install_parser.add_argument("--target", required=True, type=Path)
    install_parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Install the pre-commit scope-check hook into <target>/.git/hooks/pre-commit (T1-1).",
    )

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
    uninstall_parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Uninstall the pre-commit scope-check hook from <target>/.git/hooks/pre-commit (T1-1).",
    )

    release_parser = subparsers.add_parser("release-check", help="Verify release version, tag, and worktree gates.")
    release_parser.add_argument("--expected-version", default=None, help="Optional expected vMAJOR.MINOR.PATCH release tag.")
    release_parser.add_argument(
        "--require-origin-main",
        action="store_true",
        help="Fail unless the tagged commit equals origin/main.",
    )

    state_parser = subparsers.add_parser(
        "state",
        help="Inspect and repair managed planning state.",
    )
    state_sub = state_parser.add_subparsers(dest="state_command", required=True)

    state_show = state_sub.add_parser("show", help="Print phase-state projection (read-only).")
    state_show.add_argument("--root", type=Path, default=None)
    state_show.add_argument("--format", dest="state_format", choices=("text", "json"), default="text")

    state_repair_p = state_sub.add_parser("repair", help="Canonicalize managed marker blocks.")
    state_repair_p.add_argument("--root", type=Path, default=None)

    # `harness migrate state ...` -- thin delegator to scripts/migrate_state.py
    # (T0-1 CC1). All flags are forwarded verbatim.
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate harness state files between schema versions.",
    )
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_command", required=True)
    migrate_state_p = migrate_sub.add_parser(
        "state",
        help="Migrate .scratch/phase-state.json between v0 and v2 (ADR-001).",
    )
    mig_mode = migrate_state_p.add_mutually_exclusive_group(required=True)
    mig_mode.add_argument("--forward", action="store_true",
                          help="Apply v0 -> v2 transformation.")
    mig_mode.add_argument("--reverse", action="store_true",
                          help="Apply v2 -> v0 transformation.")
    mig_mode.add_argument("--resume", action="store_true",
                          help="Resume from sidecar after crash.")
    migrate_state_p.add_argument("--target", default=".scratch/phase-state.json",
                                 help="Path to phase-state file.")
    migrate_state_p.add_argument("--dry-run", action="store_true",
                                 help="Print canonical transformed output to stdout; no disk mutation.")

    # ----- phase lifecycle verbs (ADR-003a Artifact 1, T0-3) -----
    phase_parser = subparsers.add_parser(
        "phase",
        help="Phase lifecycle verbs (ADR-003a Artifact 1).",
    )
    phase_sub = phase_parser.add_subparsers(dest="phase_command", required=True)

    p_set = phase_sub.add_parser(
        "set", help="Set current phase (ADR-001 transition table)."
    )
    p_set.add_argument(
        "phase", choices=["discuss", "plan", "execute", "done"]
    )
    p_set.add_argument("--plan-id", default=None)
    p_set.add_argument("--summary", default=None)
    p_set.add_argument("--reset-approval", action="store_true")
    p_set.add_argument("--stdin-json", action="store_true")

    p_approve = phase_sub.add_parser(
        "approve", help="Approve current phase (ADR-003a verb 2)."
    )
    p_approve.add_argument("--by", default=None)
    p_approve.add_argument("--at", default=None)
    p_approve.add_argument("--stdin-json", action="store_true")

    # ----- session operational verbs (ADR-003a verb 3, T0-3) -----
    session_parser = subparsers.add_parser(
        "session",
        help="Session operational verbs (ADR-003a verb 3).",
    )
    session_sub = session_parser.add_subparsers(
        dest="session_command", required=True
    )
    s_unlock = session_sub.add_parser(
        "unlock", help="Remove a stale session lockfile (G1-B recovery)."
    )
    s_unlock.add_argument("--force", action="store_true")
    s_unlock.add_argument(
        "--print", dest="print_only", action="store_true",
        help="Print the lockfile payload and exit 0 without removing.",
    )

    # harness verify --audit [--fixture <dir>] (design §12.7, §12.9, S06)
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify audit log chain integrity (§2.2, §12.7).",
    )
    verify_parser.add_argument(
        "--audit",
        action="store_true",
        required=True,
        help="Verify the audit log chain.",
    )
    verify_parser.add_argument(
        "--fixture",
        dest="verify_fixture",
        default=None,
        metavar="DIR",
        help=(
            "Override source to verify from <DIR>/audit.log + rotation files. "
            "Anchor checks are skipped (§12.9)."
        ),
    )

    # Audit-tip anchor admin verbs (design doc §12.1, S00.7-anchor).
    anchor_parser = subparsers.add_parser(
        "anchor",
        help="Out-of-repo audit-tip anchor admin verbs (TTY-only).",
    )
    anchor_sub = anchor_parser.add_subparsers(dest="anchor_command", required=True)
    a_repair = anchor_sub.add_parser(
        "repair",
        help="Rebuild ~/.harness/audit-tip/<repo-id>.json from current live state.",
    )
    a_repair.add_argument(
        "--by",
        dest="anchor_by",
        default=None,
        help="Acting user email (recorded in the future audit entry that wraps repair).",
    )
    a_repair.add_argument(
        "--accept-no-audit",
        action="store_true",
        help=(
            "Allow repair before any audit entries exist (S00.7 boot path). "
            "Without this flag, repair refuses when no audit tail is found."
        ),
    )
    a_repair.add_argument(
        "--accept-no-install-record",
        action="store_true",
        help=(
            "Allow repair before .harness/install-record.json exists, OR when "
            "its install_id field is missing. Mints a fresh UUID. Use only "
            "during first install bootstrap (S00.7) — otherwise repair refuses "
            "to silently invent an install_id."
        ),
    )

    args = parser.parse_args(argv)
    root = repo_root()
    command_root = root
    if args.command == "upgrade":
        command_root = upgrade_source_root(root, args.target)
    HARNESS_VERSION = resolve_harness_version(command_root, explicit=args.release_version)

    if args.command == "install":
        # T1-1 pre-commit hook installer. Other install scopes may be wired
        # here in future slices.
        from lib.hooks import install_pre_commit_hook
        if args.pre_commit:
            install_pre_commit_hook(args.target)
            return 0
        raise SystemExit(
            "harness install: at least one install scope is required "
            "(e.g., --pre-commit)"
        )
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
        # T1-1 pre-commit hook removal short-circuits the standard
        # uninstaller (which requires INSTALL_STATE in target).
        if args.pre_commit:
            from lib.hooks import uninstall_pre_commit_hook
            if args.target is None:
                raise SystemExit("--target is required for --pre-commit")
            uninstall_pre_commit_hook(args.target)
            return 0
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
    if args.command == "state":
        state_root = Path(args.root) if args.root else root
        if args.state_command == "show":
            return state_run_show(root=state_root, stream=sys.stdout, fmt=args.state_format)
        if args.state_command == "repair":
            return state_run_repair(root=state_root, stream=sys.stdout)
        raise AssertionError(f"Unhandled state subcommand: {args.state_command}")
    if args.command == "migrate":
        if args.migrate_command == "state":
            # Forward args to scripts/migrate_state.py:main().
            import migrate_state as _migrate_state
            forwarded: list[str] = []
            if args.forward:
                forwarded.append("--forward")
            elif args.reverse:
                forwarded.append("--reverse")
            elif args.resume:
                forwarded.append("--resume")
            forwarded.extend(["--target", str(args.target)])
            if args.dry_run:
                forwarded.append("--dry-run")
            return _migrate_state.main(forwarded)
        raise AssertionError(f"Unhandled migrate subcommand: {args.migrate_command}")
    if args.command == "phase":
        from lib.phase_cli import cmd_phase_set, cmd_phase_approve
        if args.phase_command == "set":
            return cmd_phase_set(args)
        if args.phase_command == "approve":
            return cmd_phase_approve(args)
        raise AssertionError(f"Unhandled phase subcommand: {args.phase_command}")
    if args.command == "session":
        from lib.phase_cli import cmd_session_unlock
        if args.session_command == "unlock":
            return cmd_session_unlock(args)
        raise AssertionError(f"Unhandled session subcommand: {args.session_command}")
    if args.command == "verify":
        from lib.audit_verify_cli import cmd_verify_audit
        return cmd_verify_audit(args, root)
    if args.command == "anchor":
        from lib.anchor_cli import cmd_anchor_repair
        if args.anchor_command == "repair":
            return cmd_anchor_repair(args, root)
        raise AssertionError(f"Unhandled anchor subcommand: {args.anchor_command}")
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(run())
