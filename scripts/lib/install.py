"""Install flow: copy files, plan managed appends, sync roomodes, write install state."""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from lib.adoption import assert_safe_write_destination
from lib.append_block import (
    plan_managed_append,
    write_managed_append,
)
from lib.manifest import (
    MANIFEST_PATH,
    ManifestEntry,
    load_manifest,
    select_entries,
    source_path,
    destination_path,
    validate_managed_append_destinations,
    validate_scope_names,
    selected_pack_metadata,
)
from lib.profiles import default_packs_for_profile, normalize_profiles, db_packs
from lib.state import (
    INSTALL_STATE,
    scope_record,
    delegated_source_provenance,
    write_install_state,
    write_json,
    now_utc,
    file_hash,
    file_state,
    manifest_sha256,
    sha256_text,
)
from lib.version import (
    repo_root,
    resolve_harness_version,
    git_source_provenance,
    source_provenance,
)

# ---------------------------------------------------------------------------
# Install-record bootstrap (T7 / NEW-1)
# ---------------------------------------------------------------------------

INSTALL_RECORD_NAME = "install-record.json"
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_approver_email(raw: str) -> str:
    """Sanitize a candidate approver email (codex M-6).

    - Trim ASCII whitespace; reject empty; reject control chars; lowercase.
    """
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("approver email is empty after whitespace trim")
    if len(trimmed.splitlines()) > 1:
        raise ValueError(f"approver email contains multiple lines: {raw!r}")
    if _CONTROL_CHAR_RE.search(trimmed):
        raise ValueError(f"approver email contains control characters: {raw!r}")
    return trimmed.lower()


def resolve_approver_email(
    *,
    cli_flag: "str | None" = None,
    env: "dict | None" = None,
    root: "Path | None" = None,
) -> "tuple[str, str]":
    """Resolve bootstrap approver email using priority chain.

    Priority: (1) cli_flag, (2) HARNESS_INSTALL_APPROVER env, (3) git config user.email.
    Returns ``(lowercased_email, bootstrap_source)``.
    Raises ``SystemExit`` if all sources empty/invalid.
    """
    _env = env if env is not None else os.environ

    if cli_flag is not None:
        try:
            return _sanitize_approver_email(cli_flag), "cli-flag"
        except ValueError as exc:
            raise SystemExit(
                f"error: --approver-email invalid: {exc}\n"
                "Fix: provide a valid email address with --approver-email."
            ) from exc

    env_val = _env.get("HARNESS_INSTALL_APPROVER", "")
    if env_val:
        try:
            return _sanitize_approver_email(env_val), "env"
        except ValueError as exc:
            raise SystemExit(
                f"error: HARNESS_INSTALL_APPROVER invalid: {exc}\n"
                "Fix: set HARNESS_INSTALL_APPROVER to a valid email address."
            ) from exc

    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=2.0,
            cwd=str(root) if root else None,
        )
        if result.returncode == 0:
            git_email = result.stdout.strip()
            if git_email:
                try:
                    return _sanitize_approver_email(git_email), "git-config"
                except ValueError:
                    pass
    except (OSError, subprocess.SubprocessError):
        pass

    raise SystemExit(
        "error: harness init refused: cannot determine approver email.\n"
        "Provide one of:\n"
        "  --approver-email <addr>          (CLI flag)\n"
        "  HARNESS_INSTALL_APPROVER=<addr>  (environment variable)\n"
        "  git config user.email            (git config)"
    )


def write_install_record(
    *,
    target: Path,
    approver_email: str,
    bootstrap_source: str,
    harness_version: str,
    root: Path,
) -> None:
    """Write .harness/install-record.json and append audit row.

    Idempotent: if the file already exists, logs advisory and returns.
    """
    from lib.atomic_io import atomic_write_text
    from lib.audit import audit_append

    harness_dir = target / ".harness"
    record_path = harness_dir / INSTALL_RECORD_NAME
    audit_path = harness_dir / "audit.log"

    if record_path.exists():
        sys.stderr.write(
            f"advisory: install-record already exists at {record_path}; "
            "preserving existing approvers (install_record.preexisting).\n"
        )
        return

    commit_sha, tag_val, is_dirty = "", "", False
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2.0, cwd=str(root),
        )
        if r.returncode == 0:
            commit_sha = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(
            ["git", "describe", "--exact-match", "--tags", "HEAD"],
            capture_output=True, text=True, timeout=2.0, cwd=str(root),
        )
        if r.returncode == 0:
            tag_val = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=2.0, cwd=str(root),
        )
        if r.returncode == 0:
            is_dirty = bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record: dict = {
        "schema_version": 1,
        "harness_version": harness_version,
        "installed_at_iso": now_iso,
        "bootstrap_source": bootstrap_source,
        "approvers": [
            {"email": approver_email, "added_at": now_iso, "source": "bootstrap"},
        ],
        "source_provenance": {"commit": commit_sha, "tag": tag_val, "dirty": is_dirty},
    }

    harness_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(record_path, json.dumps(record, indent=2, sort_keys=True) + "\n")

    try:
        audit_append(
            {
                "verb": "install_record.bootstrap",
                "at": now_iso,
                "actor": approver_email,
                "args": {"bootstrap_source": bootstrap_source, "approver_count": 1},
            },
            audit_path=audit_path,
        )
    except Exception:
        pass  # audit failure is non-fatal


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
    adapters: "set[str] | None" = None,
    profiles: "set[str] | None" = None,
    packs: "set[str] | None" = None,
    harness_version: str = "0.0.0-dev+unknown",
    approver_email: "str | None" = None,
    approver_bootstrap_source: "str | None" = None,
) -> None:
    # P5-P1-3: verify prior installed-manifest chain hash before any install
    # decision (§6 integrity). Raises ManifestChainTamperedError (exit 5) if
    # the chain hash has been tampered. Returns False for fresh installs.
    from lib.manifest_reconciler import verify_install_record_integrity as _vir
    _vir(target.resolve() if hasattr(target, 'resolve') else Path(target).resolve())

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
        raise SystemExit(
            "Refusing to overwrite existing files during init:\n  "
            + "\n  ".join(existing)
            + "\nHint: pick an empty target directory, or remove these files first."
        )

    if dry_run:
        print("init dry-run")
        print(f"target={target}")
        print(f"source={root.resolve()}")
        print(f"version={harness_version}")
        print("adapters=" + ",".join(sorted(adapters)))
        print("profiles=" + ",".join(sorted(profiles)))
        print("packs=" + ",".join(sorted(packs)))
        # STALE-1 sync: on fresh init ALL non-exclude entries are written
        # (project-owned scaffold files don't exist yet; managed-append blocks
        # are always injected on first install).  upgrade.py uses a narrower
        # counter that skips project-owned and managed-append-with-no-change.
        # The two numbers are intentionally different: init counts "files
        # touched in this operation" while upgrade counts "harness-managed
        # files overwritten".  See stale1-trace.md §3 for the full analysis.
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

    # B3-Fix-3: stamp trust_origin on fresh install so subsequent upgrades can
    # enforce downgrade protection. Without this, trust_origin is absent from
    # the install record and upgrades silently accept dev_unsigned downgrades.
    _stamp_install_trust_origin(
        root=root,
        target=target,
        harness_version=harness_version,
    )

    # T7 / NEW-1: write .harness/install-record.json so `phase approve` works immediately.
    if approver_email is not None and approver_bootstrap_source is not None:
        write_install_record(
            target=target,
            approver_email=approver_email,
            bootstrap_source=approver_bootstrap_source,
            harness_version=harness_version,
            root=root,
        )

    print(f"installed harness v{harness_version} → {target} ({len(destinations)} planned writes). Next: cd {target} && python3 scripts/harness.py check")


def _stamp_install_trust_origin(
    *,
    root: Path,
    target: Path,
    harness_version: str,
) -> None:
    """B3-Fix-3: stamp trust_origin/release_tag/release_commit on the fresh install record.

    For release builds: calls verify_release_tag; on success stamps trust_origin=signed_tag.
    For dev builds (0.0.0-dev+...): stamps trust_origin=dev_unsigned immediately.
    On verification failure: stamps trust_origin=dev_unsigned if HARNESS_ALLOW_UNSIGNED_DEV=1,
    otherwise exits with EXIT_RELEASE_TRUST_INVALID to fail closed.
    """
    import os as _os
    from lib.state import INSTALL_STATE, write_json, read_install_state
    from lib.manifest_reconciler import compute_manifest_hash_chain

    is_dev_version = (
        harness_version.startswith("0.0.0-dev+")
        or harness_version == "0.0.0-dev+unknown"
        or harness_version.endswith(".dev0")
    )

    trust_origin: str
    release_tag: str | None = None
    release_commit: str | None = None

    if is_dev_version:
        trust_origin = "dev_unsigned"
    else:
        from lib.release_trust import UpgradeTrustError, verify_release_tag
        from lib.exitcodes import EXIT_RELEASE_TRUST_INVALID
        tag = "v" + harness_version
        allow_unsigned = _os.environ.get("HARNESS_ALLOW_UNSIGNED_DEV", "") == "1"
        try:
            release_commit = verify_release_tag(root, tag)
            release_tag = tag
            trust_origin = "signed_tag"
        except UpgradeTrustError as _te:
            # tag_not_found means this is not an actual release tag (e.g. dev/test
            # version string) — stamp dev_unsigned without blocking.
            if _te.sub_reason == "tag_not_found" or allow_unsigned:
                trust_origin = "dev_unsigned"
                if _te.sub_reason != "tag_not_found":
                    sys.stderr.write(
                        f"WARNING: HARNESS_ALLOW_UNSIGNED_DEV=1 — install trust_origin=dev_unsigned "
                        f"for {tag!r}.\n"
                    )
            else:
                sys.stderr.write(
                    f"ERROR: SSH tag verification failed for {tag!r} ({_te.sub_reason}). "
                    f"Set HARNESS_ALLOW_UNSIGNED_DEV=1 to bypass (dev installs only).\n"
                )
                # B-5 (Cycle-2): preserve original exception context on the SystemExit.
                raise SystemExit(EXIT_RELEASE_TRUST_INVALID) from _te

    # Patch the trust fields into the freshly-written install state record.
    # B-4 (Cycle-2): strict — re-raise on failure so install fails loudly rather
    # than silently leaving a manifest with no trust stamping.  Silent bypass is
    # unacceptable for internal-share-stable.
    install_state_path = target / INSTALL_STATE
    state: dict = read_install_state(target)
    state["trust_origin"] = trust_origin
    if release_tag is not None:
        state["release_tag"] = release_tag
    if release_commit is not None:
        state["release_commit"] = release_commit
    # Re-compute chain hash to include the new trust fields.
    files_dict: dict = state.get("files", {})
    chain_manifest: dict = {
        "release_commit": state.get("release_commit"),
        "release_tag": state.get("release_tag"),
        "schema_version": state.get("schema_version", 2),
        "harness_version": state.get("harness_version", harness_version),
        "files": {
            p: {
                "installed_sha256": v.get("installed_sha256", ""),
                "current_sha256": v.get("current_sha256", ""),
            }
            for p, v in files_dict.items()
            if isinstance(v, dict) and "installed_sha256" in v
        },
        "removed_in_version": [],
        "trust_origin": trust_origin,
    }
    state["installed_files_chain_hash"] = compute_manifest_hash_chain(chain_manifest)
    write_json(install_state_path, state)

    # B-4 (Cycle-2): emit release.trust.bypassed audit row when trust_origin=dev_unsigned
    # at install time (symmetric with upgrade path — forensic visibility).
    if trust_origin == "dev_unsigned":
        try:
            import datetime as _dt
            from lib.audit import audit_append as _aa
            _audit_path = target / ".harness" / "audit.log"
            _aa(
                {
                    "verb": "release.trust.bypassed",
                    "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "args": {
                        "bypass_source": "install_path",
                        "reason": "tag_not_found" if not release_tag else "tag_signature_invalid",
                    },
                },
                audit_path=_audit_path,
            )
        except Exception:
            pass  # audit failure is non-fatal


def write_copy(source: Path, destination: Path) -> None:
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def write_text_file(destination: Path, text: str) -> None:
    # NOTE (T0-A, deliberate exclusion): this writer targets SKILL-pack
    # content (user-facing files installed from harness/manifest.json),
    # NOT paths in STATE_FILE_PATHS / OPERATIONAL_PATHS / INSTALL_PATHS
    # per scripts/lib/operational_paths.py. The T0-A atomic-write grep
    # gate (scripts/test_atomic_io.py) explicitly excludes these
    # destinations because (a) they are user-content overwrites, not
    # operational/state writes, and (b) the conflict-detection path
    # already produces a `.new` sidecar for any divergence so partial
    # writes are recoverable. If a future commit retargets this helper
    # at a managed state path, the grep gate WILL fail and the call
    # must move to lib.atomic_io.atomic_write_text.
    # See .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md task 16.
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def write_text_conflict(target: Path, path_text: str, content: str) -> None:
    from lib.roadmap_state import normalize_path
    destination = target / ".harness/conflicts" / normalize_path(path_text)
    write_text_file(destination, content)


def remove_empty_parents(path: Path, stop: Path) -> None:
    from lib.worktree import is_relative_to
    stop = stop.resolve()
    current = path.resolve()
    while current != stop and is_relative_to(current, stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
