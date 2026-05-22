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
import os
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
    HashDriftFinding,
    managed_block_warnings,
    verify_hashes,
    format_hash_drift_errors,
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
    hash_drift_doctor_findings,
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
from lib.state_cli import run_show as state_run_show, run_repair as state_run_repair, resolve_root as state_resolve_root
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
    "state_run_show", "state_run_repair", "state_resolve_root", "state_repair_fn", "StateRepairReport",
    "managed_render_block", "managed_parse_blocks", "managed_replace_block",
    "managed_canonicalize",
    # local
    "HARNESS_VERSION", "CLEAN_SKELETON", "UTC_TIMESTAMP", "VERIFICATION_PREFIXES",
    "REQUIRED_TARGET_PHRASES", "CONTAMINATION_PATTERNS",
    "run", "run_delegated_command",
    # status-next
    "cmd_status", "cmd_next", "cmd_run", "cmd_check_machine",
]


def install(
    *,
    root: Path,
    target: Path,
    dry_run: bool = False,
    adapters: set[str] | None = None,
    profiles: set[str] | None = None,
    packs: set[str] | None = None,
    approver_email: str | None = None,
    approver_bootstrap_source: str | None = None,
    quiet: bool = False,
    force: bool = False,
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
        approver_email=approver_email,
        approver_bootstrap_source=approver_bootstrap_source,
        quiet=quiet,
        force=force,
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
    quiet: bool = False,
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
        quiet=quiet,
    )


def check(
    *,
    root: Path,
    target: Path | None = None,
    base: str | None = None,
    worktree: bool = False,
    adapter: str | None = None,
    verify_hashes: bool = False,
) -> None:
    _check_mod.check(
        root=root,
        target=target,
        base=base,
        worktree=worktree,
        adapter=adapter,
        harness_version=HARNESS_VERSION,
        verify_hashes=verify_hashes,
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


class _HintingArgumentParser(argparse.ArgumentParser):
    """argparse parser that prints a 'did you mean ...?' hint to stderr
    on 'invalid choice' errors.

    Preserves the original error message text and exit code 2 entirely —
    the hint is emitted BEFORE delegating to super().error(). Subparsers
    inherit this class automatically via argparse's parser_class default.
    """

    def error(self, message):  # type: ignore[override]
        try:
            import re as _re
            import difflib as _difflib
            m = _re.search(r"invalid choice: ['\"]([^'\"]+)['\"] \(choose from (.+)\)", message)
            if m:
                bad = m.group(1)
                choices = _re.findall(r"['\"]([^'\"]+)['\"]", m.group(2))
                close = _difflib.get_close_matches(bad, choices, n=2, cutoff=0.6)
                if close:
                    self._print_message(
                        f"hint: did you mean: {', '.join(close)}?\n",
                        sys.stderr,
                    )
        except (BrokenPipeError, OSError):
            pass
        super().error(message)


def main() -> int:
    """Entry point alias for `run()` — used by harness_cli.py console script."""
    return run()


def _normal_help() -> str:
    return (
        "usage: harness [next|run|check]\n\n"
        "Normal workflow:\n"
        "  harness        Show this guide.\n"
        "  harness next   Show the next safe action.\n"
        "  harness run    Run the next safe workflow step; stops for approval.\n"
        "  harness check  Validate the harness and project workflow state.\n\n"
        "Advanced/debug commands are hidden from the normal path. "
        "Set HARNESS_ADVANCED=1 to show the full command surface.\n"
    )


def run(argv: list[str] | None = None) -> int:
    global HARNESS_VERSION

    # S07: check for deprecated flags BEFORE argparse sees them (§3.3, §3.4).
    # --chain / --auto are detected anywhere in argv; halt with exit 13 +
    # structured hint + audit entry verb=cli.deprecated_flag.
    _check_argv = argv if argv is not None else sys.argv[1:]
    if os.environ.get("HARNESS_ADVANCED") != "1" and (
        not _check_argv or _check_argv in (["-h"], ["--help"])
    ):
        sys.stdout.write(_normal_help())
        return 0
    try:
        from lib.cli_deprecated import check_deprecated_flags, print_and_exit
        _dep_err = check_deprecated_flags(
            _check_argv,
            audit_path=None,  # no audit path here; audit written only if repo-root available
        )
        if _dep_err is not None:
            # Try to write audit to the default .harness/audit.log if we can find the repo root
            try:
                _repo = repo_root()
                _audit_path = _repo / ".harness" / "audit.log"
                from lib.cli_deprecated import _write_audit_entry
                _write_audit_entry(_dep_err.flag, _dep_err.hint, audit_path=_audit_path)
            except Exception:
                pass
            print_and_exit(_dep_err)
            return 13  # unreachable — print_and_exit calls sys.exit
    except ImportError:
        pass  # cli_deprecated not available in this installation (older target)

    parser = _HintingArgumentParser(description=__doc__)
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
    init_parser.add_argument(
        "--approver-email",
        default=None,
        metavar="ADDR",
        help=(
            "[optional, v0.9.9+] Audit-display email recorded in "
            ".harness/install-record.json. Not required — harness auto-derives "
            "<user>@<host> when no value is provided. The approver field is no "
            "longer enforced (internal single-user threat model)."
        ),
    )
    init_parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress progress lines on stderr (init phase ticks). stdout summary is unchanged.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Overwrite existing harness-owned files and clear .harness/ "
            "before re-staging. Use to recover from a half-installed state "
            "(files present but installed-manifest.json missing). v0.9.12+."
        ),
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
    upgrade_parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress progress lines on stderr (Pass A/B ticks). stdout summary is unchanged.",
    )
    check_parser = subparsers.add_parser("check", help="Validate harness structure and policy.")
    check_parser.add_argument("--target", type=Path, default=None)
    check_parser.add_argument("--adapter", default=None, help="Validate a specific adapter in addition to installed adapters.")
    check_parser.add_argument("--base", default=None, help="Optional git base ref for changed-path checks.")
    check_parser.add_argument("--worktree", action="store_true", help="Check staged and unstaged paths against allowed_paths.")
    check_parser.add_argument(
        "--verify-hashes",
        action="store_true",
        default=False,
        help="Verify per-policy file hashes against installed-manifest.json (opt-in; always-on in doctor).",
    )

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

    # v0.9.13: phase autopilot verbs removed entirely (single-user tool).

    # ----- phase reopen (design §3.2) -----
    reopen_parser = phase_sub.add_parser(
        "reopen",
        help="Rewind phase to plan or discuss (design §3.2).",
    )
    reopen_parser.add_argument(
        "--to",
        choices=["plan", "discuss"],
        default="plan",
        help="Target phase to rewind to (default: plan).",
    )
    reopen_parser.add_argument(
        "--by",
        default=None,
        help="Approver email (defaults to gitconfig).",
    )
    reopen_parser.add_argument(
        "--reason",
        default=None,
        help="Optional reason (audited).",
    )
    reopen_parser.add_argument(
        "--reset-approval",
        dest="reset_approval",
        action="store_true",
        default=False,
        help=(
            "Required when the current state is approved=True (backward move). "
            "Explicitly acknowledges that the prior approval will be revoked."
        ),
    )

    # ----- phase next-pending (design §3.5, Round-4) -----
    phase_sub.add_parser(
        "next-pending",
        help="Print next non-done roadmap phase slug (pure read, §3.5).",
    )

    # v0.9.13: fsd-run-phase / fsd-run-all wrappers removed (autopilot gone).

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

    # ----- halt-diary admin verbs (design §5.3 + §12.7) -----
    halt_diary_parser = subparsers.add_parser(
        "halt-diary",
        help="Halt-diary admin verbs (§5.3 + §12.7).",
    )
    halt_diary_sub = halt_diary_parser.add_subparsers(
        dest="halt_diary_command", required=True
    )
    hd_clear = halt_diary_sub.add_parser(
        "clear",
        help=(
            "Acknowledge and clear the last_halt diary entry. "
            "TTY-required admin verb (§12.7)."
        ),
    )
    hd_clear.add_argument(
        "--by",
        dest="by",
        default=None,
        metavar="EMAIL",
        help="Acting user email (recorded in audit row; defaults to gitconfig).",
    )

    # ----- harness status (§3.9) -----
    status_parser = subparsers.add_parser(
        "status",
        help="Show current phase + halt diary + next action (§3.9).",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON.",
    )

    # ----- harness next (§3.9) -----
    next_parser = subparsers.add_parser(
        "next",
        help="Recommended next action (§3.9).",
    )
    next_group = next_parser.add_mutually_exclusive_group()
    next_group.add_argument(
        "--shell",
        action="store_true",
        help=(
            "Stdout safe for shell execution; exit 17 if requires_human, "
            "exit 18 if autopilot active."
        ),
    )
    next_group.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON: {requires_human, agent_safe, command, reason}.",
    )

    # ----- harness run (v0.8 normal path) -----
    subparsers.add_parser(
        "run",
        help="Run the next safe workflow step; stops for human approval.",
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
        # T7 / NEW-1: resolve bootstrap approver email before install.
        # Skip for --dry-run (no files are written).
        _approver_email: str | None = None
        _approver_bootstrap_source: str | None = None
        if not args.dry_run:
            from lib.install import resolve_approver_email as _rae
            _approver_email, _approver_bootstrap_source = _rae(
                cli_flag=getattr(args, "approver_email", None),
                root=root,
            )
        install(
            root=root,
            target=args.target,
            dry_run=args.dry_run,
            adapters=parse_scope(args.adapters, default={"roo"}),
            profiles=set(profiles_resolved),
            packs=final_packs,
            approver_email=_approver_email,
            approver_bootstrap_source=_approver_bootstrap_source,
            quiet=getattr(args, "quiet", False),
            force=getattr(args, "force", False),
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
            quiet=getattr(args, "quiet", False),
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
        if getattr(args, "verify_hashes", False):
            command.append("--verify-hashes")
        if os.environ.get("HARNESS_MACHINE") == "1":
            result = subprocess.run(command, cwd=root, text=True, capture_output=True)
            warnings = []
            for stream in (result.stderr, result.stdout):
                for line in stream.splitlines():
                    if line.strip():
                        warnings.append(line.strip())
            from lib.status_next_cli import cmd_check_machine, _read_current_state_for_machine
            state = _read_current_state_for_machine(Path.cwd())
            return cmd_check_machine(
                result.returncode,
                phase=state.get("phase", "unknown"),
                warnings=warnings if result.returncode else [],
            )
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
        # Use cwd walk-up resolution so `state show` always reflects the
        # project the user is currently working in, not the harness source
        # tree.  --root and HARNESS_STATE_ROOT override the walk-up.
        state_root = state_resolve_root(args.root if hasattr(args, "root") else None)
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
        from lib.phase_cli import (
            cmd_phase_set,
            cmd_phase_approve,
            cmd_phase_reopen,
            cmd_phase_next_pending,
        )
        if args.phase_command == "set":
            return cmd_phase_set(args)
        if args.phase_command == "approve":
            return cmd_phase_approve(args)
        if args.phase_command == "reopen":
            return cmd_phase_reopen(args)
        if args.phase_command == "next-pending":
            return cmd_phase_next_pending(args)
        raise AssertionError(f"Unhandled phase subcommand: {args.phase_command}")
    if args.command == "session":
        from lib.phase_cli import cmd_session_unlock
        if args.session_command == "unlock":
            return cmd_session_unlock(args)
        raise AssertionError(f"Unhandled session subcommand: {args.session_command}")
    if args.command == "halt-diary":
        from lib.halt_diary_cli import cmd_halt_diary_clear
        if args.halt_diary_command == "clear":
            return cmd_halt_diary_clear(args)
        raise AssertionError(f"Unhandled halt-diary subcommand: {args.halt_diary_command}")
    if args.command == "verify":
        from lib.audit_verify_cli import cmd_verify_audit
        return cmd_verify_audit(args, root)
    if args.command == "status":
        from lib.status_next_cli import cmd_status
        return cmd_status(args)
    if args.command == "next":
        from lib.status_next_cli import cmd_next
        return cmd_next(args)
    if args.command == "run":
        from lib.status_next_cli import cmd_run
        return cmd_run(args)
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    import traceback as _traceback

    try:
        raise SystemExit(run())
    except SystemExit:
        raise
    except PermissionError as _exc:
        # v0.9.11: top-level PermissionError catcher. Mostly hit on Windows
        # when AV/EDR holds a file handle longer than the 7.85 s replace
        # backoff, or when target was originally installed by an elevated
        # user and a non-elevated retry hits a write-blocked .harness/.
        # Surface one actionable message instead of a Python traceback.
        _path_hint = ""
        try:
            _path_hint = f" — path: {_exc.filename!r}" if getattr(_exc, "filename", None) else ""
        except Exception:
            pass
        print(
            f"error: 권한 거부 (PermissionError){_path_hint}\n"
            f"\n"
            f"흔한 원인 + 대처:\n"
            f"  1) target 디렉토리가 다른 사용자 권한으로 만들어짐\n"
            f"     → 새 폴더에 init 또는 takeown/icacls 로 권한 회수\n"
            f"  2) AV/EDR (Defender 등) 가 파일 핸들 점유 중\n"
            f"     → 잠시 후 재시도 (보통 5~10 초). 또는 target 폴더 AV 예외 등록.\n"
            f"  3) source 와 target 이 같은 폴더 → 다른 폴더로 분리\n"
            f"\n"
            f"세부 traceback: HARNESS_DEBUG=1 환경 변수 설정 후 재실행.\n"
            f"[Top-level PermissionError. Most likely Windows AV handle pin or "
            f"prior elevated install. Retry, switch target, or whitelist in AV.]",
            file=sys.stderr,
        )
        if os.environ.get("HARNESS_DEBUG") == "1":
            _traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except Exception as _exc:
        if os.environ.get("HARNESS_DEBUG") == "1":
            _traceback.print_exc(file=sys.stderr)
        else:
            _tb = _traceback.extract_tb(_exc.__traceback__)
            if _tb:
                _first = _tb[0]
                print(
                    f"error: {type(_exc).__name__} at "
                    f"{_first.filename}:{_first.lineno}: {_exc}",
                    file=sys.stderr,
                )
            else:
                print(f"error: {type(_exc).__name__}: {_exc}", file=sys.stderr)
            print("Set HARNESS_DEBUG=1 for full traceback.", file=sys.stderr)
        sys.exit(1)
