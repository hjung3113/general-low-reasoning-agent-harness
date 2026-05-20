"""T13 NEW-8 — `verify --audit` and `harness check` error wording disambiguation.

Spec (v095-PLAN.md §3.3, v095-IMPL.md T13):
  Three failure modes MUST produce distinct error strings:
  1. audit.log does not exist at all
       → message contains "audit log absent"
  2. audit.log exists but is unreadable (permission denied / corrupted header)
       → message contains "audit log unreachable" (plus the path)
  3. audit.log readable but tail's after_sha256 != state file sha256
       → message contains "audit chain tail does not match state"

All three currently conflate to "audit_log_missing" or a generic
"chain verification failed" message (NEW-8 evidence in smoke-B report).
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _make_args(fixture_dir=None) -> types.SimpleNamespace:
    args = types.SimpleNamespace()
    args.verify_fixture = str(fixture_dir) if fixture_dir is not None else None
    return args


def _write_advanced_state(tmp_path: Path) -> None:
    """Write a non-baseline state so BUG-1 path activates."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    state = {
        "phase": "done",
        "approved": False,
        "plan_id": "plan-abc",
        "execution_mode": "manual",
        "automation_mode": "manual",
        "updated_by": "test-agent",
        "updated_at": "2026-05-21T00:00:00Z",
    }
    (scratch / "phase-state.json").write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


def _write_installed_manifest(harness_dir: Path) -> None:
    """Write a minimal installed-manifest.json so Case 3 gate activates."""
    (harness_dir / "installed-manifest.json").write_text(
        '{"version": "0.0.0-test", "files": {}}', encoding="utf-8"
    )


def _write_valid_audit_and_state(tmp_path: Path) -> None:
    """Write a valid audit log and matching state."""
    from lib.audit import audit_append

    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    audit_path = harness_dir / "audit.log"

    _write_advanced_state(tmp_path)
    state_path = tmp_path / ".scratch" / "phase-state.json"
    state_bytes = state_path.read_bytes()
    import hashlib
    state_sha = hashlib.sha256(state_bytes).hexdigest()

    audit_append(
        {
            "verb": "phase.set",
            "at": "2026-05-21T00:00:00Z",
            "before_sha256": "",
            "after_sha256": state_sha,
        },
        audit_path=audit_path,
    )


# ---------------------------------------------------------------------------
# Case 1: audit log absent (file does not exist at all)
# ---------------------------------------------------------------------------


class TestAuditLogAbsent:
    def test_absent_exits_nonzero(self, tmp_path):
        """No audit.log + advanced state → non-zero exit."""
        from lib.audit_verify_cli import cmd_verify_audit

        _write_advanced_state(tmp_path)
        # .harness/ dir exists but audit.log is absent
        (tmp_path / ".harness").mkdir()

        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc != 0, f"Expected non-zero; got {rc}"

    def test_absent_message_says_audit_log_absent(self, tmp_path, capsys):
        """No audit.log + advanced state → stderr says 'audit log absent'."""
        from lib.audit_verify_cli import cmd_verify_audit

        _write_advanced_state(tmp_path)
        (tmp_path / ".harness").mkdir()

        args = _make_args()
        cmd_verify_audit(args, tmp_path)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "audit log absent" in combined.lower(), (
            f"Expected 'audit log absent' in error output; got:\n{combined}"
        )


# ---------------------------------------------------------------------------
# Case 2: audit log unreachable (permission denied or unreadable)
# ---------------------------------------------------------------------------


class TestAuditLogUnreachable:
    @pytest.mark.skipif(os.name == "nt", reason="chmod not reliable on Windows")
    def test_unreadable_exits_nonzero(self, tmp_path):
        """audit.log exists but unreadable (mode 000) → non-zero exit."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-21T00:00:00Z"}, audit_path=audit_path)

        _write_advanced_state(tmp_path)

        # Make unreadable
        audit_path.chmod(0o000)
        try:
            args = _make_args()
            rc = cmd_verify_audit(args, tmp_path)
            assert rc != 0, f"Expected non-zero for unreadable audit.log; got {rc}"
        finally:
            audit_path.chmod(0o644)

    @pytest.mark.skipif(os.name == "nt", reason="chmod not reliable on Windows")
    def test_unreadable_message_says_unreachable(self, tmp_path, capsys):
        """audit.log unreadable → stderr says 'audit log unreachable'."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-21T00:00:00Z"}, audit_path=audit_path)

        _write_advanced_state(tmp_path)

        audit_path.chmod(0o000)
        try:
            args = _make_args()
            cmd_verify_audit(args, tmp_path)
        finally:
            audit_path.chmod(0o644)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "unreachable" in combined.lower(), (
            f"Expected 'unreachable' in error output; got:\n{combined}"
        )


# ---------------------------------------------------------------------------
# Case 3: audit chain tail does not match state hash
# ---------------------------------------------------------------------------


class TestAuditChainTailMismatch:
    def test_tail_mismatch_exits_nonzero(self, tmp_path):
        """audit.log readable, tail after_sha256 != state sha256 → non-zero exit."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        _write_advanced_state(tmp_path)

        # Write audit entry with a sha that does NOT match the state file
        audit_append(
            {
                "verb": "phase.set",
                "at": "2026-05-21T00:00:00Z",
                "before_sha256": "",
                "after_sha256": "a" * 64,  # wrong sha
            },
            audit_path=audit_path,
        )

        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc != 0, f"Expected non-zero for tail hash mismatch; got {rc}"

    def test_tail_mismatch_message_says_does_not_match_state(self, tmp_path, capsys):
        """tail mismatch → stderr says 'audit chain tail does not match state'."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        _write_advanced_state(tmp_path)

        audit_append(
            {
                "verb": "phase.set",
                "at": "2026-05-21T00:00:00Z",
                "before_sha256": "",
                "after_sha256": "b" * 64,  # wrong sha
            },
            audit_path=audit_path,
        )

        args = _make_args()
        cmd_verify_audit(args, tmp_path)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # Must be clearly distinct from "absent" or "unreachable"
        assert "does not match state" in combined.lower() or "chain tail" in combined.lower() or "state hash" in combined.lower(), (
            f"Expected 'does not match state' or 'chain tail' in output; got:\n{combined}"
        )

    def test_tail_mismatch_message_distinct_from_absent(self, tmp_path, capsys):
        """tail mismatch error must NOT say 'absent' (regression: was conflated with missing)."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        _write_advanced_state(tmp_path)
        audit_append(
            {
                "verb": "phase.set",
                "at": "2026-05-21T00:00:00Z",
                "before_sha256": "",
                "after_sha256": "c" * 64,
            },
            audit_path=audit_path,
        )

        args = _make_args()
        cmd_verify_audit(args, tmp_path)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "absent" not in combined.lower(), (
            f"Tail-mismatch error must not say 'absent' (conflation regression); got:\n{combined}"
        )

    def test_absent_message_distinct_from_tail_mismatch(self, tmp_path, capsys):
        """Absent log error must NOT say 'does not match state'."""
        from lib.audit_verify_cli import cmd_verify_audit

        _write_advanced_state(tmp_path)
        (tmp_path / ".harness").mkdir()

        args = _make_args()
        cmd_verify_audit(args, tmp_path)

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "does not match state" not in combined.lower(), (
            f"Absent-log error must not say 'does not match state'; got:\n{combined}"
        )
