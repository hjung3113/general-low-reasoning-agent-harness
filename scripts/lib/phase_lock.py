"""Cross-platform O_EXCL state lock + recovery mutex (design §3.7).

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
ADR:  `docs/adr/2026-05-17-audit-canonicalization-locking-and-state-trust.md`

Public surface
--------------
    LockError                       -- base OSError subclass; exit policy
                                       chosen by caller (typically 3).
    LockHeldError(LockError)        -- live/foreign-host/ambiguous lock owner.
    LockTimeoutError(LockError)     -- timeout while waiting.
    LockRecoveryError(LockError)    -- recovery failed (e.g. Windows AV pin).
    LockHandle                      -- dataclass(fd, path, owner_token, scratch)
    LOCK_VERDICTS                   -- frozenset of classify() outputs
    current_owner_record()          -- builds a fresh record for THIS process
    classify(record, *, current_hostname, current_boot_id, proc_lookup)
                                    -- verdict in LOCK_VERDICTS
    acquire_primary(scratch, *, timeout_s=10.0, audit_path=None)
                                    -- STEP A->D loop; returns LockHandle.
    release_primary(handle)         -- idempotent unlink + close.
    try_recover(scratch, observed_token, *, audit_path=None)
                                    -- single recovery attempt; returns None.

The recovery path emits `verb=lock.recovered` (design §3.7 line 417) only
when an `audit_path` is supplied; this mirrors `state_migrate.migrate_file`
and `durable_fs` — wiring policy is the caller's, not this module's.

OS-substrate details:
* `_current_boot_id`: Linux `/proc/sys/kernel/random/boot_id`, macOS
  `sysctl -n kern.boottime` (compact-tuple parse), Windows
  `GetTickCount64`-shifted approximation (LastBootUpTime is the canonical
  source; release-smoke S13 substitutes the WMI value).
* `_proc_lookup`: returns `(alive: bool, create_time: float | None)` via
  `psutil`; raises whatever exception `psutil` raises (PermissionError /
  OSError) so `classify()` can map to `"ambiguous"`.
"""

from __future__ import annotations

import dataclasses
import datetime
import errno
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

import psutil

from . import durable_fs as _durable_fs
from . import audit as _audit


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------


LOCK_VERDICTS: frozenset[str] = frozenset({"live", "foreign_host", "stale", "ambiguous"})

PRIMARY_NAME = "phase-state.json.lock"
RECOVERY_NAME = "phase-state.json.lock.recovery"

MAX_RECOVERY_WAIT_S = 30.0
BACKOFF_INITIAL_S = 0.05
BACKOFF_MAX_S = 1.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LockError(OSError):
    """Base class for phase_lock failures. Callers map to exit 3."""


class LockHeldError(LockError):
    """Lock currently held (live owner, foreign host, or ambiguous)."""


class LockTimeoutError(LockError):
    """Timed out before the lock became acquireable."""


class LockRecoveryError(LockError):
    """Stale lock detected but its removal failed (e.g. Windows AV pin)."""


# ---------------------------------------------------------------------------
# Handle
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LockHandle:
    fd: int
    path: Path
    owner_token: str
    scratch: Path
    _released: bool = False


# ---------------------------------------------------------------------------
# Host / boot identity helpers (overridable test seams)
# ---------------------------------------------------------------------------


def _current_hostname() -> str:
    return socket.gethostname()


def _current_boot_id() -> str:
    """Best-effort stable identifier for this machine's current boot.

    Linux  : /proc/sys/kernel/random/boot_id
    macOS  : `sysctl -n kern.boottime` -> { sec = N, usec = M } -> "N.M"
    Windows: not implementable without WMI here; we approximate via the
             ms-precision tick count (GetTickCount64) which is monotonic
             since boot. Production substitute (WMI LastBootUpTime) is
             wired in the S13 release-smoke matrix per design §3.7.
    """
    if sys.platform.startswith("linux"):
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        except OSError:
            return "linux-boot-id-unavailable"

    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout
            m = re.search(r"sec\s*=\s*(\d+),\s*usec\s*=\s*(\d+)", out)
            if m:
                return f"{m.group(1)}.{m.group(2)}"
            return out.strip()
        except (OSError, subprocess.SubprocessError):
            return "darwin-boot-id-unavailable"

    # S01-C review-fix (P2, 2026-05-17): the original Windows fallback
    # computed `int(time.time()) - GetTickCount64()//1000` which separately
    # truncated both sides and could drift by one full second between
    # calls, breaking the i1 "same boot → same boot_id" requirement.
    # `psutil.boot_time()` returns a stable float per boot session on
    # every supported platform — use it for the non-Linux/non-darwin
    # fallback (covers Windows, FreeBSD, etc.). The S13 release-smoke
    # matrix substitutes the canonical WMI LastBootUpTime per design §3.7.
    try:
        return f"psutil-boot-{psutil.boot_time()}"
    except (OSError, psutil.Error):
        return f"unknown-os-{sys.platform}"


def _proc_lookup(pid: int) -> tuple[bool, Optional[float]]:
    """Return (alive, create_time_seconds_since_epoch).

    Raises whatever psutil raises (PermissionError / OSError / etc.) so
    classify() can map it to "ambiguous".
    """
    if not psutil.pid_exists(pid):
        return False, None
    proc = psutil.Process(pid)
    return True, float(proc.create_time())


# ---------------------------------------------------------------------------
# Owner record write/read
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def current_owner_record(*, owner_token: Optional[str] = None) -> dict[str, Any]:
    """Build the JSON record for a freshly-acquired lock (design §3.7)."""
    pid = os.getpid()
    try:
        _, create_time = _proc_lookup(pid)
    except (OSError, psutil.Error):
        # v0.7.0 review CRIT WF-3: prior code stored 0.0 here, which classify()
        # then compared against a live create_time and falsely returned "stale",
        # letting try_recover unlink a still-held lock. We now store None and
        # classify() treats None as "ambiguous" (no-op), refusing to recover.
        create_time = None
    return {
        "pid": pid,
        "hostname": _current_hostname(),
        "process_start_time": float(create_time) if create_time is not None else None,
        "boot_id": _current_boot_id(),
        "monotonic_acquired_at": time.monotonic(),
        "acquired_iso": _now_iso(),
        "owner_token": owner_token or secrets.token_hex(16),
    }


def _write_owner_record(fd: int, record: Mapping[str, Any]) -> None:
    """Serialize `record` as canonical JSON and `os.write` it into `fd`.

    Caller owns the fd lifecycle (close + fsync). The serializer uses
    `sort_keys=True` so the file is deterministic for diff/hash. RFC 8785
    canonicalization is reserved for audit-chain payloads (§2.3); the
    lock file does not participate in the per-entry hash chain.
    """
    line = json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
    os.write(fd, line.encode("utf-8"))


def _read_owner_record(path: Union[str, "os.PathLike[str]"]) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def classify(
    record: Mapping[str, Any],
    *,
    current_hostname: str,
    current_boot_id: str,
    proc_lookup: Callable[[int], tuple[bool, Optional[float]]],
) -> str:
    """Decision matrix from design §3.7. Return value is in `LOCK_VERDICTS`."""
    if record.get("hostname") != current_hostname:
        return "foreign_host"
    if record.get("boot_id") != current_boot_id:
        # Reboot happened — pid namespace is fresh; safe to recover.
        return "stale"
    try:
        alive, create_time = proc_lookup(int(record.get("pid", -1)))
    except (OSError, psutil.Error):
        # S01-C review-fix (P1): psutil.Error is NOT an OSError subclass
        # in psutil 7.x — NoSuchProcess / AccessDenied / ZombieProcess
        # need to map to "ambiguous" per §3.7. Any *other* exception
        # (ValueError, KeyboardInterrupt, programmer bug) intentionally
        # propagates so it surfaces during testing.
        return "ambiguous"
    if not alive:
        return "stale"
    if create_time is None:
        return "ambiguous"
    stored = record.get("process_start_time", None)
    # v0.7.0 review CRIT WF-3: None means the recorder could not read
    # psutil at acquire time — treat as ambiguous, never stale, so a live
    # lock holder under transient psutil failure is not silently recovered.
    if stored is None:
        return "ambiguous"
    if float(stored) != float(create_time):
        return "stale"
    return "live"


# ---------------------------------------------------------------------------
# acquire_primary
# ---------------------------------------------------------------------------


def acquire_primary(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    timeout_s: float = 10.0,
    audit_path: Optional[Union[str, "os.PathLike[str]"]] = None,
    max_recovery_wait_s: Optional[float] = None,
) -> LockHandle:
    """STEP A/B/C/D loop per design §3.7.

    Raises `LockTimeoutError` on timeout; `LockHeldError` on "ambiguous"
    (requires `harness session unlock --force`). Returns a `LockHandle` on
    successful acquisition.

    `max_recovery_wait_s`: cap for how long STEP A will wait on the recovery
    mutex. Defaults to ``min(timeout_s, 30.0)`` when None.
    """
    scratch = Path(scratch)
    primary = scratch / PRIMARY_NAME
    recovery = scratch / RECOVERY_NAME

    _effective_max_recovery_wait_s: float = (
        min(timeout_s, MAX_RECOVERY_WAIT_S) if max_recovery_wait_s is None else max_recovery_wait_s
    )

    deadline = time.monotonic() + timeout_s
    recovery_seen = 0.0
    backoff = BACKOFF_INITIAL_S

    while True:
        # STEP A — recovery-mutex check MUST precede every O_EXCL attempt.
        if recovery.exists():
            if recovery_seen > _effective_max_recovery_wait_s:
                raise LockTimeoutError(
                    f"recovery mutex held longer than {_effective_max_recovery_wait_s}s at {recovery}"
                )
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"timeout waiting for recovery mutex at {recovery}")
            time.sleep(backoff)
            recovery_seen += backoff
            backoff = min(backoff * 2, BACKOFF_MAX_S)
            continue

        # STEP B — atomic O_EXCL.
        try:
            token = secrets.token_hex(16)
            record = current_owner_record(owner_token=token)
            fd = os.open(
                str(primary),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            try:
                _write_owner_record(fd, record)
                os.fsync(fd)
                _durable_fs.fsync_parent_dir(primary.parent)
            except OSError:
                # If we fail to seal the record, drop the partially-written
                # primary so we don't leave a half-baked lock to confuse
                # the next acquirer.
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(primary)
                except OSError:
                    pass
                raise
            return LockHandle(fd=fd, path=primary, owner_token=token, scratch=scratch)
        except FileExistsError:
            pass

        # STEP C — classify existing primary.
        try:
            existing = _read_owner_record(primary)
        except FileNotFoundError:
            # Disappeared between O_EXCL and read; loop to STEP A.
            continue

        verdict = classify(
            existing,
            current_hostname=_current_hostname(),
            current_boot_id=_current_boot_id(),
            proc_lookup=_proc_lookup,
        )
        if verdict == "ambiguous":
            raise LockHeldError(
                "lock state ambiguous; run `harness session unlock --force` after manual inspection"
            )
        if verdict in ("live", "foreign_host"):
            if time.monotonic() >= deadline:
                raise LockTimeoutError(
                    f"timeout waiting on {verdict} lock owner at {primary}"
                )
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
            continue

        # STEP D — verdict == "stale". Attempt recovery and re-enter STEP A.
        try_recover(scratch, observed_token=existing.get("owner_token", ""), audit_path=audit_path)
        # S01-C review-fix (P-note): if try_recover() is a no-op because a
        # racing recoverer holds the mutex (or the primary record doesn't
        # match `observed_token` after a re-acquire window), the loop
        # would spin forever without a deadline check. Honour the caller's
        # `timeout_s` here so the stale-recovery path terminates.
        if time.monotonic() >= deadline:
            raise LockTimeoutError(
                f"timeout while attempting stale-lock recovery at {primary}"
            )
        time.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_S)


def release_primary(handle: LockHandle) -> None:
    """Idempotent unlink + close. Safe to call twice (e.g. defensive finally)."""
    if handle._released:
        return
    handle._released = True
    try:
        os.close(handle.fd)
    except OSError:
        pass
    try:
        os.unlink(handle.path)
    except FileNotFoundError:
        pass
    try:
        _durable_fs.fsync_parent_dir(handle.path.parent)
    except _durable_fs.DurableFsError:
        # The lock file is already gone; missing parent fsync is not fatal.
        pass


# ---------------------------------------------------------------------------
# try_recover
# ---------------------------------------------------------------------------


def try_recover(
    scratch: Union[str, "os.PathLike[str]"],
    *,
    observed_token: str,
    audit_path: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> None:
    """Single recovery attempt. Mutex acquired/released; caller loops STEP A."""
    scratch = Path(scratch)
    primary = scratch / PRIMARY_NAME
    recovery = scratch / RECOVERY_NAME

    try:
        rfd = os.open(
            str(recovery),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        return  # Another recoverer is in flight; STEP A will see this.

    try:
        # Validation point (i).
        try:
            record_i = _read_owner_record(primary)
        except FileNotFoundError:
            return  # Clean release happened between O_EXCL fail and now.
        if record_i.get("owner_token") != observed_token:
            return
        if classify(
            record_i,
            current_hostname=_current_hostname(),
            current_boot_id=_current_boot_id(),
            proc_lookup=_proc_lookup,
        ) != "stale":
            return

        # Validation point (ii) — IMMEDIATELY before unlink.
        try:
            record_ii = _read_owner_record(primary)
        except FileNotFoundError:
            return
        if record_ii.get("owner_token") != record_i.get("owner_token"):
            return

        # Safe to unlink.
        try:
            os.unlink(primary)
            _durable_fs.fsync_parent_dir(primary.parent)
        except PermissionError as exc:
            raise LockRecoveryError(
                f"unlink({primary!r}) refused — likely Windows AV holding handle: {exc}"
            ) from exc

        if audit_path is not None:
            _audit.audit_append(
                {
                    "verb": "lock.recovered",
                    "at": _now_iso(),
                    "by": "harness.phase_lock",
                    "reclaimed_owner_token": record_ii["owner_token"],
                    "reclaimed_pid": record_ii.get("pid"),
                    "reclaimed_hostname": record_ii.get("hostname"),
                },
                audit_path=Path(audit_path),
            )
    finally:
        try:
            os.close(rfd)
        except OSError:
            pass
        try:
            os.unlink(recovery)
            _durable_fs.fsync_parent_dir(recovery.parent)
        except FileNotFoundError:
            pass
        except _durable_fs.DurableFsError:
            pass


__all__ = [
    "LockError",
    "LockHeldError",
    "LockTimeoutError",
    "LockRecoveryError",
    "LockHandle",
    "LOCK_VERDICTS",
    "PRIMARY_NAME",
    "RECOVERY_NAME",
    "MAX_RECOVERY_WAIT_S",
    "BACKOFF_INITIAL_S",
    "BACKOFF_MAX_S",
    "current_owner_record",
    "classify",
    "acquire_primary",
    "release_primary",
    "try_recover",
]
