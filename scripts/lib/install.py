"""Install flow: copy files, plan managed appends, sync roomodes, write install state."""
from __future__ import annotations

import datetime
import json
import os
import re
import secrets
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
    build_install_state_payload,
    write_install_state,
    write_json,
    now_utc,
    file_hash,
    file_state,
    manifest_sha256,
    sha256_text,
)
from lib.atomic_io import atomic_install_batch, CrossFilesystemError
from lib.progress import ProgressReporter
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
    """Resolve bootstrap approver email — never fails.

    v0.9.9: this is an internal single-user dev tool (see memory
    feedback_internal_only_threat_model). The approver email used to be a
    hard requirement that refused init when no source was available — that
    was workflow theater, not security. Now this returns a best-effort
    identity and never raises.

    Priority:
      1. ``cli_flag``                       → source = "cli-flag"
      2. ``git config user.email``          → source = "git-config"
      3. ``<getpass.getuser>@<hostname>``   → source = "auto"
      4. ``"local@harness"`` constant       → source = "auto"

    Invalid CLI values fall through to the next source instead of aborting.
    """
    _env = env if env is not None else os.environ

    if cli_flag is not None:
        try:
            return _sanitize_approver_email(cli_flag), "cli-flag"
        except ValueError:
            pass  # v0.9.9: invalid flag → fall through

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

    try:
        import getpass as _gp
        import socket as _sk
        user = _gp.getuser() or "user"
        host = _sk.gethostname() or "localhost"
        candidate = f"{user}@{host}".lower()
        try:
            return _sanitize_approver_email(candidate), "auto"
        except ValueError:
            pass
    except Exception:
        pass

    return "local@harness", "auto"


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
        "schema_version": 2,
        "harness_version": harness_version,
        "installed_at_iso": now_iso,
        "bootstrap_source": bootstrap_source,
        "installer_email": approver_email,
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
    quiet: bool = False,
    force: bool = False,
) -> None:
    # P5-P1-3: verify prior installed-manifest chain hash before any install
    # decision (§6 integrity). Raises ManifestChainTamperedError (exit 5) if
    # the chain hash has been tampered. Returns False for fresh installs.
    from lib.manifest_reconciler import verify_install_record_integrity as _vir
    _vir(target.resolve() if hasattr(target, 'resolve') else Path(target).resolve())

    adapters = adapters if adapters is not None else {"roo"}
    profiles = profiles if profiles is not None else {"generic"}
    packs = packs if packs is not None else set()

    # v0.9.11: preflight write-test on target before any real work. Skipped
    # on dry-run so it does not pollute the target with .harness/.
    if not dry_run:
        _resolved_target = target.resolve() if hasattr(target, "resolve") else Path(target).resolve()
        _preflight_target_writable(_resolved_target)

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
    # v0.9.12: detect half-installed state — files present but no manifest.
    # Common cause: previous init hit a mid-flow PermissionError between
    # Phase 4 (atomic batch) and Phase 5 (finalize), leaving target with
    # most files installed but no installed-manifest.json. Without --force
    # the user is stuck: init refuses (files exist), upgrade refuses (no
    # install state). With --force we cleanly delete existing files +
    # staging dirs + pending sidecars before proceeding.
    if existing and not force and not dry_run:
        manifest_present = (target / ".harness" / "installed-manifest.json").exists()
        half_installed = not manifest_present
        if half_installed:
            staging_hint = ""
            harness_dir = target / ".harness"
            if harness_dir.exists():
                stale_staging = list(harness_dir.glob(".staging-*"))
                pending = list(harness_dir.glob("installed-manifest.json.pending-*"))
                if stale_staging or pending:
                    staging_hint = (
                        f"\n  detected: {len(stale_staging)} stale .staging-* dir(s), "
                        f"{len(pending)} pending sidecar(s)"
                    )
            raise SystemExit(
                f"error: harness init detected a half-installed state "
                f"({len(existing)} harness-owned files present, but "
                f".harness/installed-manifest.json is missing).{staging_hint}\n"
                f"\n"
                f"흔한 원인: 이전 init 이 PermissionError 등으로 도중에 실패.\n"
                f"\n"
                f"해결:\n"
                f"  1) (권장) --force 로 재실행 — 기존 harness-owned 파일 + .harness/ 정리 후 새로 init:\n"
                f"       python3 scripts/harness.py init --target {target} --force\n"
                f"\n"
                f"  2) 또는 수동 정리:\n"
                f"       Remove-Item -Recurse -Force .harness   # PowerShell\n"
                f"       rm -rf .harness                         # bash\n"
                f"     그 후 다시 init.\n"
                f"\n"
                f"[Half-installed state detected. Re-run with --force, or delete "
                f"`.harness/` + the harness-owned files and retry.]"
            )
        raise SystemExit(
            "Refusing to overwrite existing files during init:\n  "
            + "\n  ".join(existing)
            + "\nHint: pick an empty target directory, remove these files first, "
            "or pass --force to overwrite."
        )

    # v0.9.12: --force on init cleans up prior install state before staging.
    if force and not dry_run and existing:
        if not quiet:
            sys.stderr.write(
                f"init --force: removing {len(existing)} existing harness-owned "
                f"file(s) and clearing .harness/ before re-staging.\n"
            )
        for entry_path in existing:
            dest = target / entry_path
            try:
                if dest.is_symlink() or dest.exists():
                    dest.unlink()
            except OSError:
                pass  # best-effort; if it persists, atomic batch will hit
        harness_dir = target / ".harness"
        if harness_dir.exists():
            try:
                shutil.rmtree(str(harness_dir), ignore_errors=True)
            except OSError:
                pass

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
        # v0.9.10: print the exact command to run for-real (drop --dry-run).
        _cmd = (
            f"python3 scripts/harness.py init --target {target} "
            f"--adapters {','.join(sorted(adapters))} "
            f"--profiles {','.join(sorted(profiles))}"
        )
        if packs:
            _cmd += f" --packs {','.join(sorted(packs))}"
        print(f"To execute for real: {_cmd}")
        return

    # --- Atomic staged install (T3 / REV-2 phase order) ---
    target.mkdir(parents=True, exist_ok=True)
    harness_dir = target / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)

    iso_compact = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runid = f"{os.getpid()}-{iso_compact}-{secrets.token_hex(3)}"
    staging_dir = harness_dir / f".staging-{runid}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    journal_path = staging_dir.parent / f"{staging_dir.name}.journal.jsonl"
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"

    reporter = ProgressReporter(quiet=quiet)
    _staging_total = sum(1 for entry, _s, _d in destinations if entry.policy == "harness-owned")
    reporter.start("staging files", _staging_total)
    _staged_count = 0

    # Phase 1: stage harness-owned; managed-append + project-owned handled in-place.
    staging_map: dict[Path, Path] = {}  # entry.path -> staged path
    for entry, source, destination in destinations:
        if entry.policy == "managed-append":
            write_managed_append(source=source, destination=destination, entry=entry)
        elif entry.policy == "project-owned" and destination.exists():
            continue
        elif entry.policy == "harness-owned":
            # Stage to staging dir (will be atomically renamed in Phase 4).
            staged = staging_dir / entry.path
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(staged))
            staging_map[entry.path] = staged
            _staged_count += 1
            reporter.tick(_staged_count)
        else:
            # project-owned scaffold file (destination doesn't exist yet): write directly.
            write_copy(source, destination)

    # Phase 2: compose payload from staged hashes.
    payload = build_install_state_payload(
        root=root,
        target=target,
        entries=entries,
        adapters=adapters,
        profiles=profiles,
        packs=packs,
        staging_map=staging_map,
        harness_version=harness_version,
    )

    # Phase 3: write pending sidecar (atomic + fsync).
    reporter.note("writing pending sidecar...")
    _atomic_write_json_fsync(pending_path, payload)

    # Phase 4: atomic batch rename.
    reporter.start("applying atomic batch", _staging_total)
    try:
        result = atomic_install_batch(
            staging_dir,
            target,
            journal_path,
            defer_cleanup=True,
            progress=lambda done, total: reporter.tick(done),
        )
    except CrossFilesystemError:
        if not os.environ.get("HARNESS_ALLOW_NONATOMIC_INSTALL"):
            raise InstallFailed(
                "타겟 파일시스템이 atomic rename 을 지원하지 않습니다.\n"
                "(또는 HARNESS_ALLOW_NONATOMIC_INSTALL=1 로 비-atomic 강제 — 권장하지 않음)\n"
                "\n"
                "복구:\n"
                "    python3 scripts/harness.py state repair\n"
                "\n"
                "[Target filesystem does not support atomic rename.\n"
                "Or set HARNESS_ALLOW_NONATOMIC_INSTALL=1 to force non-atomic install (not recommended).\n"
                "\n"
                "Recover:\n"
                "    python3 scripts/harness.py state repair]"
            )
        # Fallback: copy directly without staging dance.
        for entry, source, destination in destinations:
            if entry.policy not in {"managed-append", "project-owned"}:
                staged = staging_map.get(entry.path)
                if staged is not None and staged.exists():
                    write_copy(staged, destination)
        result = None  # type: ignore[assignment]

    if result is not None and result.aborted:
        raise InstallFailed(
            f"설치 중단됨 (runid={runid}).\n"
            f"\n"
            f"복구:\n"
            f"    python3 scripts/harness.py state repair\n"
            f"\n"
            f"[Install aborted (runid={runid}).\n"
            f"\n"
            f"Recover:\n"
            f"    python3 scripts/harness.py state repair]"
        )

    # Phase 5: sync roomodes + rewrite pending + finalize.
    reporter.note("syncing roomodes...")
    sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)

    # Phase 5a (mirror of upgrade.py FIX-3 B4a): the pending sidecar's .roomodes hashes
    # were composed from the staged template content (pre-sync). sync_roomodes_profile_modes
    # mutates target/.roomodes with profile-injected content, producing a different hash.
    # Rewrite the pending sidecar with post-sync hashes BEFORE the final os.replace so the
    # finalized installed-manifest.json matches what's actually on disk.
    roomodes_path = target / ".roomodes"
    if (
        roomodes_path.exists()
        and ".roomodes" in payload.get("files", {})
    ):
        new_hash = file_hash(roomodes_path)
        payload["files"][".roomodes"]["sha256"] = new_hash
        payload["files"][".roomodes"]["installed_sha256"] = new_hash
        payload["files"][".roomodes"]["current_sha256"] = new_hash
        _atomic_write_json_fsync(pending_path, payload)

    reporter.note("finalizing...")
    final_path = harness_dir / "installed-manifest.json"
    os.replace(str(pending_path), str(final_path))

    # Phase 6: post-finalize verify.
    with open(str(final_path), encoding="utf-8") as fh:
        verify = json.load(fh)
    expected_version = payload["version"]
    if verify.get("version") != expected_version:
        raise InstallFailed(
            f"finalize 검증 실패 (expected={expected_version}, got={verify.get('version')}).\n"
            f"\n"
            f"복구:\n"
            f"    python3 scripts/harness.py state repair\n"
            f"\n"
            f"[Finalize verification failed (expected={expected_version}, got={verify.get('version')}).\n"
            f"\n"
            f"Recover:\n"
            f"    python3 scripts/harness.py state repair]"
        )

    # Phase 7: cleanup (best-effort).
    sentinel_path = staging_dir.parent / f"{staging_dir.name}.complete"
    try:
        sentinel_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        journal_path.unlink(missing_ok=True)
    except OSError:
        pass
    _rmdir_recursive_quiet(staging_dir)

    # B3-Fix-3: stamp trust_origin on fresh install so subsequent upgrades can
    # enforce downgrade protection.
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


class InstallFailed(RuntimeError):
    """Raised when an atomic install fails and cannot be recovered automatically."""


def _preflight_target_writable(target: Path) -> None:
    """v0.9.11: confirm we can create + write inside ``target/.harness/``.

    Common Windows failure modes this catches up-front, with one clear
    message + remediation list, instead of a mid-flow PermissionError
    traceback:
      - target dir itself read-only for the current user
      - inherited deny-write ACL
      - AV / EDR policy blocking dot-prefix directory creation
      - prior install owned by elevated user; current user cannot overwrite
      - target on a network share that refused dot-prefix dirs

    Raises SystemExit with rc=1 if any of those is the case. The probe is
    cleaned up regardless of outcome.
    """
    target.mkdir(parents=True, exist_ok=True)

    if not os.access(str(target), os.W_OK):
        raise SystemExit(
            f"error: harness init refused — target is not writable: {target}\n"
            f"\n"
            f"가능한 원인 + 대처:\n"
            f"  1) 다른 사용자 권한으로 만들어진 target 폴더 → 새 폴더에 init:\n"
            f"     python3 scripts/harness.py init --target <new-empty-folder>\n"
            f"  2) 회사 PC AV / DLP 정책이 쓰기 차단 → 폴더 위치 변경\n"
            f"     (예: C:\\Users\\<you>\\dev\\<project>)\n"
            f"  3) 관리자 권한 PowerShell 에서 재시도 (마지막 수단)\n"
            f"\n"
            f"[Target directory is not writable by the current user.\n"
            f"Try a new empty target, move target out of restricted location, or rerun as admin.]"
        )

    harness_dir = target / ".harness"
    try:
        harness_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SystemExit(
            f"error: harness init refused — cannot create .harness/ in {target}: {exc}\n"
            f"\n"
            f"흔한 원인: 회사 PC AV/EDR 가 dot-prefix 디렉토리 생성 차단 (Windows).\n"
            f"대처:\n"
            f"  1) target 을 user 디렉토리 안으로 이동:\n"
            f"     python3 scripts/harness.py init --target C:\\Users\\<you>\\dev\\<project>\n"
            f"  2) target 폴더에 대해 AV 예외 등록\n"
            f"\n"
            f"[Cannot create .harness/ — likely AV/EDR blocks hidden-dir creation. "
            f"Move target into your user profile or whitelist target in AV settings.]"
        ) from exc

    probe = harness_dir / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(
            f"error: harness init refused — .harness/ exists but is not writable: {exc}\n"
            f"\n"
            f"흔한 원인: 이전 install 이 관리자 권한으로 돌아 .harness/ 가 다른 사용자 소유.\n"
            f"대처 (Windows PowerShell):\n"
            f"  takeown /F .harness /R /A\n"
            f"  icacls .harness /grant \"$env:USERNAME:(F)\" /T\n"
            f"  Remove-Item -Recurse -Force .harness\n"
            f"  python3 scripts\\harness.py init --target .\n"
            f"\n"
            f"[.harness/ exists but current user has no write permission. "
            f"takeown + icacls + delete then retry.]"
        ) from exc


def _atomic_write_json_fsync(path: Path, data: object) -> None:
    """Write JSON payload to ``path`` atomically.

    FIX-C (v0.9.7): unified onto ``atomic_io.atomic_write_text`` (cross-fs guard,
    fchmod-before-replace, dir fsync, Windows retry-replace).  Kept as a thin
    wrapper so call sites elsewhere in install.py / upgrade.py stay readable.
    """
    from lib.atomic_io import atomic_write_text
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, content)


def _rmdir_recursive_quiet(path: Path) -> None:
    """Best-effort recursive directory removal."""
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except OSError:
        pass


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
