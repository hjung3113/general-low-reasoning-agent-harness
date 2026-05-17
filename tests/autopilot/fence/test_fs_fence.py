"""Tests for scripts/lib/fs_fence.py — check_write_path + enforce_write.

RED phase: written before implementation (TDD discipline).
Spec: §5.1 (filesystem fence + allowed_paths), §5.0 enforcement scope,
      §3.4 exit 4.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from scripts.lib.fs_fence import (
    FenceDenyError,
    FenceCheckResult,
    check_write_path,
    enforce_write,
)
from scripts.lib.phase_lock import acquire_primary, release_primary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    *,
    execution_mode: str = "phase_autopilot",
    allowed_paths: list | None = None,
) -> dict:
    return {
        "execution_mode": execution_mode,
        "allowed_paths": allowed_paths,
    }


def _make_audit_file(tmp_path: Path) -> Path:
    audit = tmp_path / ".harness" / "audit.log"
    audit.parent.mkdir(parents=True, exist_ok=True)
    return audit


def _make_lock_handle(scratch: Path):
    """Create a minimal real LockHandle for enforce_write tests."""
    return acquire_primary(scratch)


# ---------------------------------------------------------------------------
# check_write_path — manual mode
# ---------------------------------------------------------------------------


def test_check_write_path_manual_mode_always_allowed(tmp_path: Path):
    """Manual mode: fence is disabled regardless of allowed_paths."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(execution_mode="manual", allowed_paths=[])
    result = check_write_path("scripts/some_file.py", anchor=anchor, state=state)
    assert isinstance(result, FenceCheckResult)
    assert result.allowed is True
    assert result.reason == "fence_disabled_manual_mode"


def test_check_write_path_manual_mode_allowed_paths_none(tmp_path: Path):
    """Manual mode bypass works even when allowed_paths=None."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(execution_mode="manual", allowed_paths=None)
    result = check_write_path("scripts/foo.py", anchor=anchor, state=state)
    assert result.allowed is True
    assert result.reason == "fence_disabled_manual_mode"


# ---------------------------------------------------------------------------
# check_write_path — autopilot + allowed_paths=None (fail-closed)
# ---------------------------------------------------------------------------


def test_check_write_path_autopilot_allowed_paths_none_fail_closed(tmp_path: Path):
    """Autopilot + allowed_paths=None → fail-closed (not_in_allowed_paths)."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(execution_mode="phase_autopilot", allowed_paths=None)
    result = check_write_path("scripts/foo.py", anchor=anchor, state=state)
    assert result.allowed is False
    # The spec says fail-CLOSED if execution_mode != manual AND allowed_paths is None


def test_check_write_path_autopilot_allowed_paths_empty_fail_closed(tmp_path: Path):
    """Autopilot + allowed_paths=[] → fail-closed."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(execution_mode="phase_autopilot", allowed_paths=[])
    result = check_write_path("scripts/foo.py", anchor=anchor, state=state)
    assert result.allowed is False
    assert result.reason == "not_in_allowed_paths"


# ---------------------------------------------------------------------------
# check_write_path — autopilot + allowed prefix match
# ---------------------------------------------------------------------------


def test_check_write_path_autopilot_path_under_allowed_prefix(tmp_path: Path):
    """Autopilot + path under allowed prefix → allowed."""
    anchor = tmp_path / "anchor"
    (anchor / "scripts").mkdir(parents=True)
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/", ".harness/"],
    )
    result = check_write_path("scripts/lib/foo.py", anchor=anchor, state=state)
    assert result.allowed is True
    assert result.reason == "allowed"


def test_check_write_path_autopilot_exact_prefix_match(tmp_path: Path):
    """Path exactly at the prefix boundary → allowed."""
    anchor = tmp_path / "anchor"
    (anchor / ".harness").mkdir(parents=True)
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=[".harness/"],
    )
    result = check_write_path(".harness/audit.log", anchor=anchor, state=state)
    assert result.allowed is True
    assert result.reason == "allowed"


# ---------------------------------------------------------------------------
# check_write_path — autopilot + path outside allowed prefixes
# ---------------------------------------------------------------------------


def test_check_write_path_autopilot_path_outside_allowed_prefixes(tmp_path: Path):
    """Autopilot + path outside allowed prefixes → not_in_allowed_paths."""
    anchor = tmp_path / "anchor"
    (anchor / "scripts").mkdir(parents=True)
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )
    result = check_write_path("docs/secret.md", anchor=anchor, state=state)
    assert result.allowed is False
    assert result.reason == "not_in_allowed_paths"


def test_check_write_path_autopilot_chain_autopilot_also_checked(tmp_path: Path):
    """chain_autopilot mode also triggers fence checks."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(execution_mode="chain_autopilot", allowed_paths=[])
    result = check_write_path("scripts/foo.py", anchor=anchor, state=state)
    assert result.allowed is False


# ---------------------------------------------------------------------------
# check_write_path — symlink in path → symlink_in_path
# ---------------------------------------------------------------------------


def test_check_write_path_autopilot_symlink_in_path(tmp_path: Path):
    """Symlink in path components → FenceCheckResult(False, 'symlink_in_path')."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    real_dir = tmp_path / "real_scripts"
    real_dir.mkdir()
    # Create a symlink inside anchor pointing to real_dir
    sym = anchor / "symlink_dir"
    sym.symlink_to(real_dir)
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["symlink_dir/"],
    )
    result = check_write_path("symlink_dir/foo.py", anchor=anchor, state=state)
    assert result.allowed is False
    assert result.reason == "symlink_in_path"


# ---------------------------------------------------------------------------
# check_write_path — '..' traversal → path_outside_anchor
# ---------------------------------------------------------------------------


def test_check_write_path_autopilot_dotdot_traversal(tmp_path: Path):
    """'..' component → FenceCheckResult(False, 'path_outside_anchor')."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["../"],
    )
    result = check_write_path("../escape.py", anchor=anchor, state=state)
    assert result.allowed is False
    assert result.reason == "path_outside_anchor"


def test_check_write_path_autopilot_dotdot_in_middle(tmp_path: Path):
    """'..' embedded in path → path_outside_anchor."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    (anchor / "scripts").mkdir()
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )
    result = check_write_path("scripts/../../../etc/passwd", anchor=anchor, state=state)
    assert result.allowed is False
    assert result.reason == "path_outside_anchor"


# ---------------------------------------------------------------------------
# FenceDenyError shape
# ---------------------------------------------------------------------------


def test_fence_deny_error_has_exit_code_4():
    err = FenceDenyError(
        path="some/path.py",
        reason="not_in_allowed_paths",
        allowed_paths=["scripts/"],
    )
    assert err.exit_code == 4
    assert err.path == "some/path.py"
    assert err.reason == "not_in_allowed_paths"
    assert err.allowed_paths == ["scripts/"]
    assert isinstance(err, OSError)


# ---------------------------------------------------------------------------
# enforce_write — happy path
# ---------------------------------------------------------------------------


def test_enforce_write_happy_path_returns_none(tmp_path: Path):
    """enforce_write returns None when path is allowed."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    anchor = tmp_path
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )
    (tmp_path / "scripts").mkdir()

    lock = _make_lock_handle(scratch)
    try:
        result = enforce_write(
            "scripts/lib/foo.py",
            anchor=anchor,
            state=state,
            lock_handle=lock,
            audit_path=audit_path,
            actor="phase.set",
        )
        assert result is None
    finally:
        release_primary(lock)

    # No audit row should be emitted for the happy path
    if audit_path.exists():
        lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
        for line in lines:
            entry = json.loads(line)
            assert entry.get("verb") != "autopilot.fence.deny"


def test_enforce_write_manual_mode_always_passes(tmp_path: Path):
    """Manual mode: enforce_write always returns None."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    anchor = tmp_path
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    state = _make_state(execution_mode="manual", allowed_paths=[])

    lock = _make_lock_handle(scratch)
    try:
        result = enforce_write(
            "any/path.py",
            anchor=anchor,
            state=state,
            lock_handle=lock,
            audit_path=audit_path,
            actor="phase.set",
        )
        assert result is None
    finally:
        release_primary(lock)


# ---------------------------------------------------------------------------
# enforce_write — deny path: raises FenceDenyError + audit row
# ---------------------------------------------------------------------------


def test_enforce_write_deny_raises_fence_deny_error(tmp_path: Path):
    """Denied path raises FenceDenyError with exit_code=4."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    anchor = tmp_path
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock_handle(scratch)
    try:
        with pytest.raises(FenceDenyError) as exc_info:
            enforce_write(
                "docs/secret.md",
                anchor=anchor,
                state=state,
                lock_handle=lock,
                audit_path=audit_path,
                actor="phase.set",
            )
    finally:
        release_primary(lock)

    err = exc_info.value
    assert err.exit_code == 4
    assert err.path == "docs/secret.md"
    assert err.reason == "not_in_allowed_paths"


def test_enforce_write_deny_emits_audit_row(tmp_path: Path):
    """Denied path emits autopilot.fence.deny audit row with required fields."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    anchor = tmp_path
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock_handle(scratch)
    try:
        with pytest.raises(FenceDenyError):
            enforce_write(
                "docs/secret.md",
                anchor=anchor,
                state=state,
                lock_handle=lock,
                audit_path=audit_path,
                actor="phase.approve",
            )
    finally:
        release_primary(lock)

    assert audit_path.exists()
    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    assert lines, "Expected at least one audit line"
    deny_entries = [json.loads(l) for l in lines if json.loads(l).get("verb") == "autopilot.fence.deny"]
    assert len(deny_entries) == 1, "Expected exactly one fence.deny entry"

    entry = deny_entries[0]
    assert entry["verb"] == "autopilot.fence.deny"
    assert entry["path"] == "docs/secret.md"
    assert entry["reason"] == "not_in_allowed_paths"
    assert entry["allowed_paths"] == ["scripts/"]
    assert entry["actor"] == "phase.approve"
    assert "at" in entry


def test_enforce_write_deny_audit_path_truncated_over_256(tmp_path: Path):
    """Paths longer than 256 chars are truncated in the audit entry."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    anchor = tmp_path
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    long_path = "docs/" + "x" * 300 + ".md"
    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock_handle(scratch)
    try:
        with pytest.raises(FenceDenyError):
            enforce_write(
                long_path,
                anchor=anchor,
                state=state,
                lock_handle=lock,
                audit_path=audit_path,
                actor="phase.set",
            )
    finally:
        release_primary(lock)

    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    deny_entries = [json.loads(l) for l in lines if json.loads(l).get("verb") == "autopilot.fence.deny"]
    assert deny_entries
    # path in audit should be at most 256 chars
    assert len(deny_entries[0]["path"]) <= 256
