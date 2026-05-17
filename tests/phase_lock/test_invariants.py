"""S01-C: §3.7 invariants i1..i4 (design page anchor).

i1: No code path acquires primary without first stat'ing recovery (STEP A).
i2: Recoverer NEVER replaces primary; only `os.unlink()` after two-point
    token validation.
i3: `try_recover` releases recovery mutex on every return path.
i4: After recovery, recoverer re-enters STEP A (does NOT inherit lock).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from lib import phase_lock


# ---------------------------------------------------------------------------
# i1 — RECOVERY mutex check precedes every O_EXCL attempt.
# ---------------------------------------------------------------------------


def test_i1_recovery_check_precedes_oexcl_attempt(scratch: Path, monkeypatch):
    """Plant a recovery mutex; acquire_primary must back off and timeout
    rather than racing into O_EXCL."""
    recovery = scratch / "phase-state.json.lock.recovery"
    recovery.write_text("{}", encoding="utf-8")

    open_calls = []
    real_open = os.open

    def spy_open(path, flags, mode=0o777):
        open_calls.append((str(path), flags))
        return real_open(path, flags, mode)

    monkeypatch.setattr(phase_lock.os, "open", spy_open)

    with pytest.raises(phase_lock.LockTimeoutError):
        phase_lock.acquire_primary(scratch, timeout_s=0.2)

    # No os.open with O_EXCL on the PRIMARY path was ever issued.
    primary = str(scratch / "phase-state.json.lock")
    excl_primary_opens = [
        c for c in open_calls if c[0] == primary and (c[1] & os.O_EXCL)
    ]
    assert excl_primary_opens == [], "i1 violation: O_EXCL on primary fired while recovery mutex existed"


# ---------------------------------------------------------------------------
# i2 — recoverer never replaces primary; only unlinks after two-point check.
# ---------------------------------------------------------------------------


def test_i2_try_recover_only_unlinks_never_writes_primary(scratch: Path, monkeypatch):
    """Plant a stale primary; assert try_recover unlinks it (never writes)."""
    primary = scratch / "phase-state.json.lock"
    stale = {
        "pid": 999_999,  # synthetic dead pid (caught by proc_lookup mock below)
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "a" * 32,
    }
    primary.write_text(json.dumps(stale, sort_keys=True) + "\n", encoding="utf-8")

    writes_to_primary = []
    real_open = os.open

    def spy_open(path, flags, mode=0o777):
        if str(path) == str(primary) and (flags & os.O_WRONLY):
            writes_to_primary.append((str(path), flags))
        return real_open(path, flags, mode)

    monkeypatch.setattr(phase_lock.os, "open", spy_open)
    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    phase_lock.try_recover(scratch, observed_token="a" * 32)

    assert not primary.exists(), "i2 violation: primary not unlinked"
    assert writes_to_primary == [], "i2 violation: primary was written by recoverer"


# ---------------------------------------------------------------------------
# i3 — try_recover releases the recovery mutex on every return path.
# ---------------------------------------------------------------------------


def test_i3_try_recover_releases_recovery_mutex_on_clean_release(scratch: Path, monkeypatch):
    """Primary vanishes between recovery mutex acquire and validation
    (clean release): recoverer returns immediately AND deletes the
    recovery mutex."""
    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    # No primary file at all -> "clean release" branch.
    phase_lock.try_recover(scratch, observed_token="a" * 32)
    assert not (scratch / "phase-state.json.lock.recovery").exists()


def test_i3_try_recover_releases_recovery_mutex_on_token_mismatch(scratch: Path, monkeypatch):
    """A different observed_token from the disk record: recoverer must
    NOT unlink primary, but MUST still release the recovery mutex."""
    primary = scratch / "phase-state.json.lock"
    rec = {
        "pid": 1,
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "b" * 32,
    }
    primary.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    phase_lock.try_recover(scratch, observed_token="a" * 32)
    assert primary.exists(), "i2 cross-check: primary should NOT be unlinked on token mismatch"
    assert not (scratch / "phase-state.json.lock.recovery").exists(), \
        "i3 violation: recovery mutex not released on token-mismatch path"


# ---------------------------------------------------------------------------
# i4 — after recovery, do NOT inherit lock; re-enter STEP A on next loop.
# ---------------------------------------------------------------------------


def test_i4_try_recover_returns_no_lock_handle(scratch: Path, monkeypatch):
    """The public signature is `try_recover(...) -> None`. Acquirers must
    loop back to STEP A after this returns to retry the O_EXCL path."""
    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))
    result = phase_lock.try_recover(scratch, observed_token="a" * 32)
    assert result is None, "i4 violation: recoverer returned a lock handle"
