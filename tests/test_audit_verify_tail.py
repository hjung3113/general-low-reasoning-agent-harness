"""test_audit_verify_tail — verify --audit tail check uses after_sha256, not entry_hash.

Regression test for the false-positive discovered in v0.9.4 smoke (/tmp/v095-smoke3):
  - verify --audit compared result.final_tip_hash (= entry_hash, a chain hash) against
    the raw sha256 of phase-state.json (= after_sha256, a state hash).
  - These are different hash types and will never be equal, so every valid lifecycle
    ended with rc=10 (audit_chain_tail_mismatch) even though nothing was tampered.

Fix: ChainVerifyResult.final_after_sha256 tracks the last entry's after_sha256 field,
and audit_verify_cli.py compares that (not final_tip_hash) to the state file sha256.
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(fixture_dir=None) -> types.SimpleNamespace:
    args = types.SimpleNamespace()
    args.verify_fixture = str(fixture_dir) if fixture_dir is not None else None
    return args


def _write_state(tmp_path: Path, phase: str = "done") -> Path:
    scratch = tmp_path / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    state = {
        "phase": phase,
        "approved": True,
        "plan_id": "plan-smoke",
        "execution_mode": "manual",
        "automation_mode": "manual",
        "updated_by": "test-harness",
        "updated_at": "2026-05-21T00:00:00Z",
    }
    state_path = scratch / "phase-state.json"
    state_path.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return state_path


def _write_installed_manifest(harness_dir: Path) -> None:
    (harness_dir / "installed-manifest.json").write_text(
        '{"version": "0.0.0-test", "files": {}}', encoding="utf-8"
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Core regression: after_sha256 match passes (was false-positive before fix)
# ---------------------------------------------------------------------------

class TestTailCheckUsesAfterSha256:
    """The tail check must compare the last entry's after_sha256 against the
    state file sha256 — NOT entry_hash (chain hash) vs state sha256."""

    def test_matching_after_sha256_exits_zero(self, tmp_path):
        """Valid lifecycle: after_sha256 == state sha256 → rc=0 (no false positive)."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        state_path = _write_state(tmp_path, phase="done")
        state_sha = _sha256(state_path)

        # Simulate a realistic multi-step lifecycle (discuss→plan→execute→done)
        # Only the LAST entry's after_sha256 needs to match state.
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:00:00Z",
             "before_sha256": "0" * 64, "after_sha256": "aaa" + "0" * 61},
            audit_path=audit_path,
        )
        audit_append(
            {"verb": "phase.approve", "at": "2026-05-21T00:01:00Z",
             "before_sha256": "aaa" + "0" * 61, "after_sha256": "bbb" + "0" * 61},
            audit_path=audit_path,
        )
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:02:00Z",
             "before_sha256": "bbb" + "0" * 61, "after_sha256": state_sha},
            audit_path=audit_path,
        )

        rc = cmd_verify_audit(_make_args(), tmp_path)
        assert rc == 0, (
            f"Expected rc=0 when after_sha256 matches state sha256; got rc={rc}.\n"
            f"This is the false-positive regression: entry_hash was compared instead."
        )

    def test_mismatched_after_sha256_exits_nonzero(self, tmp_path):
        """Tampered state: after_sha256 != state sha256 → rc != 0 (real positive)."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        _write_state(tmp_path, phase="done")

        # Write an audit entry whose after_sha256 does NOT match the state file
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:00:00Z",
             "before_sha256": "0" * 64, "after_sha256": "dead" + "0" * 60},
            audit_path=audit_path,
        )

        rc = cmd_verify_audit(_make_args(), tmp_path)
        assert rc != 0, f"Expected non-zero for tampered state; got rc={rc}"

    def test_entry_hash_is_not_compared_to_state(self, tmp_path):
        """Confirm that entry_hash (chain hash) is never equal to state sha256
        under normal circumstances — the old code would always false-positive here."""
        from lib.audit_verify_cli import cmd_verify_audit
        from lib.audit import audit_append
        from lib.audit_chain import verify_chain

        harness_dir = tmp_path / ".harness"
        harness_dir.mkdir()
        audit_path = harness_dir / "audit.log"
        _write_installed_manifest(harness_dir)

        state_path = _write_state(tmp_path, phase="done")
        state_sha = _sha256(state_path)

        # Write correct after_sha256; the entry_hash will be something entirely different
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:00:00Z",
             "before_sha256": "0" * 64, "after_sha256": state_sha},
            audit_path=audit_path,
        )

        result = verify_chain(audit_path)
        assert result.ok
        # entry_hash and after_sha256 are different hash types — they won't match
        assert result.final_tip_hash != result.final_after_sha256, (
            "entry_hash should differ from after_sha256 (they hash different data); "
            "if they happen to be equal this test needs updating but the fix still holds."
        )
        # The fix: final_after_sha256 == state sha256 → cli returns 0
        assert result.final_after_sha256 == state_sha

        rc = cmd_verify_audit(_make_args(), tmp_path)
        assert rc == 0, (
            f"rc={rc}; fix regression: cli must compare final_after_sha256 to state sha256, "
            f"not final_tip_hash (entry_hash)."
        )


# ---------------------------------------------------------------------------
# ChainVerifyResult dataclass exposes final_after_sha256
# ---------------------------------------------------------------------------

class TestChainVerifyResultAfterSha256:
    def test_final_after_sha256_populated(self, tmp_path):
        """verify_chain sets final_after_sha256 from the last entry."""
        from lib.audit import audit_append
        from lib.audit_chain import verify_chain

        audit_path = tmp_path / "audit.log"
        expected = "c" * 64
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:00:00Z",
             "before_sha256": "0" * 64, "after_sha256": expected},
            audit_path=audit_path,
        )
        result = verify_chain(audit_path)
        assert result.ok
        assert result.final_after_sha256 == expected

    def test_final_after_sha256_tracks_last_entry(self, tmp_path):
        """final_after_sha256 reflects the LAST entry, not an earlier one."""
        from lib.audit import audit_append
        from lib.audit_chain import verify_chain

        audit_path = tmp_path / "audit.log"
        first_sha = "a" * 64
        last_sha = "b" * 64

        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:00:00Z",
             "before_sha256": "0" * 64, "after_sha256": first_sha},
            audit_path=audit_path,
        )
        audit_append(
            {"verb": "phase.set", "at": "2026-05-21T00:01:00Z",
             "before_sha256": first_sha, "after_sha256": last_sha},
            audit_path=audit_path,
        )

        result = verify_chain(audit_path)
        assert result.ok
        assert result.final_after_sha256 == last_sha

    def test_final_after_sha256_none_for_empty_log(self, tmp_path):
        """Empty log → final_after_sha256 is None (no entries to read)."""
        from lib.audit_chain import verify_chain

        audit_path = tmp_path / "audit.log"
        audit_path.write_text("", encoding="utf-8")
        result = verify_chain(audit_path)
        assert result.ok
        assert result.final_after_sha256 is None

    def test_final_after_sha256_none_for_entry_without_field(self, tmp_path):
        """Entry lacking after_sha256 → final_after_sha256 stays None."""
        from lib.audit import audit_append
        from lib.audit_chain import verify_chain

        audit_path = tmp_path / "audit.log"
        # Intentionally omit after_sha256 (e.g. a legacy or non-phase-set entry)
        audit_append(
            {"verb": "audit.rotated", "at": "2026-05-21T00:00:00Z"},
            audit_path=audit_path,
        )
        result = verify_chain(audit_path)
        assert result.ok
        assert result.final_after_sha256 is None
