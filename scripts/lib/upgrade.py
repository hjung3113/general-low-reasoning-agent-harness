"""Upgrade flow: migrate legacy install state, re-apply manifest."""
from __future__ import annotations

import copy
import json
import os
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
from lib.exitcodes import EXIT_RELEASE_TRUST_INVALID
from lib.release_trust import UpgradeTrustError, file_sha256_at_commit, verify_release_tag
from lib.manifest_reconciler import (
    ReconcileDecision,
    compute_manifest_hash_chain,
    reconcile_install as _reconcile_install,
    verify_manifest_chain as _verify_manifest_chain,
)
from lib.manifest_v2 import read_manifest as _read_manifest_v2
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


def _read_target_trust_origin(target: Path) -> str | None:
    """Return trust_origin from the target's existing installed manifest, or None.

    δ-P1-1: distinguishes "file absent" (returns None) from "file present but
    unparseable / missing keys" (raises UpgradeTrustError with
    sub_reason="target_manifest_corrupted").  A corrupted install-state.json
    must NOT silently mask a prior signed_tag install and allow a downgrade.

    B3-Fix-1: When installed_files_chain_hash is present and trust fields
    (trust_origin, release_tag, release_commit) are present, verify the chain
    hash to detect tampering. Old v1 records without the hash field are accepted
    without chain verification (backward compatibility).
    """
    from lib.state import INSTALL_STATE as _IS  # avoid circular at module level
    from lib.release_trust import UpgradeTrustError as _UTE  # local import — avoid circular
    p = target / _IS
    if not p.exists():
        return None
    # File is present — parse it.  Any failure here is suspicious (corruption /
    # tampering) and must be reported rather than silently swallowed.
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise _UTE(
            "target_manifest_corrupted",
            f"install-state.json unreadable: {exc}",
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _UTE(
            "target_manifest_corrupted",
            f"install-state.json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise _UTE(
            "target_manifest_corrupted",
            "install-state.json top-level value is not a JSON object",
        )
    # B3-Fix-1: Verify chain hash when present to detect tampering with trust fields.
    # Only verify when ALL trust provenance fields are present — old records written
    # before this fix have trust_origin stamped AFTER the chain hash was computed
    # (without trust fields), so their chain hash won't match the new format.
    # We detect new-format records by the presence of release_tag AND release_commit
    # alongside trust_origin (these are only stamped by _stamp_installed_manifest_v2
    # and _stamp_install_trust_origin which ALSO include trust fields in the hash).
    stored_chain_hash = data.get("installed_files_chain_hash")
    has_trust_provenance = (
        data.get("trust_origin") is not None
        and "release_tag" in data
        and "release_commit" in data
    )
    if stored_chain_hash and has_trust_provenance:
        installed_files: dict = data.get("files", {})
        recomputed_chain_manifest: dict = {
            "release_commit": data.get("release_commit"),
            "release_tag": data.get("release_tag"),
            "schema_version": data.get("schema_version", 2),
            "harness_version": data.get("harness_version", ""),
            "files": {
                p_str: {
                    "installed_sha256": v.get("installed_sha256", ""),
                    "current_sha256": v.get("current_sha256", ""),
                }
                for p_str, v in installed_files.items()
                if isinstance(v, dict) and "installed_sha256" in v
            },
            "removed_in_version": [],
            "trust_origin": data.get("trust_origin"),
        }
        expected_hash = compute_manifest_hash_chain(recomputed_chain_manifest)
        if expected_hash != stored_chain_hash:
            raise _UTE(
                "target_manifest_corrupted",
                f"install-state.json chain hash mismatch — possible tampering. "
                f"Expected {expected_hash!r}, stored {stored_chain_hash!r}",
            )
    # trust_origin may legitimately be absent (old v1 records) — that's fine.
    return data.get("trust_origin")


def _emit_trust_audit(
    verb: str,
    *,
    target: Path | None,
    **kwargs: object,
) -> None:
    """Emit a release.trust.* audit row to the target's audit log.

    Uses the existing audit_append pattern.  If target is None or the audit
    subsystem is unavailable, silently skips (audit is best-effort for trust
    events — the error path already exits 17).
    """
    import datetime as _dt
    try:
        from lib.audit import audit_append as _audit_append
    except ImportError:
        return
    if target is None:
        return
    audit_path = target / ".harness" / "audit.log"
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry: dict = {"verb": verb, "at": now, "args": dict(kwargs)}
    try:
        _audit_append(entry, audit_path=audit_path)
    except Exception:
        pass  # audit is best-effort; never let it abort the upgrade


def _build_release_manifest_v2(
    *,
    root: Path,
    entries: list,
    harness_version: str,
    target: Path | None = None,
) -> dict:
    """Build a release_manifest dict in installed-manifest v2 format for the reconciler.

    SSH-signed-tag trust root (§6, Group δ):
    ─────────────────────────────────────────
    For release builds (harness_version is a clean MAJOR.MINOR.PATCH string):
      1. Trust-downgrade guard: if the *target*'s existing manifest already has
         ``trust_origin: signed_tag`` and the new build would produce
         ``trust_origin: dev_unsigned``, raise UpgradeTrustError immediately.
      2. Attempt ``verify_release_tag(root, "v<version>")``.
         On success: bind all reads to the verified commit SHA via
         ``file_sha256_at_commit`` — the working tree is never consulted.
         Emit ``trust_origin: "signed_tag"`` in the manifest.
         Emit ``release.trust.verified`` audit row.
      3. On UpgradeTrustError("tag_signature_invalid"):
         - Check env var ``HARNESS_ALLOW_UNSIGNED_DEV=1``.
         - If set AND target has no signed_tag trust yet:
             - If a target manifest exists (any trust_origin): require y/N TTY
               confirmation unless HARNESS_BYPASS_TTY_CONFIRM=1.
             - Fall through to working-tree reads with ``trust_origin:
               "dev_unsigned"`` + stderr WARNING.
             - Emit ``release.trust.bypassed`` audit row.
         - Otherwise: emit ``release.trust.refused`` + raise SystemExit(EXIT_RELEASE_TRUST_INVALID).

    For dev builds (``0.0.0-dev+…`` pattern): skip verification, emit
    ``trust_origin: "dev_unsigned"`` immediately (working-tree path).
    """
    tag: str | None = None
    commit_sha: str | None = None
    trust_origin: str
    is_dev_version = (
        harness_version.startswith("0.0.0-dev+")
        or harness_version == "0.0.0-dev+unknown"
        or harness_version.endswith(".dev0")
    )

    allow_unsigned = os.environ.get("HARNESS_ALLOW_UNSIGNED_DEV", "") == "1"

    # ── Early trust-downgrade guard ─────────────────────────────────────────
    # If the target's existing manifest is already signed_tag and the new build
    # would be dev_unsigned, refuse immediately — before any file access.
    # δ-P1-1: _read_target_trust_origin now raises UpgradeTrustError on
    # corruption rather than silently returning None.
    existing_trust_origin = _read_target_trust_origin(target) if target is not None else None
    if is_dev_version or allow_unsigned:
        # Might end up as dev_unsigned; check downgrade now.
        if existing_trust_origin == "signed_tag":
            _emit_trust_audit(
                "release.trust.refused",
                target=target,
                sub_reason="trust_downgrade_refused",
                target_path=str(target) if target else None,
            )
            _te_downgrade = UpgradeTrustError(
                "trust_downgrade_refused",
                "target manifest already has trust_origin=signed_tag; "
                "refusing downgrade to dev_unsigned. "
                "Unset HARNESS_ALLOW_UNSIGNED_DEV or use a signed release tag.",
            )
            # B3-Fix-2: emit SystemExit with the constant exit code, not a bare
            # UpgradeTrustError that may propagate silently.
            raise SystemExit(_te_downgrade.exit_code) from _te_downgrade

    if is_dev_version:
        # Dev checkout: working-tree path without tag verification.
        trust_origin = "dev_unsigned"
    else:
        # Release build: attempt SSH-signed-tag verification.
        tag = "v" + harness_version
        try:
            commit_sha = verify_release_tag(root, tag)
            trust_origin = "signed_tag"
            # δ-P1-2: emit release.trust.verified on success.
            _emit_trust_audit(
                "release.trust.verified",
                target=target,
                release_tag=tag,
                release_commit=commit_sha,
                target_path=str(target) if target else None,
            )
        except UpgradeTrustError as _te:
            # tag_not_found counts as tag_signature_invalid for bypass purposes.
            if _te.sub_reason in ("tag_signature_invalid", "tag_not_found"):
                if allow_unsigned and existing_trust_origin != "signed_tag":
                    # δ-P1-4: TTY confirmation when a target manifest already exists.
                    # This ensures the operator is aware they are bypassing trust.
                    target_manifest_exists = existing_trust_origin is not None
                    bypass_tty_confirm = (
                        os.environ.get("HARNESS_BYPASS_TTY_CONFIRM", "") == "1"
                    )
                    if target_manifest_exists and not bypass_tty_confirm:
                        import sys as _sys_tty
                        if not _sys_tty.stdin.isatty():
                            _emit_trust_audit(
                                "release.trust.refused",
                                target=target,
                                sub_reason="bypass_requires_tty_confirm",
                                target_path=str(target) if target else None,
                            )
                            raise SystemExit(EXIT_RELEASE_TRUST_INVALID) from UpgradeTrustError(
                                "bypass_requires_tty_confirm",
                                "HARNESS_ALLOW_UNSIGNED_DEV bypass requested but stdin is "
                                "not a TTY and HARNESS_BYPASS_TTY_CONFIRM is not set. "
                                "Refuse for safety.",
                            )
                        _sys_tty.stderr.write(
                            "Trust-root bypass requested. Continue? [y/N] "
                        )
                        _sys_tty.stderr.flush()
                        try:
                            answer = input()
                        except EOFError:
                            answer = ""
                        import re as _re
                        if not _re.match(r"^[Yy]$", answer.strip()):
                            _emit_trust_audit(
                                "release.trust.refused",
                                target=target,
                                sub_reason="bypass_requires_tty_confirm",
                                target_path=str(target) if target else None,
                            )
                            raise SystemExit(EXIT_RELEASE_TRUST_INVALID) from UpgradeTrustError(
                                "bypass_requires_tty_confirm",
                                "User declined TTY confirmation for HARNESS_ALLOW_UNSIGNED_DEV bypass.",
                            )
                    # Bypass accepted — warn and proceed.
                    sys.stderr.write(
                        f"WARNING: HARNESS_ALLOW_UNSIGNED_DEV=1 — skipping SSH tag "
                        f"verification for {tag!r} ({_te.sub_reason}). "
                        f"trust_origin will be dev_unsigned.\n"
                    )
                    trust_origin = "dev_unsigned"
                    commit_sha = None
                    # δ-P1-2: emit release.trust.bypassed audit row.
                    _emit_trust_audit(
                        "release.trust.bypassed",
                        target=target,
                        reason=_te.sub_reason,
                        target_path=str(target) if target else None,
                    )
                else:
                    _emit_trust_audit(
                        "release.trust.refused",
                        target=target,
                        sub_reason=_te.sub_reason,
                        target_path=str(target) if target else None,
                    )
                    raise SystemExit(EXIT_RELEASE_TRUST_INVALID) from _te
            else:
                # trust_downgrade_refused or unknown — propagate directly.
                # Audit row already emitted above for trust_downgrade_refused.
                raise

    # ── Compute file hashes ─────────────────────────────────────────────────
    files: dict[str, object] = {}
    for entry in entries:
        if entry.policy == "exclude":
            continue
        if trust_origin == "signed_tag" and commit_sha is not None:
            # Bind read to the verified commit SHA — working tree is NOT consulted.
            try:
                sha = file_sha256_at_commit(root, commit_sha, str(entry.path))
            except UpgradeTrustError:
                # File absent from signed tree — skip (conditional content).
                continue
        else:
            # dev_unsigned path: fall back to working-tree read.
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
        "trust_origin": trust_origin,
        "release_tag": tag,
        "release_commit": commit_sha,
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
            quarantined_paths.append((path_str, qp))

    # P2-3: loud quarantine summary block so users notice their files were moved
    if quarantined_paths:
        n = len(quarantined_paths)
        print("====================================================================", file=_sys.stderr)
        print(f"WARNING: harness upgrade quarantined {n} user-modified file(s).", file=_sys.stderr)
        print("The new versions have been installed; your modified copies are at:", file=_sys.stderr)
        for _p, _q in quarantined_paths:
            print(f"  {_q}", file=_sys.stderr)
        print("Review with: ls -la .harness/conflicts/", file=_sys.stderr)
        print("====================================================================", file=_sys.stderr)

    # B3-Fix-1: persist trust provenance fields so subsequent upgrades can
    # read back trust_origin and enforce downgrade protection, and so chain
    # hash covers these fields (tampering is chain-hash-detected).
    for key in ("trust_origin", "release_tag", "release_commit"):
        if key in release_manifest:
            installed[key] = release_manifest[key]

    # Compute and stamp installed_files_chain_hash
    # B3-Fix-1: include trust_origin, release_tag, release_commit in canonical
    # input so tampering with any of these fields is chain-hash-detected.
    chain_manifest: dict[str, object] = {
        "release_commit": installed.get("release_commit"),
        "release_tag": installed.get("release_tag"),
        "schema_version": 2,
        "harness_version": harness_version,
        "files": {
            p: {"installed_sha256": v.get("installed_sha256", ""), "current_sha256": v.get("current_sha256", "")}
            for p, v in installed_files.items()
            if isinstance(v, dict) and "installed_sha256" in v
        },
        "removed_in_version": [],
        "trust_origin": installed.get("trust_origin"),
    }
    installed["installed_files_chain_hash"] = compute_manifest_hash_chain(chain_manifest)


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
    # current_sha256, and installed_files_chain_hash onto the installed dict.
    # Backward compat: if prior manifest schema_version < 2, prior_manifest
    # is treated as None (no upgrade history) — reconcile_install handles this.
    try:
        release_manifest_v2 = _build_release_manifest_v2(
            root=root,
            entries=entries,
            harness_version=harness_version,
            target=target,
        )
    except UpgradeTrustError as _ute:
        # B3-Fix-2: bare UpgradeTrustError (e.g. target_manifest_corrupted from
        # _read_target_trust_origin) must become SystemExit, not an unhandled
        # exception that produces a confusing traceback.
        _emit_trust_audit(
            "release.trust.refused",
            target=target,
            sub_reason=_ute.sub_reason,
            detail=str(_ute),
        )
        raise SystemExit(_ute.exit_code) from _ute
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
        if prior_manifest_v2 is not None:
            # P5-P1-3: verify chain hash on read (§6 manifest integrity).
            # Upgrade treats a chain mismatch as a WARNING (not hard stop) —
            # the prior manifest may be a legacy record from an older harness
            # that did not stamp installed_files_chain_hash.  Upgrade will
            # re-stamp a correct chain hash when it writes the new manifest.
            # Hard stop (ManifestChainTamperedError exit 5) is enforced by
            # check.py and install.py on the CURRENT installed target.
            from lib.manifest_reconciler import ManifestChainTamperedError as _MCTE
            try:
                _verify_manifest_chain(prior_manifest_v2)
            except _MCTE as _ce:
                sys.stderr.write(
                    f"WARNING: prior installed-manifest chain hash mismatch "
                    f"(possible tampering or legacy record). Upgrade proceeds "
                    f"and will re-stamp hash. Detail: {_ce}\n"
                )
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
