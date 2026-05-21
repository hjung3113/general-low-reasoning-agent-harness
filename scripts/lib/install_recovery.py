"""Detect and reconcile aborted install staging directories (T14b).

A staging directory is considered *stale* when it is either:
  - older than ``STAGING_AGE_THRESHOLD_SECS`` (default 600 s / 10 min), OR
  - contains a ``.aborted`` sentinel written by ``atomic_install_batch``.

Recovery decisions
------------------
1. All journal entries are *complete* (no entry with ``"error"`` key AND
   no staging files remain) → staging dir was fully renamed; clean it up
   and emit ``install.recovery.finished``.

2. Staging dir has *pending* renames (staging files still present, no
   ``.aborted`` sentinel) → resume via a fresh ``atomic_install_batch``
   call and emit ``install.recovery.finished`` on success.

3. ``.aborted`` sentinel present → rollback: for each completed rename in
   the journal try to restore from ``.harness/backups/``; if no backup
   is available, move the displaced file to ``.harness/conflicts/`` with
   a timestamp suffix and emit ``install.recovery.quarantined``.  Emit
   ``install.recovery.rolled_back`` for entries restored from backup.

Audit rows are written via ``lib.audit.audit_append`` — never raw file
write.

Public API
----------
``recover_aborted_install(target) -> RecoveryResult``
"""

from __future__ import annotations

import datetime
import fnmatch
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List

from lib.atomic_io import atomic_install_batch, read_install_journal
from lib.audit import audit_append, KNOWN_VERBS  # noqa: F401 (KNOWN_VERBS imported for IDE)

# Staging dirs older than this (in seconds) are treated as stale.
STAGING_AGE_THRESHOLD_SECS: int = 600  # 10 minutes


class RecoveryAction(Enum):
    """Action taken for one pending-manifest recovery."""
    FINALIZED = auto()       # pending -> final (sentinel path)
    ROLLED_BACK = auto()     # explicit rollback (.aborted marker)
    RESUMED = auto()         # resumed batch + finalized
    QUARANTINED = auto()     # orphaned pending sidecar quarantined
    NOOP = auto()            # nothing to do


@dataclass
class RecoveryResult:
    """Outcome of :func:`recover_aborted_install`."""

    found_staging_dirs: int
    finished: List[Path] = field(default_factory=list)   # completed pending renames
    rolled_back: List[Path] = field(default_factory=list)  # entries undone via backup
    quarantined: List[Path] = field(default_factory=list)  # entries moved to conflicts/
    sentinel_present: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _harness_dir(target: Path) -> Path:
    return target / ".harness"


def _audit_path(target: Path) -> Path:
    return _harness_dir(target) / "audit.log"


def _conflicts_dir(target: Path) -> Path:
    return _harness_dir(target) / "conflicts"


def _backups_dir(target: Path) -> Path:
    return _harness_dir(target) / "backups"


def _compact_ts() -> str:
    """Return current UTC time as a compact ISO-8601 string for filenames."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def _find_staging_dirs(target: Path) -> List[Path]:
    """Return all ``.staging-*`` directories under ``target/.harness/``."""
    harness = _harness_dir(target)
    if not harness.is_dir():
        return []
    found: List[Path] = []
    try:
        with os.scandir(str(harness)) as it:
            for entry in it:
                if fnmatch.fnmatchcase(entry.name, ".staging-*") and entry.is_dir(
                    follow_symlinks=False
                ):
                    found.append(Path(entry.path))
    except OSError:
        pass
    return found


def _is_stale(staging_dir: Path) -> bool:
    """Return True when staging_dir is old enough or has an .aborted sentinel."""
    if (staging_dir / ".aborted").exists():
        return True
    try:
        mtime = staging_dir.stat().st_mtime
        age = time.time() - mtime
        return age >= STAGING_AGE_THRESHOLD_SECS
    except OSError:
        return True  # can't stat → treat as stale


def _staging_journal_path(staging_dir: Path) -> Path:
    """Conventional journal path alongside the staging dir."""
    return staging_dir.parent / (staging_dir.name + ".journal.jsonl")


def _journal_completed(records: list[dict]) -> list[str]:
    """Return rel-paths of entries that were successfully renamed."""
    return [r["src_rel"] for r in records if "src_rel" in r and "error" not in r]


def _find_backup(backups_dir: Path, filename: str) -> Path | None:
    """Find the *most recent* ``.bak`` for ``filename`` under ``backups_dir``."""
    if not backups_dir.is_dir():
        return None
    pattern = f"{filename}.pre-repair.*.bak"
    matches: list[Path] = []
    try:
        with os.scandir(str(backups_dir)) as it:
            for entry in it:
                if fnmatch.fnmatchcase(entry.name, pattern) and not entry.is_symlink():
                    matches.append(Path(entry.path))
    except OSError:
        return None
    if not matches:
        return None
    matches.sort()
    return matches[-1]  # most recent (lexicographic = chronological per §6.1)


def _emit_audit(target: Path, verb: str, payload: dict) -> None:
    """Emit a single audit row; silently suppress if audit log not writable."""
    audit_path = _audit_path(target)
    # Ensure .harness/ exists (it should; we only recover inside an installed target).
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"verb": verb, "args": payload}
    try:
        audit_append(entry, audit_path=audit_path)
    except (OSError, SystemExit):
        # Best-effort: recovery must not crash because audit is unavailable.
        pass


# ---------------------------------------------------------------------------
# Pending-manifest recovery (.pending-<runid> sidecar)
# ---------------------------------------------------------------------------

# Age threshold for .complete.tmp orphan cleanup (seconds).
_SENTINEL_TMP_ORPHAN_AGE_SECS: int = 60


def _find_pending_manifests(target: Path) -> List[Path]:
    """Return all ``installed-manifest.json.pending-*`` files under ``target/.harness/``."""
    harness = _harness_dir(target)
    if not harness.is_dir():
        return []
    found: List[Path] = []
    try:
        with os.scandir(str(harness)) as it:
            for entry in it:
                if (
                    fnmatch.fnmatchcase(
                        entry.name, "installed-manifest.json.pending-*"
                    )
                    and entry.is_file(follow_symlinks=False)
                ):
                    found.append(Path(entry.path))
    except OSError:
        pass
    return found


def _cleanup_sentinel_tmp_orphans(target: Path) -> int:
    """Scan ``.harness/.staging-*.complete.tmp`` and unlink orphans older than 60s.

    Returns the count of files removed.
    """
    harness = _harness_dir(target)
    if not harness.is_dir():
        return 0
    removed = 0
    now = time.time()
    try:
        with os.scandir(str(harness)) as it:
            for entry in it:
                if (
                    fnmatch.fnmatchcase(entry.name, ".staging-*.complete.tmp")
                    and entry.is_file(follow_symlinks=False)
                ):
                    try:
                        mtime = os.path.getmtime(entry.path)
                        if (now - mtime) >= _SENTINEL_TMP_ORPHAN_AGE_SECS:
                            os.unlink(entry.path)
                            removed += 1
                    except OSError:
                        pass
    except OSError:
        pass
    return removed


def _recover_pending_manifest(
    target: Path,
    pending_path: Path,
    result: RecoveryResult,
) -> RecoveryAction:
    """Recover one ``installed-manifest.json.pending-<runid>`` sidecar.

    Decision matrix (checked in order — .aborted BEFORE sentinel per REV-2):

    1. ``runid`` extracted from suffix. Derive staging_dir, journal_path, sentinel_path.
    2. ``.aborted`` marker present in staging_dir → EXPLICIT ROLLBACK (.aborted wins).
    3. Sentinel (``.staging-<runid>.complete``) exists → FINALIZE (os.replace pending→final).
    4. Journal + staging_dir present → RESUME batch; on success FINALIZE.
    5. None of the above → ORPHAN → quarantine pending sidecar; emit audit row.
    """
    harness = _harness_dir(target)
    final_path = harness / "installed-manifest.json"

    # Extract runid from pending filename suffix.
    prefix = "installed-manifest.json.pending-"
    if not pending_path.name.startswith(prefix):
        return RecoveryAction.NOOP
    runid = pending_path.name[len(prefix):]

    staging_dir = harness / f".staging-{runid}"
    journal_path = harness / f".staging-{runid}.journal.jsonl"
    sentinel_path = harness / f".staging-{runid}.complete"

    # Step 1: .aborted wins over sentinel (REV-2 Codex NEW-1 decision matrix).
    aborted_marker = staging_dir / ".aborted"
    if aborted_marker.exists():
        result.sentinel_present = True  # re-use field to signal aborted state
        # Rollback: for completed journal entries, restore from backup or quarantine.
        records = read_install_journal(journal_path)
        completed_rels = _journal_completed(records)
        backups = _backups_dir(target)
        conflicts = _conflicts_dir(target)
        for rel in completed_rels:
            installed_path = target / rel
            if not installed_path.exists():
                continue
            bak = _find_backup(backups, installed_path.name)
            if bak is not None:
                try:
                    installed_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(bak), str(installed_path))
                    result.rolled_back.append(installed_path)
                    _emit_audit(target, "install.recovery.rolled_back", {"rel": rel, "backup": str(bak)})
                except OSError:
                    _quarantine_file(installed_path, conflicts, rel, target, result)
            else:
                _quarantine_file(installed_path, conflicts, rel, target, result)
        # Cleanup
        _cleanup_pending_artifacts(staging_dir, journal_path, sentinel_path, pending_path)
        return RecoveryAction.ROLLED_BACK

    # Step 2: sentinel exists → finalize.
    if sentinel_path.exists():
        try:
            _finalize_pending_manifest(pending_path, final_path, target)
        except Exception as exc:
            _emit_audit(target, "install.recovery.pending_finalize_failed", {"error": str(exc)})
            return RecoveryAction.NOOP
        _cleanup_pending_artifacts(staging_dir, journal_path, sentinel_path, pending_path)
        _emit_audit(target, "install.recovery.finished", {"runid": runid, "method": "sentinel_finalize"})
        result.finished.append(final_path)
        return RecoveryAction.FINALIZED

    # Step 3: journal + staging dir → resume batch.
    if journal_path.exists() and staging_dir.exists():
        try:
            batch_result = atomic_install_batch(staging_dir, target, journal_path, defer_cleanup=True)
        except OSError:
            return RecoveryAction.NOOP
        if batch_result.aborted:
            # Batch failed during resume; leave for operator.
            return RecoveryAction.NOOP
        # Sentinel written by batch; finalize.
        if sentinel_path.exists():
            try:
                _finalize_pending_manifest(pending_path, final_path, target)
            except Exception as exc:
                _emit_audit(target, "install.recovery.pending_finalize_failed", {"error": str(exc)})
                return RecoveryAction.NOOP
            _cleanup_pending_artifacts(staging_dir, journal_path, sentinel_path, pending_path)
            _emit_audit(target, "install.recovery.finished", {"runid": runid, "method": "resume_finalize"})
            result.finished.append(final_path)
            return RecoveryAction.RESUMED
        return RecoveryAction.NOOP

    # Step 4: orphan — no staging, no journal, no sentinel, no .aborted.
    conflicts = _conflicts_dir(target)
    try:
        conflicts.mkdir(parents=True, exist_ok=True)
        ts = _compact_ts()
        dest = conflicts / f"installed-manifest.json.pending.{ts}"
        os.replace(str(pending_path), str(dest))
        result.quarantined.append(pending_path)
        _emit_audit(
            target,
            "install.recovery.pending_orphaned",
            {"pending": pending_path.name, "conflicts_path": str(dest)},
        )
    except OSError:
        pass
    return RecoveryAction.QUARANTINED


def _finalize_pending_manifest(pending_path: Path, final_path: Path, target: Path) -> None:
    """Atomic rename of pending sidecar to final manifest path with post-finalize verify."""
    # Read pending content before rename.
    try:
        pending_content = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read pending manifest {pending_path}: {exc}") from exc

    expected_version = pending_content.get("version")
    os.replace(str(pending_path), str(final_path))

    # Post-finalize verify.
    try:
        actual = json.loads(final_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Post-finalize verify failed (unreadable): {exc}") from exc
    if actual.get("version") != expected_version:
        raise RuntimeError(
            f"Post-finalize verify: version mismatch (expected={expected_version!r}, "
            f"got={actual.get('version')!r}). "
            f"복구: python3 scripts/harness.py state repair "
            f"[Finalize verification failed; recover with: python3 scripts/harness.py state repair]"
        )


def _cleanup_pending_artifacts(
    staging_dir: Path,
    journal_path: Path,
    sentinel_path: Path,
    pending_path: Path,
) -> None:
    """Best-effort cleanup of staging artifacts after pending-manifest recovery."""
    for p in (sentinel_path, journal_path, pending_path):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    if staging_dir.exists():
        try:
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Core recovery logic for a single staging dir
# ---------------------------------------------------------------------------


def _recover_one(
    staging_dir: Path,
    target: Path,
    result: RecoveryResult,
) -> None:
    """Reconcile one stale staging directory; mutates ``result`` in-place."""
    sentinel = staging_dir / ".aborted"
    journal_path = _staging_journal_path(staging_dir)
    records = read_install_journal(journal_path)
    completed_rels = _journal_completed(records)

    if sentinel.exists():
        result.sentinel_present = True
        # Rollback path: undo completed renames using backups, or quarantine.
        backups = _backups_dir(target)
        conflicts = _conflicts_dir(target)
        for rel in completed_rels:
            installed_path = target / rel
            if not installed_path.exists():
                # Already gone; nothing to undo.
                continue
            bak = _find_backup(backups, installed_path.name)
            if bak is not None:
                # Restore from backup via os.replace (atomic on same-FS).
                try:
                    installed_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(bak), str(installed_path))
                    result.rolled_back.append(installed_path)
                    _emit_audit(
                        target,
                        "install.recovery.rolled_back",
                        {"rel": rel, "backup": str(bak)},
                    )
                except OSError:
                    # Backup restore failed → quarantine instead.
                    _quarantine_file(installed_path, conflicts, rel, target, result)
            else:
                # No backup → quarantine.
                _quarantine_file(installed_path, conflicts, rel, target, result)

        # Remove staging dir (best-effort).
        try:
            shutil.rmtree(str(staging_dir), ignore_errors=True)
        except OSError:
            pass
        if journal_path.exists():
            try:
                journal_path.unlink()
            except OSError:
                pass
        return

    # No .aborted sentinel → finish pending renames (idempotent resume).
    try:
        batch_result = atomic_install_batch(staging_dir, target, journal_path)
        for rel in batch_result.completed:
            finished_path = target / rel
            result.finished.append(finished_path)
        _emit_audit(
            target,
            "install.recovery.finished",
            {
                "staging_dir": staging_dir.name,
                "completed": len(batch_result.completed),
                "aborted": batch_result.aborted,
            },
        )
    except OSError:
        # Can't resume; leave staging dir intact for operator inspection.
        pass


def _quarantine_file(
    installed_path: Path,
    conflicts: Path,
    rel: str,
    target: Path,
    result: RecoveryResult,
) -> None:
    """Move ``installed_path`` into the conflicts directory."""
    try:
        conflicts.mkdir(parents=True, exist_ok=True)
        ts = _compact_ts()
        safe_name = rel.replace("/", "_").replace("\\", "_")
        dest = conflicts / f"{safe_name}.{ts}"
        os.replace(str(installed_path), str(dest))
        result.quarantined.append(installed_path)
        _emit_audit(
            target,
            "install.recovery.quarantined",
            {"rel": rel, "conflicts_path": str(dest)},
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def recover_aborted_install(target: Path) -> RecoveryResult:
    """Scan ``target/.harness/`` and reconcile pending installs and stale dirs.

    Order of operations per REV-2:
    1. Scan ``installed-manifest.json.pending-*`` and dispatch to
       ``_recover_pending_manifest`` for each.
    2. Clean up ``.staging-*.complete.tmp`` orphans older than 60s.
    3. Legacy scan: stale ``.staging-*`` dirs (no pending sidecar) via
       ``_recover_one``.

    Parameters
    ----------
    target:
        Root of the installed harness target (contains ``.harness/``).

    Returns
    -------
    RecoveryResult
        Summary of recovery actions taken.
    """
    target = Path(target)

    # Step 1: pending-manifest recovery.
    pending_manifests = _find_pending_manifests(target)
    any_pending_work = len(pending_manifests) > 0

    staging_dirs = _find_staging_dirs(target)
    stale = [d for d in staging_dirs if _is_stale(d)]

    result = RecoveryResult(found_staging_dirs=len(stale) + len(pending_manifests))

    for pending_path in pending_manifests:
        _recover_pending_manifest(target, pending_path, result)

    # Step 2: .complete.tmp orphan cleanup.
    _cleanup_sentinel_tmp_orphans(target)

    # Step 3: legacy stale staging-dir recovery (for staging dirs not linked to a pending sidecar).
    if not stale and not any_pending_work:
        _emit_audit(target, "install.recovery.noop", {"staging_dirs_found": 0})
        return result

    for staging_dir in stale:
        # Skip if this staging dir was already handled by pending-manifest recovery.
        runid = staging_dir.name[len(".staging-"):]
        pending_for_this = _harness_dir(target) / f"installed-manifest.json.pending-{runid}"
        if pending_for_this in pending_manifests:
            continue
        _recover_one(staging_dir, target, result)

    return result
