"""Backup helpers for atomic state-mutation workflows.

Owning slice: T0-1 CC5 (extracted from ``lib.state_migrate``).
Future owner: T0-5 per CONTRACT-PIN §1 -- may patch retention policy.

Public surface:
- ``write_backup_with_excl_and_prune(target, *, source_bytes, backups_dir=None,
  retention=10) -> Path`` -- writes ``source_bytes`` into a per-target
  timestamped ``.bak`` (CONTRACT-PIN §6.1 filename grammar) using
  ``O_CREAT|O_EXCL|O_NOFOLLOW`` so neither pre-existing files nor symlinks
  can be silently overwritten. Creates the backups directory with mode
  ``0o700`` when absent (SM3). Then prunes oldest backups of the same
  basename so at most ``retention`` remain.

Symbols intentionally exposed for test seams:
- ``_compact_utc_nanos`` -- timestamp generator (monkeypatched in tests).
- ``_pid`` -- process id helper (monkeypatched in tests).
"""

from __future__ import annotations

import fnmatch
import os
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Test seams.
# ---------------------------------------------------------------------------


def _compact_utc_nanos() -> str:
    """Return current UTC time as ``YYYYMMDDTHHMMSSnnnnnnnnnZ`` (CONTRACT-PIN §6.1)."""
    ns = time.time_ns()
    secs, nanos = divmod(ns, 1_000_000_000)
    tm = time.gmtime(secs)
    return "%04d%02d%02dT%02d%02d%02d%09dZ" % (
        tm.tm_year, tm.tm_mon, tm.tm_mday,
        tm.tm_hour, tm.tm_min, tm.tm_sec, nanos,
    )


def _pid() -> int:
    return os.getpid()


# ---------------------------------------------------------------------------
# Exceptions.
# ---------------------------------------------------------------------------


class _CodedSystemExit(SystemExit):
    """SystemExit with both ``.code`` (int) and ``str()`` (message)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(code)
        self._message = message

    def __str__(self) -> str:  # noqa: D401
        return self._message


def _exit1(message: str) -> _CodedSystemExit:
    return _CodedSystemExit(1, message)


# ---------------------------------------------------------------------------
# Backup directory management.
# ---------------------------------------------------------------------------


_REPO_BACKUPS_DEFAULT = Path(".harness/backups")


def default_backups_dir(target: Path) -> Path:
    """Walk up from ``target`` to a repo-root-like directory; place backups there."""
    for parent in [target.parent, *target.parent.parents]:
        if (parent / ".harness").exists() or (parent / ".scratch").exists():
            return parent / ".harness" / "backups"
    return target.parent / ".harness" / "backups"


def _ensure_backups_dir(backups_dir: Path) -> None:
    """Create ``backups_dir`` if missing; chmod to 0o700 either way (SM3)."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(backups_dir, 0o700)
    except OSError:
        # Non-fatal -- e.g. on filesystems that ignore chmod -- but still
        # surface the attempt above for the common case.
        pass


# ---------------------------------------------------------------------------
# Filename grammar.
# ---------------------------------------------------------------------------


def _bak_name(target: Path) -> str:
    """CONTRACT-PIN §6.1: ``<basename>.pre-repair.<ts>.<pid>.bak``."""
    return f"{target.name}.pre-repair.{_compact_utc_nanos()}.{_pid()}.bak"


# ---------------------------------------------------------------------------
# Core write + retention prune.
# ---------------------------------------------------------------------------


_DEFAULT_RETENTION = 10


def _open_excl(bak_path: Path) -> int:
    """Open ``bak_path`` with O_EXCL + O_NOFOLLOW; return fd. Propagates errors."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(str(bak_path), flags, 0o644)


def _write_bak_excl(bak_path: Path, content: bytes) -> None:
    """Write ``content`` to ``bak_path`` with O_EXCL + O_NOFOLLOW (single attempt)."""
    try:
        fd = _open_excl(bak_path)
    except FileExistsError:
        raise _exit1(
            f"error: backup file already exists at {bak_path}; this typically "
            f"indicates a previous migration crashed. Inspect the backup and either:\n"
            f"  (a) restore it manually (cp {bak_path} <target>) and re-run, or\n"
            f"  (b) run 'harness migrate state --resume' to continue from the backup, or\n"
            f"  (c) remove the stale backup after confirming target is correct."
        )
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


def _prune_old_backups(target_basename: str, backups_dir: Path, retention: int) -> None:
    """Keep at most ``retention`` ``.bak`` files matching ``<basename>.pre-repair.*.bak``.

    Sort is lexicographic by filename. Because CONTRACT-PIN §6.1 timestamps
    are zero-padded ``YYYYMMDDTHHMMSSnnnnnnnnn``, lexicographic order ==
    chronological order. Oldest files are unlinked.
    """
    # SecM1: use os.scandir + entry.is_symlink() so a hostile or
    # accidentally-planted symlink under backups_dir cannot trick the
    # retention loop into unlinking through it. Skipped symlinks emit a
    # stderr warning so the operator can investigate.
    pattern = f"{target_basename}.pre-repair.*.bak"
    matches: list[Path] = []
    with os.scandir(backups_dir) as it:
        for entry in it:
            if not fnmatch.fnmatchcase(entry.name, pattern):
                continue
            try:
                if entry.is_symlink():
                    print(
                        f"WARNING: skipping symlink in .harness/backups/ during prune: "
                        f"{entry.name}",
                        file=sys.stderr,
                    )
                    continue
            except OSError:  # pragma: no cover -- race during scan
                continue
            matches.append(Path(entry.path))
    matches.sort()
    excess = len(matches) - retention
    if excess <= 0:
        return
    for stale in matches[:excess]:
        try:
            stale.unlink()
        except FileNotFoundError:  # pragma: no cover -- concurrent prune
            pass


def write_backup_with_excl_and_prune(
    target: Path,
    *,
    source_bytes: bytes,
    backups_dir: Optional[Path] = None,
    retention: int = _DEFAULT_RETENTION,
) -> Path:
    """Write ``source_bytes`` as a per-target ``.bak`` and prune old siblings.

    Returns the path of the freshly written backup.
    """
    target = Path(target)
    if backups_dir is None:
        backups_dir = default_backups_dir(target)
    _ensure_backups_dir(backups_dir)

    # CC4: retry up to 3 times on O_EXCL collision (regenerate the name each
    # time via _compact_utc_nanos / _pid). Pre-existing legitimate .bak
    # collisions still surface as exit-1 from _write_bak_excl after the last
    # retry, preserving the original "stale backup" guidance.
    bak_path: Optional[Path] = None
    last_exc: Optional[BaseException] = None
    for attempt in range(3):
        candidate = backups_dir / _bak_name(target)
        try:
            fd = _open_excl(candidate)
        except FileExistsError as exc:
            last_exc = exc
            continue
        try:
            os.write(fd, source_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
        bak_path = candidate
        break

    if bak_path is None:
        # All retries collided -- fall through to the canonical exit-1 message
        # using the most recent candidate path (last_exc carries the original).
        _write_bak_excl(backups_dir / _bak_name(target), source_bytes)
        # _write_bak_excl always either succeeds or raises; we should not reach
        # here, but keep type-checkers happy.
        raise AssertionError(f"unreachable; last exc was {last_exc!r}")

    _prune_old_backups(target.name, backups_dir, retention)
    return bak_path


__all__ = [
    "write_backup_with_excl_and_prune",
    "default_backups_dir",
]
