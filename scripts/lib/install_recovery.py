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
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from lib.atomic_io import atomic_install_batch, read_install_journal
from lib.audit import audit_append, KNOWN_VERBS  # noqa: F401 (KNOWN_VERBS imported for IDE)

# Staging dirs older than this (in seconds) are treated as stale.
STAGING_AGE_THRESHOLD_SECS: int = 600  # 10 minutes


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
    """Scan ``target/.harness/.staging-*`` and reconcile stale dirs.

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
    staging_dirs = _find_staging_dirs(target)

    stale = [d for d in staging_dirs if _is_stale(d)]
    result = RecoveryResult(found_staging_dirs=len(stale))

    if not stale:
        _emit_audit(target, "install.recovery.noop", {"staging_dirs_found": 0})
        return result

    for staging_dir in stale:
        _recover_one(staging_dir, target, result)

    return result
