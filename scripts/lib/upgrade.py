"""Upgrade flow: migrate legacy install state, re-apply manifest."""
from __future__ import annotations

import copy
import json
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
    select_entries,
    validate_scope_names,
    source_path,
    destination_path,
    selected_pack_metadata,
)
from lib.profiles import LEGACY_PROFILE_ALIASES, normalize_profiles
from lib.roadmap_state import normalize_path
from lib.state import (
    INSTALL_STATE,
    read_install_state,
    scope_record,
    write_install_state,
    write_json,
    installed_scope,
    available_scopes,
    file_hash,
    file_state,
    manifest_sha256,
)
from lib.version import (
    repo_root,
    resolve_harness_version,
    source_provenance,
)
# S12 — manifest v2 reconciler (§6)
from lib.manifest_reconciler import (
    ReconcileDecision,
    compute_manifest_hash_chain,
    reconcile_install as _reconcile_install,
)
from lib.state import now_utc as _now_utc


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
) -> dict:
    """Build a release_manifest dict in installed-manifest v2 format for the reconciler.

    For each entry compute ``installed_sha256`` from the source file in *root*.
    ``current_sha256`` mirrors ``installed_sha256`` (the release is the new truth).
    Backward compat: if a source file is missing (e.g. conditional content), skip it.
    """
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
    - ``manifest_chain_hash`` (computed over the final installed dict)

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
            entry_info["quarantine_path"] = rr.quarantine_path or ""
            print(
                f"WARN: {path_str} diverged from release — moved to {rr.quarantine_path}. "
                "Release version installed.",
                file=_sys.stderr,
            )

    # Compute and stamp manifest_chain_hash
    chain_manifest: dict[str, object] = {
        "schema_version": 2,
        "harness_version": harness_version,
        "files": {
            p: {"installed_sha256": v.get("installed_sha256", ""), "current_sha256": v.get("current_sha256", "")}
            for p, v in installed_files.items()
            if isinstance(v, dict) and "installed_sha256" in v
        },
        "removed_in_version": [],
    }
    installed["manifest_chain_hash"] = compute_manifest_hash_chain(chain_manifest)


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
) -> int:
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
            from lib.append_block import plan_managed_append, plan_managed_append_retirement
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
        if not dry_run:
            if destination.exists():
                destination.unlink()
                remove_empty_parents(destination.parent, target)
                installed.setdefault("files", {}).pop(path_text, None)
        if destination.exists():
            planned_removals += 1

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
    if not dry_run:
        sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
        roomodes_path = target / ".roomodes"
        if roomodes_path.exists() and isinstance(installed.get("files"), dict) and ".roomodes" in installed["files"]:
            installed["files"][".roomodes"]["sha256"] = file_hash(roomodes_path)

    # S12 — manifest v2 reconciler pass (§6): stamp installed_sha256,
    # current_sha256, and manifest_chain_hash onto the installed dict.
    # Backward compat: if prior manifest schema_version < 2, prior_manifest
    # is treated as None (no upgrade history) — reconcile_install handles this.
    release_manifest_v2 = _build_release_manifest_v2(
        root=root,
        entries=entries,
        harness_version=harness_version,
    )
    prior_installed_path = target / INSTALL_STATE
    prior_manifest_v2 = None
    if prior_installed_path.exists():
        try:
            import json as _json
            _raw = prior_installed_path.read_bytes()
            if not _raw.startswith(b"\xef\xbb\xbf"):  # skip BOM files
                prior_manifest_v2 = _json.loads(_raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        except Exception:
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

    if not dry_run and not (adopting_missing_state and conflicts):
        write_json(target / INSTALL_STATE, installed)
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
    return 1 if conflicts else 0
