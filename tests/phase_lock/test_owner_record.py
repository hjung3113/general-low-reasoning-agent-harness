"""S01-C: owner-record write/read/roundtrip semantics (design §3.7)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from lib import phase_lock


def test_current_owner_record_shape_contains_required_fields():
    rec = phase_lock.current_owner_record()
    for key in (
        "pid",
        "hostname",
        "process_start_time",
        "boot_id",
        "monotonic_acquired_at",
        "acquired_iso",
        "owner_token",
    ):
        assert key in rec, f"owner record missing required field: {key}"


def test_current_owner_record_token_is_128_bit_hex():
    rec = phase_lock.current_owner_record()
    assert isinstance(rec["owner_token"], str)
    assert len(rec["owner_token"]) == 32  # 128 bits / 4 bits-per-hex
    int(rec["owner_token"], 16)  # raises on non-hex


def test_current_owner_record_pid_is_self():
    rec = phase_lock.current_owner_record()
    assert rec["pid"] == os.getpid()


def test_current_owner_record_acquired_iso_z_terminated():
    rec = phase_lock.current_owner_record()
    assert rec["acquired_iso"].endswith("Z")
    assert "T" in rec["acquired_iso"]


def test_read_owner_record_round_trips(tmp_path: Path):
    fd = os.open(str(tmp_path / "lock"), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    rec = phase_lock.current_owner_record()
    phase_lock._write_owner_record(fd, rec)
    os.close(fd)
    back = phase_lock._read_owner_record(tmp_path / "lock")
    assert back == rec


def test_read_owner_record_raises_file_not_found(tmp_path: Path):
    import pytest

    with pytest.raises(FileNotFoundError):
        phase_lock._read_owner_record(tmp_path / "nope")


def test_current_owner_record_tolerates_psutil_error_during_lookup(monkeypatch):
    """v0.7.0 review CRIT WF-3: if psutil raises NoSuchProcess during the
    initial self-lookup (race with rapid PID reuse, container weirdness),
    current_owner_record() MUST still produce a record but with
    process_start_time=None — NOT 0.0. The prior 0.0 sentinel caused
    classify() to falsely report a live holder as 'stale', letting
    try_recover unlink the lock under an active owner."""
    import psutil

    def fake_lookup(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(phase_lock, "_proc_lookup", fake_lookup)
    rec = phase_lock.current_owner_record()
    # Did not raise; record is well-formed.
    assert rec["pid"] == os.getpid()
    # Sentinel changed: None signals "psutil failed at acquire time", which
    # classify() must treat as ambiguous (never stale).
    assert rec["process_start_time"] is None


def test_write_owner_record_serializes_canonically(tmp_path: Path):
    """Canonical JSON: sorted keys, no BOM, LF newline. Reviewer
    cross-checks against §2.3 (rfc8785) in the audit chain — for the
    lock file the lighter `json.dumps(sort_keys=True)` is sufficient
    (no hash chain participation)."""
    fd = os.open(str(tmp_path / "lock"), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    rec = {"b": 2, "a": 1}
    phase_lock._write_owner_record(fd, rec)
    os.close(fd)
    text = (tmp_path / "lock").read_text(encoding="utf-8")
    # sorted keys: "a" precedes "b" lexicographically.
    assert text.index("\"a\"") < text.index("\"b\"")
    # No BOM.
    assert not text.startswith("﻿")
