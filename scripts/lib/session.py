"""Session lockfile lifecycle per ADR-003a G1-B.

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1.

Posix-only (relies on ``fcntl.flock``); Windows portability is an explicit
non-goal of the spec. Each successful ``acquire_lock`` writes a JSON payload
``{pid, hostname, started_at_utc, harness_version, boot_id}`` to
``.harness/session.lock``. Lifecycle:

- Create with ``O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC`` (the
  ``O_EXCL`` guarantees we lose the race with any concurrent acquirer; we
  layer ``flock(LOCK_EX|LOCK_NB)`` on top to defeat NFS-style append
  races).
- Register ``atexit`` cleanup + SIGINT/SIGTERM handlers that unlink the
  lockfile before re-raising the default signal behaviour.
- ``release_lock`` is idempotent: missing files are silently tolerated.

``harness session unlock`` (in `phase_cli.py`) uses ``is_pid_alive`` +
``read_boot_id`` to decide whether an existing lockfile is stale.
"""

from __future__ import annotations

import atexit
import contextlib
import errno
import fcntl
import json
import os
import platform
import re
import signal
import socket
import subprocess
from pathlib import Path
from typing import Iterator, Optional

from lib.timestamps import now_iso_nanos


class LockfileExists(Exception):
    """Raised by ``acquire_lock`` when ``.harness/session.lock`` already exists."""


_active_lockfile: Optional[Path] = None


_DARWIN_BOOTTIME_RE = re.compile(r"\{\s*sec\s*=\s*(\d+)")


def read_boot_id() -> Optional[str]:
    """Return a stable per-boot identifier, or ``None`` if unavailable.

    Per-platform sources (M1 amendment):

    - Linux: ``/proc/sys/kernel/random/boot_id`` (unchanged contract).
    - macOS: ``sysctl -n kern.boottime`` → ``{ sec = N, usec = M } ...``,
      parsed to ``"darwin-boot-{N}"``. Stable across the lifetime of a
      single kernel boot; changes on reboot. The ``usec`` field is
      intentionally dropped — a per-second granularity is sufficient for
      detecting reboots and avoids spurious mismatches when the boot
      epoch is sub-second skewed across reads.
    - Other Unix: ``None`` (caller treats as "boot_id unknown" and falls
      back to pid-liveness alone).
    """
    system = platform.system()
    if system == "Linux":
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return None
    if system == "Darwin":
        try:
            r = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        m = _DARWIN_BOOTTIME_RE.search(r.stdout)
        if not m:
            return None
        return f"darwin-boot-{m.group(1)}"
    return None


def _harness_version() -> str:
    try:
        import harness  # type: ignore
        return getattr(harness, "HARNESS_VERSION", "0.0.0-dev+unknown")
    except Exception:
        return "0.0.0-dev+unknown"


def _build_payload() -> dict:
    return {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "started_at_utc": now_iso_nanos(),
        "harness_version": _harness_version(),
        "boot_id": read_boot_id(),
    }


def release_lock(lock_path: Optional[Path] = None) -> None:
    """Remove the lockfile if present. Idempotent."""
    global _active_lockfile
    target = lock_path or _active_lockfile
    if target is None:
        return
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    if _active_lockfile is not None and target == _active_lockfile:
        _active_lockfile = None


def _install_signal_handlers(lock_path: Path) -> None:
    def _handler(signum, frame):  # type: ignore[no-untyped-def]
        release_lock(lock_path)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


@contextlib.contextmanager
def acquire_lock(*, lock_path: Path) -> Iterator[Path]:
    """Acquire the session lock via O_EXCL + flock.

    Raises ``LockfileExists`` on contention.
    """
    global _active_lockfile
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(lock_path), flags, 0o644)
    except FileExistsError as exc:
        raise LockfileExists(str(lock_path)) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise LockfileExists(f"refusing to follow symlink at {lock_path}") from exc
        raise

    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Another process holds the flock — treat as contention.
            os.close(fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            raise LockfileExists(str(lock_path))
        payload_bytes = (json.dumps(_build_payload()) + "\n").encode("utf-8")
        # M2: a write failure (ENOSPC, EIO, etc.) leaves an empty/partial
        # lockfile that jams every subsequent harness invocation with
        # LockfileExists. Close the fd, unlink the lockfile, then re-raise
        # so the caller sees the original errno.
        try:
            os.write(fd, payload_bytes)
            os.fsync(fd)
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    _active_lockfile = lock_path
    atexit.register(release_lock, lock_path)
    _install_signal_handlers(lock_path)
    try:
        yield lock_path
    finally:
        release_lock(lock_path)


def read_lock_payload(lock_path: Path) -> dict:
    return json.loads(Path(lock_path).read_text())


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


__all__ = [
    "LockfileExists",
    "acquire_lock",
    "release_lock",
    "read_lock_payload",
    "is_pid_alive",
    "read_boot_id",
]
