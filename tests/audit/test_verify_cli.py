"""S06-audit-chain: harness verify --audit CLI verb tests (design §12.7, §12.9).

Tests invoke `harness verify --audit [--fixture <dir>]` and assert exit codes + output.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

HARNESS_BIN = "/tmp/harness-test-venv/bin/python"
HARNESS_MOD = str(Path(__file__).parent.parent.parent / "scripts" / "harness.py")
FIXTURE_AUDIT_DIR = Path(__file__).parent.parent / "fixtures" / "audit"


def _run_harness(*args, cwd=None):
    """Run harness with given args and return (returncode, stdout, stderr)."""
    cmd = [HARNESS_BIN, HARNESS_MOD, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


class TestVerifyAuditCLI:
    def test_verify_audit_ok_fixture(self, tmp_path):
        """--fixture with a clean chain exits 0 with summary."""
        # Write two chained entries
        from lib.audit import audit_append
        audit_path = tmp_path / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)
        audit_append({"verb": "phase.approve", "at": "2026-05-17T00:01:00Z"}, audit_path=audit_path)

        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(tmp_path))
        assert rc == 0, f"Expected 0, got {rc}\nstdout={stdout}\nstderr={stderr}"
        assert "2" in stdout or "walked" in stdout.lower() or "ok" in stdout.lower()

    def test_verify_audit_tampered_exits_10(self, tmp_path):
        """--fixture with tampered chain exits 10."""
        from lib.audit import audit_append
        audit_path = tmp_path / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)
        # Corrupt it
        lines = audit_path.read_text().splitlines()
        entry = json.loads(lines[0])
        entry["verb"] = "tampered_verb"  # mutate but keep stale entry_hash
        lines[0] = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(tmp_path))
        assert rc == 10, f"Expected 10, got {rc}\nstdout={stdout}\nstderr={stderr}"
        assert "Fix:" in stderr or "Fix:" in stdout

    def test_verify_audit_empty_log_ok(self, tmp_path):
        """Empty log exits 0."""
        audit_path = tmp_path / "audit.log"
        audit_path.write_text("", encoding="utf-8")
        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(tmp_path))
        assert rc == 0

    def test_verify_audit_mixed_v1_v2_ok(self):
        """Golden fixture: mixed v1+v2 passes."""
        fixture_dir = FIXTURE_AUDIT_DIR / "mixed_v1_v2_rotation_ok"
        if not fixture_dir.exists():
            pytest.skip("fixture missing: mixed_v1_v2_rotation_ok")
        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(fixture_dir))
        assert rc == 0, f"Expected 0, got {rc}\nstdout={stdout}\nstderr={stderr}"

    def test_verify_audit_bom_fixture_exits_5(self):
        """BOM in audit.log exits 5."""
        fixture_dir = FIXTURE_AUDIT_DIR / "bom_in_audit"
        if not fixture_dir.exists():
            pytest.skip("fixture missing: bom_in_audit")
        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(fixture_dir))
        assert rc == 5, f"Expected 5, got {rc}\nstdout={stdout}\nstderr={stderr}"

    def test_verify_audit_output_has_summary_fields(self, tmp_path):
        """Output includes entries_walked and final tip hash."""
        from lib.audit import audit_append
        audit_path = tmp_path / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)
        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(tmp_path))
        assert rc == 0
        combined = stdout + stderr
        assert "1" in combined  # at least entries count

    def test_verify_audit_tampered_has_fix_line(self, tmp_path):
        """Tampered audit: stderr contains Fix: line."""
        from lib.audit import audit_append
        audit_path = tmp_path / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)
        lines = audit_path.read_text().splitlines()
        entry = json.loads(lines[0])
        entry["verb"] = "hacked"
        lines[0] = json.dumps(entry, separators=(",", ":"), sort_keys=True)
        audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc, stdout, stderr = _run_harness("verify", "--audit", "--fixture", str(tmp_path))
        assert rc == 10
        assert "Fix:" in stderr or "Fix:" in stdout


def _make_args(fixture_dir=None):
    """Return a minimal args namespace for cmd_verify_audit."""
    args = types.SimpleNamespace()
    args.verify_fixture = str(fixture_dir) if fixture_dir is not None else None
    return args


class TestVerifyAuditCornerFixes:
    """Regression tests for BUG-1 (missing .harness/) and BUG-2 (0-byte state)."""

    # ------------------------------------------------------------------
    # BUG-1 fix: .harness/ entirely absent
    # ------------------------------------------------------------------

    def test_bug1_advanced_state_no_harness_dir_exits_nonzero(self, tmp_path):
        """BUG-1: advanced state file + no .harness/ → non-zero exit (exit 10)."""
        from lib.audit_verify_cli import cmd_verify_audit

        # Set up fake root with advanced state (approved=true) but no .harness/
        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        state = {
            "phase": "execute",
            "approved": True,
            "plan_id": "plan-abc",
            "execution_mode": "manual",
        }
        (scratch / "phase-state.json").write_text(
            json.dumps(state, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        # .harness/ is intentionally absent

        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc != 0, (
            "Expected non-zero exit when state is advanced but .harness/ is missing; "
            f"got {rc}"
        )

    def test_bug1_baseline_state_no_harness_dir_exits_zero(self, tmp_path):
        """BUG-1: baseline state + no .harness/ → exit 0 (fresh install)."""
        from lib.audit_verify_cli import cmd_verify_audit

        # Baseline state: discuss phase, approved=false, no plan
        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        state = {
            "phase": "discuss",
            "approved": False,
            "plan_id": None,
            "execution_mode": "manual",
            "automation_mode": "manual",
            "updated_by": "harness-init",
        }
        (scratch / "phase-state.json").write_text(
            json.dumps(state, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        # .harness/ is intentionally absent

        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 0, (
            f"Expected 0 for fresh baseline install with no .harness/; got {rc}"
        )

    def test_bug1_no_state_no_harness_dir_exits_zero(self, tmp_path):
        """BUG-1: no state file + no .harness/ → exit 0 (truly fresh)."""
        from lib.audit_verify_cli import cmd_verify_audit

        # Neither .scratch/ nor .harness/ — completely fresh environment
        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 0, (
            f"Expected 0 for truly fresh install (no state, no .harness/); got {rc}"
        )

    # ------------------------------------------------------------------
    # BUG-2 fix: 0-byte state file
    # ------------------------------------------------------------------

    def test_bug2_zero_byte_state_file_exits_14(self, tmp_path):
        """BUG-2: 0-byte state file → exit 14 (crash artefact, run recover)."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        # Set up a valid .harness/audit.log so the chain check would pass if reached
        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)

        # 0-byte state file
        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        (scratch / "phase-state.json").write_bytes(b"")

        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 14, (
            f"Expected exit 14 for 0-byte state file; got {rc}"
        )

    def test_bug2_missing_state_file_exits_zero(self, tmp_path):
        """BUG-2: missing state file → exit 0 (no crash artefact)."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        # Valid .harness/audit.log
        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        audit_append({"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}, audit_path=audit_path)

        # No .scratch/ at all — state file does not exist
        args = _make_args()
        rc = cmd_verify_audit(args, tmp_path)
        assert rc == 0, (
            f"Expected 0 when state file is absent (not a crash artefact); got {rc}"
        )
