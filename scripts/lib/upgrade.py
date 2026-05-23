"""Upgrade flow: migrate legacy install state, re-apply manifest."""
from __future__ import annotations

import copy
import datetime
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Iterable

from lib.adoption import (
    AdoptionConflict,
    AdoptionPlan,
    build_adopted_install_state,
    normalize_selected_project_owned_state,
)
from lib.install import (
    install as _install_run,
    sync_roomodes_profile_modes,
    write_copy,
    # NOTE (T0-A, deliberate exclusion): write_text_file / write_text_conflict
    # are SKILL-pack content writers. They re-enter lib.install.write_text_file,
    # which is annotated in install.py as a non-state/non-operational writer
    # excluded from the T0-A atomic-write grep gate. Upgrade flow's call sites
    # (lines 184 and 235 in the pre-T0-A tree) therefore inherit the same
    # exclusion. See plan task 17 in
    # .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md.
    write_text_file,
    write_text_conflict,
    remove_empty_parents,
)
from lib.manifest import (
    MANIFEST_PATH,
    ManifestEntry,
    load_manifest,
    load_manifest_data,
    select_entries,
    validate_scope_names,
    source_path,
    destination_path,
    selected_pack_metadata,
    obsolete_artifact_policy,
)
from lib.profiles import LEGACY_PROFILE_ALIASES, normalize_profiles
from lib.roadmap_state import normalize_path
from lib.state import (
    INSTALL_STATE,
    read_install_state,
    build_install_state_payload,
    scope_record,
    write_install_state,
    write_json,
    installed_scope,
    available_scopes,
    file_hash,
    file_state,
    manifest_sha256,
)
from lib.atomic_io import atomic_install_batch, CrossFilesystemError
from lib.progress import ProgressReporter
from lib.install import (
    InstallFailed,
    _atomic_write_json_fsync,
    _rmdir_recursive_quiet,
)
from lib.version import (
    repo_root,
    resolve_harness_version,
    source_provenance,
)
# S12 — manifest v2 reconciler (§6)
from lib.manifest_reconciler import (
    ReconcileDecision,
    reconcile_install as _reconcile_install,
)
from lib.manifest_v2 import read_manifest as _read_manifest_v2
from lib.state import now_utc as _now_utc


class UpgradeRefused(SystemExit):
    """Raised when the skip-upgrade guard blocks an unsupported version hop."""


def _semver_ge(a: str, b: str) -> bool:
    """Return True if semver string a >= b (major.minor.patch comparison)."""
    def _parts(v: str) -> tuple[int, int, int]:
        parts = v.split(".")
        try:
            major = int(parts[0]) if parts else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2].split("-")[0].split("+")[0]) if len(parts) > 2 else 0
            return major, minor, patch
        except (ValueError, IndexError):
            return (0, 0, 0)
    return _parts(a) >= _parts(b)


def _check_skip_upgrade_guard(prior_state: dict, target_version: str) -> None:
    """Raise UpgradeRefused if this is a blocked skip-upgrade path.

    T6 guard: v0.9.4 → v0.9.7 direct upgrade is unsupported.
    Also raises UpgradeRefused if the prior version cannot be determined.
    """
    prior_version_raw = prior_state.get("version") or prior_state.get("harness_version") or ""
    prior_version = prior_version_raw.lstrip("v")
    target_version_raw = target_version.lstrip("v")

    if prior_version in {"", "unknown"}:
        raise UpgradeRefused(
            "이전 설치 버전을 확인할 수 없습니다. python3 scripts/harness.py state show 로 상태 점검 후 진행 "
            "[Cannot determine prior install version; run state show to inspect]"
        )

    if prior_version == "0.9.4" and _semver_ge(target_version_raw, "0.9.7"):
        if not os.environ.get("HARNESS_ALLOW_SKIP_UPGRADE"):
            raise UpgradeRefused(
                "v0.9.4 → v0.9.7 직접 업그레이드는 지원되지 않습니다. "
                "먼저 v0.9.5 로 업그레이드 후 다시 시도하세요. "
                "Override (권장하지 않음): HARNESS_ALLOW_SKIP_UPGRADE=1 "
                "[Skip-upgrade from v0.9.4 directly to v0.9.7 unsupported. "
                "Upgrade to v0.9.5 first. Override: HARNESS_ALLOW_SKIP_UPGRADE=1]"
            )


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


def _build_release_manifest_v2(
    *,
    root: Path,
    entries: list,
    harness_version: str,
    target: Path | None = None,
) -> dict:
    """Build a release_manifest dict in installed-manifest v2 format for the reconciler."""
    # ── Compute file hashes (working-tree path) ────────────────────────────
    files: dict[str, object] = {}
    for entry in entries:
        if entry.policy == "exclude":
            continue
        try:
            src = source_path(root, entry)
            sha = file_hash(src)
        except (FileNotFoundError, SystemExit):
            continue

        files[str(entry.path)] = {
            "installed_sha256": sha,
            "current_sha256": sha,
            "policy": entry.policy,
            "owner": entry.owner,
        }

    release_manifest: dict[str, object] = {
        "schema_version": 2,
        "harness_version": harness_version,
        "files": files,
    }
    return release_manifest


def _stamp_installed_manifest_v2(
    installed: dict,
    *,
    release_manifest: dict,
    harness_version: str,
    reconcile_results: list,
) -> None:
    """Stamp v2 fields onto *installed* (mutates in place) per §6.

    Adds:
    - ``schema_version: 2``
    - ``harness_version``
    - Per file-entry: ``installed_sha256``, ``current_sha256``
    - ``installed_files_chain_hash`` (computed over the final installed dict)

    USER_MODIFIED_QUARANTINE entries get a ``quarantine_path`` note.
    WARN lines for quarantined files go to stderr.
    """
    import sys as _sys
    installed["schema_version"] = 2
    installed["harness_version"] = harness_version

    release_files: dict[str, object] = release_manifest.get("files", {})  # type: ignore[assignment]
    installed_files: dict[str, object] = installed.get("files", {})  # type: ignore[assignment]

    # Build a lookup of reconcile results by path
    reconcile_by_path: dict[str, object] = {r.path: r for r in reconcile_results}

    quarantined_paths: list[tuple[str, str]] = []  # (path_str, quarantine_path)

    for path_str, entry_info in list(installed_files.items()):
        if not isinstance(entry_info, dict):
            continue
        rel_entry = release_files.get(path_str)
        if not isinstance(rel_entry, dict):
            continue
        entry_info["installed_sha256"] = rel_entry.get("installed_sha256", "")
        entry_info["current_sha256"] = rel_entry.get("current_sha256", "")
        rr = reconcile_by_path.get(path_str)
        if rr is not None and rr.decision == ReconcileDecision.USER_MODIFIED_QUARANTINE:
            qp = rr.quarantine_path or ""
            entry_info["quarantine_path"] = qp
            # Only record when a real file move happened.  classify_only=True
            # (used during --dry-run and the upgrade conflict-handling pass)
            # leaves quarantine_path=None — no file was moved, so suppress
            # the warning (STALE-2 false quarantine on dry-run).
            if rr.quarantine_path:
                quarantined_paths.append((path_str, qp))

    # P2-3: loud quarantine summary block so users notice their files were moved.
    # Guard: only emit when at least one path was actually quarantined (non-None
    # quarantine_path).  Entries from classify_only=True reconcile passes have
    # quarantine_path=None and are excluded above, so this check is sufficient.
    if quarantined_paths:
        n = len(quarantined_paths)
        print("====================================================================", file=_sys.stderr)
        print(f"WARNING: harness upgrade quarantined {n} user-modified file(s).", file=_sys.stderr)
        print("The new versions have been installed; your modified copies are at:", file=_sys.stderr)
        for _p, _q in quarantined_paths:
            print(f"  {_q}", file=_sys.stderr)
        print("Review with: ls -la .harness/conflicts/", file=_sys.stderr)
        print("====================================================================", file=_sys.stderr)

    # ADR-0002: origin-trust fields removed — dead code for internal tool.


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
    harness_version: str = "0.0.0-dev+unknown",
    quiet: bool = False,
) -> int:
    if not (root / MANIFEST_PATH).exists():
        raise SystemExit("Upgrade must be run from a harness source tree with harness/manifest.json.")
    target = target.resolve()

    # v0.9.11: same preflight as install — skip on dry-run.
    if not dry_run:
        from lib.install import _preflight_target_writable as _preflight
        _preflight(target)

    installed = read_install_state(target)

    # T6 / T4 Pass A: skip-upgrade guard BEFORE any state composition or staging.
    # Only check when we have a version (not a fresh install via adopt_existing).
    if installed.get("version") is not None:
        _check_skip_upgrade_guard(installed, harness_version)

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

    # T4 Pass A: set up staging dir for atomic harness-owned file writes.
    # staging_map maps entry.path -> staged file path.
    # Staged writes are collected and then batch-renamed in Pass B.
    harness_dir = target / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    iso_compact = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    upgrade_runid = f"{os.getpid()}-{iso_compact}-{secrets.token_hex(3)}"
    upgrade_staging_dir = harness_dir / f".staging-{upgrade_runid}"
    upgrade_journal_path = harness_dir / f".staging-{upgrade_runid}.journal.jsonl"
    upgrade_pending_path = harness_dir / f"installed-manifest.json.pending-{upgrade_runid}"
    # staging_map: entry.path -> staged Path (for harness-owned writes)
    upgrade_staging_map: dict[Path, Path] = {}

    if not dry_run:
        upgrade_staging_dir.mkdir(parents=True, exist_ok=True)

    reporter = ProgressReporter(quiet=quiet)
    # v0.9.13: the per-tick `[N/total]` line was misleading — total was the
    # full harness-owned entry count, but STALE-1 short-circuits drop most
    # of those. We now emit a single "staging files..." note and finish with
    # the authoritative count.
    reporter.note("staging files...")
    _stage_count = 0

    for entry in entries:
        if entry.policy not in {"harness-owned", "managed", "managed-append"}:
            continue

        source = source_path(root, entry)
        destination = destination_path(target, entry)

        if entry.policy == "managed-append":
            # FIX-4: managed-append writes happen in Pass A, before the pending
            # sidecar / atomic batch.
            from lib.append_block import plan_managed_append
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

        # v0.9.13: defer file_hash(source) so non-existent destinations skip
        # it. (We still read the destination hash when present because we
        # need it both for user-mod detection AND for STALE-1 comparison —
        # the v0.9.12 contract is "harness-owned files always reset to
        # canonical on upgrade, backing up user edits", which means we can't
        # short-circuit before the user-mod check.)
        new_hash = file_hash(source)
        installed_info = installed_paths.get(str(entry.path), {})

        _force_restage = False
        if destination.exists() and not force:
            old_hash = installed_info.get("sha256")
            current_hash = file_hash(destination)
            if not old_hash or current_hash != old_hash:
                # v0.9.12: harness-owned files are harness-managed. Back up
                # user bytes to .harness/conflicts/<path>.user-backup-<runid>
                # and force re-stage instead of producing a .new conflict.
                if not dry_run:
                    backup_path = (
                        target
                        / ".harness/conflicts"
                        / f"{entry.path}.user-backup-{upgrade_runid}"
                    )
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copyfile(str(destination), str(backup_path))
                    except OSError:
                        pass  # backup is best-effort
                _force_restage = True

            # STALE-1 sync: short-circuit when source is unchanged since
            # install. Skipped when destination was locally modified, else
            # the modified file would silently stay (the silent-skip
            # regression the v0.9.12 auto-overwrite was meant to fix).
            if not _force_restage:
                installed_src_sha = installed_info.get("source_sha256")
                if installed_src_sha and installed_src_sha == new_hash:
                    continue

        planned_writes += 1
        if not dry_run:
            staged = upgrade_staging_dir / entry.path
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(staged))
            upgrade_staging_map[entry.path] = staged
            _stage_count += 1
            installed.setdefault("files", {})[str(entry.path)] = file_state(
                root=root,
                target=target,
                entry=entry,
                source=source,
                staged=staged,
            )

    # v0.9.8: always surface Pass A outcome — authoritative count even when
    # most entries short-circuited (source_sha256 unchanged).
    if _stage_count == 0:
        reporter.note("staging files... no harness-owned files needed restaging")
    else:
        reporter.note(f"staging files... staged {_stage_count} file(s)")

    for path_text, info in list(installed_paths.items()):
        if path_text in current_paths:
            continue
        if not isinstance(info, dict) or info.get("policy") not in {"harness-owned", "managed", "managed-append"}:
            continue
        destination = target / normalize_path(path_text)
        if info.get("policy") == "managed-append":
            from lib.append_block import plan_managed_append_retirement
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
        # FIX-4: retired-file deletion happens in Pass A.
        # v0.9.13: count BEFORE unlink — the prior `if destination.exists()`
        # check ran after unlink and so always saw a missing file, reporting
        # `0 removals` even when files were deleted.
        if destination.exists():
            planned_removals += 1
            if not dry_run:
                destination.unlink()
                remove_empty_parents(destination.parent, target)
                installed.setdefault("files", {}).pop(path_text, None)
        elif not dry_run:
            installed.setdefault("files", {}).pop(path_text, None)

    # M6/#15 — Graveyard: apply upgrade_action for removed_in_version entries.
    # This handles artifacts that were present in old harness versions but no
    # longer ship in the current manifest. The policy map comes from the
    # manifest graveyard so behavior is explicit and version-controlled.
    #
    # Actions:
    #   delete  — harness-owned: delete if present, regardless of modification
    #   warn    — unknown/project-owned: warn and leave (never auto-delete)
    #   ignore  — file is absent or no action needed; skip silently
    #
    # Note: this is NOT the same as the "retired from current manifest"
    # loop above (which handles files that existed in installed_paths but
    # dropped out of current_paths). The graveyard applies to any legacy
    # path that may exist on disk even if the harness never installed it
    # via install_state (e.g. manual copies, pre-adoption files).
    _manifest_data = load_manifest_data(root)
    _graveyard_policy = obsolete_artifact_policy(_manifest_data)
    for _grave_path, _action in sorted(_graveyard_policy.items()):
        # Skip if already handled by the installed-paths retirement loop above.
        if _grave_path in installed_paths and _grave_path not in current_paths:
            continue  # already retired via installed state loop
        _dest = target / normalize_path(_grave_path)
        if not _dest.exists():
            continue  # absent — nothing to do regardless of action
        if _action == "delete":
            planned_removals += 1
            if not dry_run:
                _dest.unlink()
                remove_empty_parents(_dest.parent, target)
                installed.setdefault("files", {}).pop(_grave_path, None)
        elif _action == "warn":
            sys.stderr.write(
                f"WARNING: obsolete harness artifact present but not deleted (policy=warn): {_grave_path}\n"
                f"  Run `rm {_dest}` to remove it manually if it is no longer needed.\n"
            )
        # action == "ignore": do nothing

    if not dry_run:
        normalize_selected_project_owned_state(root=root, target=target, entries=entries, installed=installed)

    installed["version"] = harness_version
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
    # NOTE: sync_roomodes_profile_modes is deferred to Pass B (after atomic batch)
    # because the atomic batch renames .roomodes from staging, which must happen
    # BEFORE the profile-modes sync modifies it. Hash is patched in Pass B.

    # S12 — manifest v2 reconciler pass (§6): stamp installed_sha256,
    # current_sha256, and installed_files_chain_hash onto the installed dict.
    # Backward compat: if prior manifest schema_version < 2, prior_manifest
    # is treated as None (no upgrade history) — reconcile_install handles this.
    release_manifest_v2 = _build_release_manifest_v2(
        root=root,
        entries=entries,
        harness_version=harness_version,
        target=target,
    )
    prior_installed_path = target / INSTALL_STATE
    prior_manifest_v2 = None
    if prior_installed_path.exists():
        # Use read_manifest to enforce §2.4 BOM rejection (→ exit 5) and CRLF
        # normalisation.  Schema mismatch (v1 prior → upgrading to v2) is
        # treated as "no prior v2 history" so the reconciler falls through to
        # fresh-install-after-prior-install mode.
        _raw = prior_installed_path.read_bytes()
        if _raw.startswith(b"\xef\xbb\xbf"):
            # BOM in installed-manifest → hard exit 5 per §2.4
            raise SystemExit(5)
        try:
            prior_manifest_v2 = _read_manifest_v2(prior_installed_path)
        except SystemExit as _se:
            # P5-P1-4: re-raise BOM / parse errors (int exit code 5).
            # Only swallow schema_version mismatch, whose code is a str message.
            if isinstance(_se.code, int):
                raise  # BOM / parse exit 5 — propagate
            # Schema mismatch (e.g. v1 record): treat as no prior v2 history.
            prior_manifest_v2 = None
        except Exception as _e:
            # Unknown failure — warn loudly rather than silently masking.
            sys.stderr.write(
                f"WARNING: prior installed-manifest unreadable: {_e}\n"
            )
            prior_manifest_v2 = None
    # classify_only=True: the existing upgrade conflict logic already handles
    # file moves. The reconciler is used here only for v2 hash classification
    # and field stamping — it must NOT move files a second time.
    reconcile_results = _reconcile_install(
        release_manifest=release_manifest_v2,
        prior_manifest=prior_manifest_v2,
        repo_root=target,
        now_iso=_now_utc(),
        classify_only=True,
    )
    _stamp_installed_manifest_v2(
        installed,
        release_manifest=release_manifest_v2,
        harness_version=harness_version,
        reconcile_results=reconcile_results,
    )

    # T4 Pass B: compute file states for staged harness-owned entries,
    # run atomic batch, write pending sidecar, and finalize.
    #
    # Phase order (mirrors install.py:314-407 per IMPL-PLAN REV-2):
    #   B2: write pending sidecar (pre-batch, for crash durability)
    #   B3: atomic batch rename
    #   B4: sync roomodes (must run after batch landed .roomodes from staging)
    #       + patch roomodes hashes in `installed` dict
    #   B4a: REWRITE pending sidecar with post-sync roomodes hashes so the
    #        sidecar is bit-equal to what the final manifest will contain.
    #        This closes the staleness window identified by Architect C-1/C-2:
    #        a crash between B3 and B5 would leave `_recover_pending_manifest`
    #        finalizing from a sidecar whose .roomodes hashes are pre-sync.
    #   B5: os.replace(pending → final) — atomic finalize (same as install.py:375)
    #   B6: re-read final, assert version
    #   B7: cleanup sentinel, journal, staging dir
    if not dry_run and not (adopting_missing_state and conflicts):
        if upgrade_staging_map:
            # Step B2: write pending sidecar (pre-batch, crash durability).
            # NOTE: roomodes hashes are not yet in `installed` here — they are
            # patched in B4 after the batch lands .roomodes.  B4a rewrites the
            # sidecar with the correct hashes before B5 finalizes via os.replace.
            reporter.note("writing pending sidecar...")
            _atomic_write_json_fsync(upgrade_pending_path, installed)

            # Step B3: atomic batch rename.
            reporter.start("applying atomic batch", len(upgrade_staging_map))
            try:
                batch_result = atomic_install_batch(
                    upgrade_staging_dir,
                    target,
                    upgrade_journal_path,
                    defer_cleanup=True,
                    progress=lambda done, total: reporter.tick(done),
                )
            except CrossFilesystemError:
                # Fallback: copy directly.
                for entry_path, staged_file in upgrade_staging_map.items():
                    entry_dest = target / entry_path
                    entry_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(staged_file), str(entry_dest))
                batch_result = None  # type: ignore[assignment]

            if batch_result is not None and batch_result.aborted:
                raise InstallFailed(
                    f"업그레이드 중단됨 (runid={upgrade_runid}).\n"
                    f"\n"
                    f"복구:\n"
                    f"    python3 scripts/harness.py state repair\n"
                    f"\n"
                    f"[Upgrade aborted (runid={upgrade_runid}).\n"
                    f"\n"
                    f"Recover:\n"
                    f"    python3 scripts/harness.py state repair]"
                )

            # Step B4: sync roomodes AFTER batch (atomic rename landed .roomodes);
            # patch hash in installed dict.
            reporter.note("syncing roomodes...")
            sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
            roomodes_path = target / ".roomodes"
            if (
                roomodes_path.exists()
                and isinstance(installed.get("files"), dict)
                and ".roomodes" in installed["files"]
            ):
                installed["files"][".roomodes"]["sha256"] = file_hash(roomodes_path)
                installed["files"][".roomodes"]["installed_sha256"] = file_hash(roomodes_path)
                installed["files"][".roomodes"]["current_sha256"] = file_hash(roomodes_path)

            # Step B4a: rewrite pending sidecar with post-sync roomodes hashes.
            # The sidecar now contains the FINAL payload — bit-equal to what
            # os.replace will promote to installed-manifest.json in B5.
            _atomic_write_json_fsync(upgrade_pending_path, installed)

            # Step B5: atomic finalize — promote pending sidecar to final manifest.
            # v0.9.13: route through replace_with_retry so a Windows AV/indexer
            # pin on installed-manifest.json gets the same 7.85 s backoff as
            # every other state write, instead of failing the whole upgrade
            # on the first PermissionError.
            reporter.note("finalizing...")
            final_path = target / INSTALL_STATE
            from lib.durable_fs import replace_with_retry as _rwr
            _rwr(str(upgrade_pending_path), str(final_path))

            # Step B6: post-finalize verify (re-read final).
            with open(str(final_path), encoding="utf-8") as fh:
                verify = json.load(fh)
            if verify.get("version") != harness_version:
                raise InstallFailed(
                    f"finalize 검증 실패 (expected={harness_version}, got={verify.get('version')}).\n"
                    f"\n"
                    f"복구:\n"
                    f"    python3 scripts/harness.py state repair\n"
                    f"\n"
                    f"[Finalize verification failed (expected={harness_version}, got={verify.get('version')}).\n"
                    f"\n"
                    f"Recover:\n"
                    f"    python3 scripts/harness.py state repair]"
                )

            # Step B7: cleanup sentinel, journal, staging dir.
            # (Pending sidecar was promoted to final in B5 — no separate unlink needed.)
            sentinel_path = harness_dir / f".staging-{upgrade_runid}.complete"
            try:
                sentinel_path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                upgrade_journal_path.unlink(missing_ok=True)
            except OSError:
                pass
            _rmdir_recursive_quiet(upgrade_staging_dir)
        else:
            # No harness-owned files to stage: sync roomodes, clean up staging, write manifest.
            sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
            roomodes_path = target / ".roomodes"
            if (
                roomodes_path.exists()
                and isinstance(installed.get("files"), dict)
                and ".roomodes" in installed["files"]
            ):
                installed["files"][".roomodes"]["sha256"] = file_hash(roomodes_path)
            _rmdir_recursive_quiet(upgrade_staging_dir)
            write_json(target / INSTALL_STATE, installed)

    elif not dry_run and (adopting_missing_state and conflicts):
        # Conflict path: no writes, clean up staging dir.
        _rmdir_recursive_quiet(upgrade_staging_dir)

    if not dry_run:
        # v0.9.8: explicit stdout summary so operators can tell upgrade
        # completed (mirrors install.py:435). Empty stdout was being read
        # as "hang" on Windows/PowerShell where stderr buffering differs.
        print(
            f"upgraded harness → v{harness_version} at {target} "
            f"({planned_writes} writes, {planned_removals} removals, {conflicts} conflicts). "
            f"Next: cd {target} && python3 scripts/harness.py check"
        )

    if dry_run:
        print("upgrade dry-run")
        print(f"target={target}")
        print(f"source={root.resolve()}")
        print(f"version={harness_version}")
        print("adapters=" + ",".join(sorted(adapters)))
        print("profiles=" + ",".join(sorted(profiles)))
        print("packs=" + ",".join(sorted(packs)))
        print(f"planned_writes={planned_writes}")
        print(f"planned_removals={planned_removals}")
        print(f"conflicts={conflicts}")
        for path in conflict_paths:
            print(f"conflict={path}")
        print("no mutation performed")
        # v0.9.10: print the exact command to run for-real (drop --dry-run).
        _cmd = (
            f"python3 scripts/harness.py upgrade --target {target} "
            f"--adapters {','.join(sorted(adapters))} "
            f"--profiles {','.join(sorted(profiles))}"
        )
        if packs:
            _cmd += f" --packs {','.join(sorted(packs))}"
        if force:
            _cmd += " --force"
        if adopt_existing:
            _cmd += " --adopt-existing"
        print(f"To execute for real: {_cmd}")
    return 1 if conflicts else 0
