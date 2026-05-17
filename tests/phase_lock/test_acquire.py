"""S01-C: acquire_primary happy path + contended paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from lib import phase_lock


def test_acquire_primary_succeeds_on_empty_scratch(scratch: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=1.0)
    try:
        assert (scratch / "phase-state.json.lock").exists()
        assert handle.fd >= 0
        assert handle.path == scratch / "phase-state.json.lock"
        assert len(handle.owner_token) == 32
    finally:
        phase_lock.release_primary(handle)


def test_release_primary_unlinks_and_closes(scratch: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=1.0)
    phase_lock.release_primary(handle)
    assert not (scratch / "phase-state.json.lock").exists()
    # fd should already be closed; re-close should not crash via release.


def test_double_release_is_safe(scratch: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=1.0)
    phase_lock.release_primary(handle)
    phase_lock.release_primary(handle)  # idempotent


def test_acquire_primary_blocks_when_live_lock_exists(scratch: Path, monkeypatch):
    """Live (current-process) lock held → second acquire must time out."""
    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (True, 1000.0))

    first = phase_lock.acquire_primary(scratch, timeout_s=1.0)
    try:
        # Plant a "live" record (matching boot+host+pid alive+start match).
        primary = scratch / "phase-state.json.lock"
        rec = json.loads(primary.read_text(encoding="utf-8"))
        rec["process_start_time"] = 1000.0
        primary.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")

        with pytest.raises(phase_lock.LockTimeoutError):
            phase_lock.acquire_primary(scratch, timeout_s=0.2)
    finally:
        phase_lock.release_primary(first)


def test_acquire_primary_exits_3_class_on_foreign_host(scratch: Path, monkeypatch):
    """Foreign-host lock held → never auto-recover; raise LockHeldError."""
    primary = scratch / "phase-state.json.lock"
    rec = {
        "pid": 999,
        "hostname": "other-host",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "f" * 32,
    }
    primary.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (True, 1.0))

    with pytest.raises(phase_lock.LockTimeoutError):
        phase_lock.acquire_primary(scratch, timeout_s=0.2)


def test_acquire_primary_recovers_stale_and_succeeds(scratch: Path, monkeypatch):
    """Stale lock present → recoverer unlinks → acquirer retries STEP A → succeeds."""
    primary = scratch / "phase-state.json.lock"
    stale_rec = {
        "pid": 999_999,
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "a" * 32,
    }
    primary.write_text(json.dumps(stale_rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        assert handle.owner_token != "a" * 32  # new token, not the stale one
    finally:
        phase_lock.release_primary(handle)


def test_acquire_primary_raises_on_ambiguous_classification(scratch: Path, monkeypatch):
    primary = scratch / "phase-state.json.lock"
    rec = {
        "pid": 1,
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "a" * 32,
    }
    primary.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")

    def raising_lookup(pid):
        raise PermissionError("no /proc")

    monkeypatch.setattr(phase_lock, "_proc_lookup", raising_lookup)

    with pytest.raises(phase_lock.LockHeldError, match="ambiguous"):
        phase_lock.acquire_primary(scratch, timeout_s=0.5)


def test_acquire_primary_times_out_when_stale_recovery_keeps_racing(
    scratch: Path, monkeypatch
):
    """S01-C review-fix (P-note): if every try_recover() call no-ops because
    another (mock) recoverer keeps the recovery mutex around, the
    acquire_primary loop MUST eventually hit `deadline` rather than
    spinning forever. Pins the deadline contract for the stale-recovery
    loop."""
    primary = scratch / "phase-state.json.lock"
    stale_rec = {
        "pid": 999_999,
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "a" * 32,
    }
    primary.write_text(json.dumps(stale_rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    # Pin the recovery path to do nothing — primary stays in place forever.
    def no_op_recover(scratch, *, observed_token, audit_path=None):
        return None

    monkeypatch.setattr(phase_lock, "try_recover", no_op_recover)

    with pytest.raises(phase_lock.LockTimeoutError):
        phase_lock.acquire_primary(scratch, timeout_s=0.3)


def test_acquire_primary_recover_emits_lock_recovered_audit_when_audit_path_set(
    scratch: Path, monkeypatch, tmp_path: Path
):
    primary = scratch / "phase-state.json.lock"
    stale_rec = {
        "pid": 999_999,
        "hostname": "host-a",
        "process_start_time": 1.0,
        "boot_id": "boot-X",
        "monotonic_acquired_at": 0.0,
        "acquired_iso": "2026-05-17T00:00:00Z",
        "owner_token": "a" * 32,
    }
    primary.write_text(json.dumps(stale_rec, sort_keys=True) + "\n", encoding="utf-8")

    monkeypatch.setattr(phase_lock, "_current_hostname", lambda: "host-a")
    monkeypatch.setattr(phase_lock, "_current_boot_id", lambda: "boot-X")
    monkeypatch.setattr(phase_lock, "_proc_lookup", lambda pid: (False, None))

    audit_path = tmp_path / ".harness" / "audit.log"
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0, audit_path=audit_path)
    try:
        entries = [
            json.loads(ln)
            for ln in audit_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        recovered = [e for e in entries if e.get("verb") == "lock.recovered"]
        assert len(recovered) == 1
        assert recovered[0]["reclaimed_owner_token"] == "a" * 32
    finally:
        phase_lock.release_primary(handle)
