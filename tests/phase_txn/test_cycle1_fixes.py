"""Cycle-1 fix A — three P1 regression tests (phase_txn + cli_budgets + audit).

P1-1 (concurrency): PENDING sentinel in autopilot_start_entry_hash causes
    recover() to emit a rollback-to-manual commit instead of leaving the
    state wedged; preflight also detects and rejects PENDING as a defense
    in depth.

P1-2 (concurrency): apply_budget_halt / wall_seconds_check_and_maybe_halt
    commit succeeds even when file_mutation_ops==0 — the halt action strings
    are now exempt from the BudgetExhaustedError pre-check.

P3-P1-A (input/injection): audit minimal-fallback preserves by_source and
    confirmation_kind (truncation-resilient identity discriminators per
    §12.5 #1 + S05 override-identity audit shape).
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

# Make scripts/ importable when run directly
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import phase_lock, phase_txn, state_trust


# ---------------------------------------------------------------------------
# Helpers shared across all test groups
# ---------------------------------------------------------------------------


def _canon_bytes(state: dict) -> bytes:
    return phase_txn._canonical_bytes(state)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_state(scratch: Path, state: dict) -> bytes:
    body = _canon_bytes(state)
    (scratch / "phase-state.json").write_bytes(body)
    return body


def _write_audit(audit_path: Path, entries: list[dict]) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8") as fh:
        for i, entry in enumerate(entries, start=1):
            full = dict(entry, index=i)
            fh.write(json.dumps(full, sort_keys=True, separators=(",", ":")) + "\n")


def _pending_autopilot_state() -> dict:
    """Minimal state with PENDING sentinel + active autopilot."""
    return {
        "phase": "01-plan",
        "approved": True,
        "approved_at": "2026-05-17T00:00:00Z",
        "approved_by": "alice@example.com",
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "run-abc123",
        "autopilot_mode": "phase_autopilot",
        "autopilot_phase_slug": "01-plan",
        "autopilot_start_entry_hash": "PENDING",
        "autopilot_allow_network": False,
        "cli_budgets_remaining": {
            "shell_invocations": 10,
            "file_mutation_ops": 5,
            "wall_seconds": 3600,
        },
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    d = tmp_path / ".scratch"
    d.mkdir()
    return d


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    (tmp_path / ".harness").mkdir()
    return tmp_path / ".harness" / "audit.log"


@pytest.fixture
def lock(scratch: Path):
    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    yield handle
    phase_lock.release_primary(handle)


# ---------------------------------------------------------------------------
# P1-1 tests: PENDING sentinel recovery
# ---------------------------------------------------------------------------


class TestPendingSentinelRecovery:
    """P1-1: recover() detects PENDING sentinel and rolls back to manual."""

    def test_recover_detects_pending_sentinel_and_rolls_back_to_manual(
        self, scratch: Path, audit_path: Path, lock
    ):
        """Seed state with PENDING sentinel + execution_mode=phase_autopilot
        + clean journal (quiescent row-1 scenario). recover() MUST rollback
        to manual: execution_mode=manual, autopilot_* cleared, last_halt
        populated with halt_reason=crash_during_autopilot_start_hash_finalize.
        """
        pending_state = _pending_autopilot_state()
        state_body = _write_state(scratch, pending_state)
        # Empty audit → quiescent row-1 normally, but PENDING sentinel fires.
        audit_path.write_text("", encoding="utf-8")

        result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)

        # Recovery succeeds (exit 0)
        assert result.exit_code == 0
        assert result.decision == "pending_sentinel_rollback_to_manual"

        # On-disk state is now in manual mode
        on_disk = json.loads((scratch / "phase-state.json").read_bytes())
        assert on_disk["execution_mode"] == "manual"

        # Autopilot identity fields are cleared
        assert on_disk["autopilot_run_id"] is None
        assert on_disk["autopilot_mode"] is None
        assert on_disk["autopilot_phase_slug"] is None
        assert on_disk["autopilot_start_entry_hash"] is None
        assert on_disk["autopilot_allow_network"] is None

        # last_halt populated with the crash reason
        last_halt = on_disk.get("last_halt")
        assert last_halt is not None
        assert last_halt["halt_reason"] == "crash_during_autopilot_start_hash_finalize"
        assert last_halt["autopilot_run_id"] == "run-abc123"
        assert last_halt["autopilot_phase_slug"] == "01-plan"
        assert last_halt["acknowledged_at"] is None

        # Audit log has the recovery verb
        audit_lines = [
            json.loads(ln)
            for ln in audit_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        recovery_entries = [
            e for e in audit_lines
            if e.get("verb") == "phase.autopilot.start.recover_pending"
        ]
        assert len(recovery_entries) == 1, (
            f"Expected 1 recovery audit entry, got {len(recovery_entries)}: {audit_lines}"
        )

        # Journal and tmp cleaned up
        assert not (scratch / "phase-state.json.journal").exists()
        assert not (scratch / "phase-state.json.tmp").exists()

    def test_recover_pending_sentinel_with_existing_audit_tail(
        self, scratch: Path, audit_path: Path, lock
    ):
        """PENDING sentinel detection works even when audit has a prior entry
        (row-3 scenario: J=0, T=0, A=1, state matches audit after_sha).
        """
        pending_state = _pending_autopilot_state()
        state_body = _write_state(scratch, pending_state)
        # Audit tail matches current state (row-3 condition)
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "a" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)

        assert result.exit_code == 0
        assert result.decision == "pending_sentinel_rollback_to_manual"

        on_disk = json.loads((scratch / "phase-state.json").read_bytes())
        assert on_disk["execution_mode"] == "manual"
        assert on_disk["autopilot_start_entry_hash"] is None

    def test_recover_does_not_fire_for_non_pending_state(
        self, scratch: Path, audit_path: Path, lock
    ):
        """When autopilot_start_entry_hash has a real hash (not PENDING),
        recover() must NOT emit the rollback commit."""
        normal_state = _pending_autopilot_state()
        normal_state["autopilot_start_entry_hash"] = "abc" * 21 + "x"  # not PENDING
        state_body = _write_state(scratch, normal_state)
        audit_path.write_text("", encoding="utf-8")

        # This will fail row-1 check since audit tail != state sha; that's OK
        # — we just need to verify the PENDING path is NOT taken.
        # Seed audit to match so recovery quiesces normally.
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "b" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
        assert result.exit_code == 0
        # Should be row-3 (post_finalize), NOT the pending rollback
        assert result.decision != "pending_sentinel_rollback_to_manual"

    def test_recover_does_not_fire_for_manual_mode_with_pending(
        self, scratch: Path, audit_path: Path, lock
    ):
        """If execution_mode is already manual (but PENDING somehow set),
        do not fire the rollback. This is a defensive check only."""
        manual_state = _pending_autopilot_state()
        manual_state["execution_mode"] = "manual"  # already manual
        state_body = _write_state(scratch, manual_state)
        audit_path.write_text("", encoding="utf-8")
        _write_audit(audit_path, [
            {
                "verb": "phase.set",
                "txn_id": "c" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        result = phase_txn.recover(scratch, audit_path=audit_path, lock=lock)
        assert result.exit_code == 0
        assert result.decision != "pending_sentinel_rollback_to_manual"


class TestPendingSentinelPreflight:
    """P1-1 defense-in-depth: preflight rejects PENDING sentinel."""

    def test_preflight_rejects_pending_sentinel_as_defense_in_depth(
        self, scratch: Path, audit_path: Path, lock
    ):
        """state with PENDING + active autopilot must raise StateAuditMismatchError
        with sub_reason=autopilot_start_hash_pending_after_crash (exit 14
        escalation through StateTrustPreflightError -> exit 10 for audit
        mismatch, or a custom message carrying the sub_reason string).
        """
        pending_state = _pending_autopilot_state()
        state_body = _write_state(scratch, pending_state)
        # Audit tail matches state so the sha check passes → PENDING check fires.
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "d" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        with pytest.raises(state_trust.StateAuditMismatchError) as exc_info:
            state_trust.preflight(
                scratch, audit_path=audit_path, lock=lock
            )
        assert "autopilot_start_hash_pending_after_crash" in str(exc_info.value)

    def test_preflight_does_not_reject_normal_pending_none(
        self, scratch: Path, audit_path: Path, lock
    ):
        """Normal state with autopilot_start_entry_hash=None (not PENDING)
        must pass preflight (no false positive)."""
        normal_state = {
            "phase": "01-plan",
            "approved": False,
            "execution_mode": "manual",
            "autopilot_start_entry_hash": None,
            "state_schema_version": 2,
        }
        state_body = _write_state(scratch, normal_state)
        _write_audit(audit_path, [
            {
                "verb": "phase.set",
                "txn_id": "e" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        # Should not raise
        state_trust.preflight(
            scratch, audit_path=audit_path, lock=lock
        )


# ---------------------------------------------------------------------------
# P1-2 tests: budget halt exempt from budget pre-check
# ---------------------------------------------------------------------------


class TestBudgetHaltExempt:
    """P1-2: halt action strings are exempt from BudgetExhaustedError pre-check."""

    def _make_autopilot_state_with_zero_budget(self) -> dict:
        """Return state with autopilot active and file_mutation_ops=0."""
        return {
            "phase": "01-plan",
            "approved": True,
            "execution_mode": "phase_autopilot",
            "autopilot_run_id": "run-xyz",
            "autopilot_mode": "phase_autopilot",
            "autopilot_phase_slug": "01-plan",
            "autopilot_start_entry_hash": "abc" * 21 + "x",
            "autopilot_allow_network": False,
            "autopilot_started_at_iso": "2020-01-01T00:00:00Z",  # far past → exhausted wall_seconds
            "cli_budgets_remaining": {
                "shell_invocations": 10,
                "file_mutation_ops": 0,  # exhausted
                "wall_seconds": 1,       # 1s budget
            },
            "last_halt": None,
            "last_halt_history": [],
            "state_schema_version": 2,
        }

    def test_halt_action_not_blocked_by_zero_file_mutation_ops(
        self, scratch: Path, audit_path: Path, lock
    ):
        """phase.autopilot.halt.budget action must succeed even when
        before_state.cli_budgets_remaining.file_mutation_ops == 0.
        Previously this raised BudgetExhaustedError, preventing the halt
        commit from persisting.
        """
        before_state = self._make_autopilot_state_with_zero_budget()
        state_body = _write_state(scratch, before_state)
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "f" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        after_state = dict(before_state)
        after_state["execution_mode"] = "manual"
        after_state["autopilot_run_id"] = None
        after_state["cli_budgets_remaining"] = None
        after_state["last_halt"] = {
            "at": "2026-05-17T00:00:00Z",
            "reason": "budget_exhausted:file_mutation_ops",
            "capability": "file_mutation_ops",
            "remaining_at_halt": 0,
        }

        # This MUST NOT raise BudgetExhaustedError
        txn_id = phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=phase_txn.TxnRequest(
                action="phase.autopilot.halt.budget",  # exempt action
                before_state=before_state,
                after_state=after_state,
                audit_entry_draft={
                    "verb": "phase.autopilot.halt",
                    "args": {"reason": "budget_exhausted:file_mutation_ops"},
                },
            ),
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)

        # State was written
        on_disk = json.loads((scratch / "phase-state.json").read_bytes())
        assert on_disk["execution_mode"] == "manual"

    def test_generic_halt_action_exempt(
        self, scratch: Path, audit_path: Path, lock
    ):
        """phase.autopilot.halt action (generic) must also be exempt."""
        before_state = self._make_autopilot_state_with_zero_budget()
        state_body = _write_state(scratch, before_state)
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "g" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        after_state = dict(before_state)
        after_state["execution_mode"] = "manual"
        after_state["cli_budgets_remaining"] = None

        txn_id = phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=phase_txn.TxnRequest(
                action="phase.autopilot.halt",  # exempt action
                before_state=before_state,
                after_state=after_state,
                audit_entry_draft={
                    "verb": "phase.autopilot.halt",
                    "args": {"reason": "manual_override"},
                },
            ),
            audit_path=audit_path,
        )
        assert isinstance(txn_id, str)

    def test_non_exempt_action_still_blocked_by_zero_budget(
        self, scratch: Path, audit_path: Path, lock
    ):
        """Non-exempt actions with file_mutation_ops=0 MUST still raise
        BudgetExhaustedError — the exemption list is not a blanket bypass."""
        before_state = self._make_autopilot_state_with_zero_budget()
        state_body = _write_state(scratch, before_state)
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "h" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        after_state = dict(before_state)
        after_state["phase"] = "02-exec"

        with pytest.raises(phase_txn.BudgetExhaustedError):
            phase_txn.commit_transaction(
                scratch,
                lock=lock,
                request=phase_txn.TxnRequest(
                    action="phase.set",  # NOT exempt
                    before_state=before_state,
                    after_state=after_state,
                    audit_entry_draft={
                        "verb": "phase.set",
                        "args": {"slug": "02-exec"},
                    },
                ),
                audit_path=audit_path,
            )

    def test_apply_budget_halt_succeeds_when_file_mutation_ops_zero(
        self, scratch: Path, audit_path: Path, lock
    ):
        """End-to-end: wall_seconds_check_and_maybe_halt completes when
        file_mutation_ops=0 at the time the wall_seconds budget fires.
        Previously: BudgetExhaustedError raised by commit_transaction.
        Now: halt commit completes, state.execution_mode == 'manual'.
        """
        from lib import cli_budgets

        before_state = self._make_autopilot_state_with_zero_budget()
        state_body = _write_state(scratch, before_state)
        _write_audit(audit_path, [
            {
                "verb": "phase.autopilot.start",
                "txn_id": "i" * 32,
                "after_sha256": _sha(state_body),
            },
        ])

        # Use a fixed now_iso that is far enough past the anchor to exhaust
        # the 1-second wall_seconds budget.
        exit_code = cli_budgets.wall_seconds_check_and_maybe_halt(
            before_state=before_state,
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock,
            now_iso="2026-05-17T01:00:00Z",  # >> 2020-01-01 anchor, >> 1s budget
        )

        assert exit_code == 9, f"Expected exit 9 (budget halt), got {exit_code!r}"

        # State is now manual
        on_disk = json.loads((scratch / "phase-state.json").read_bytes())
        assert on_disk["execution_mode"] == "manual"

        # last_halt populated
        last_halt = on_disk.get("last_halt")
        assert last_halt is not None


# ---------------------------------------------------------------------------
# P3-P1-A tests: audit minimal-fallback preserves by_source + confirmation_kind
# ---------------------------------------------------------------------------


class TestMinimalFallbackPreservesIdentity:
    """P3-P1-A: audit minimal-fallback preserves by_source and confirmation_kind."""

    def _force_minimal_fallback(
        self,
        tmp_path: Path,
        *,
        by_source: str,
        confirmation_kind: str,
    ) -> dict:
        """Construct an oversized audit entry with override-identity fields,
        force minimal-fallback, and return the written audit line dict."""
        from lib.audit import audit_append, AUDIT_MAX_LINE_BYTES

        audit_path = tmp_path / "audit.log"
        big_entry = {
            "verb": "phase.approve",
            "at": "2026-05-17T00:00:00Z",
            "by": "alice@example.com",
            "by_source": by_source,
            "confirmation_kind": confirmation_kind,
            "args": {
                # Large enough args payload to push the entry past 1024 bytes
                # even after truncation, forcing the last-resort minimal path.
                "override_reason": "x" * 2000,
                "extra_field": "y" * 500,
            },
        }
        audit_append(big_entry, audit_path=audit_path)

        lines = [
            json.loads(ln)
            for ln in audit_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        return lines[-1]

    def test_minimal_fallback_preserves_by_source_and_confirmation_kind(
        self, tmp_path: Path
    ):
        """An oversized entry with by_source + confirmation_kind MUST have
        both fields in the minimal-fallback record written to audit.log."""
        entry = self._force_minimal_fallback(
            tmp_path,
            by_source="override",
            confirmation_kind="human_tty_nonce",
        )
        assert entry.get("args") == {"truncated": True}, (
            "Expected minimal-fallback to have args={truncated: True}, "
            f"got args={entry.get('args')!r}"
        )
        assert entry.get("by_source") == "override", (
            f"by_source missing from minimal-fallback: {entry}"
        )
        assert entry.get("confirmation_kind") == "human_tty_nonce", (
            f"confirmation_kind missing from minimal-fallback: {entry}"
        )

    def test_minimal_fallback_preserves_chain_fields_alongside_identity(
        self, tmp_path: Path
    ):
        """Chain fields (seq, seq_global, previous_entry_hash, entry_hash,
        schema_version) must also be present in the minimal-fallback record
        together with the identity fields (§12.5 #1)."""
        entry = self._force_minimal_fallback(
            tmp_path,
            by_source="ci_env",
            confirmation_kind="ci_predicate",
        )
        for field in ("seq", "seq_global", "previous_entry_hash", "entry_hash", "schema_version"):
            assert field in entry, f"Chain field {field!r} missing from minimal-fallback"
        assert entry.get("by_source") == "ci_env"
        assert entry.get("confirmation_kind") == "ci_predicate"

    def test_minimal_fallback_omits_none_identity_fields(self, tmp_path: Path):
        """When by_source and confirmation_kind are absent from the original
        entry, the minimal fallback must NOT add None-valued keys for them."""
        from lib.audit import audit_append

        audit_path = tmp_path / "audit.log"
        big_entry = {
            "verb": "phase.set",
            "at": "2026-05-17T00:00:00Z",
            "by": "alice@example.com",
            # NO by_source, NO confirmation_kind
            "args": {"data": "x" * 2000},
        }
        audit_append(big_entry, audit_path=audit_path)
        lines = [
            json.loads(ln)
            for ln in audit_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        entry = lines[-1]
        # The minimal fallback should NOT include these keys when absent
        # (to keep the record compact and avoid polluting the schema)
        assert "by_source" not in entry, (
            "by_source should not appear in minimal-fallback when not in original entry"
        )
        assert "confirmation_kind" not in entry, (
            "confirmation_kind should not appear in minimal-fallback when not in original"
        )

    def test_phase_approve_override_audit_survives_truncation(self, tmp_path: Path):
        """End-to-end: an oversized override-reason audit entry written by
        phase_approve survives to minimal-fallback with by_source preserved."""
        from lib.audit import audit_append, AUDIT_MAX_LINE_BYTES

        audit_path = tmp_path / "audit.log"
        # Simulate the audit entry shape phase_approve emits for an override
        override_entry = {
            "verb": "phase.approve",
            "at": "2026-05-17T00:00:00Z",
            "by": "alice@example.com",
            "by_source": "override",
            "confirmation_kind": "human_tty_nonce",
            "args": {
                # Crafted long override-reason that triggers minimal-fallback
                "override_reason": "Security exception: " + "A" * 1500,
                "phase_slug": "01-plan",
                "nonce": "abc123def456",
            },
        }
        audit_append(override_entry, audit_path=audit_path)

        lines = [
            json.loads(ln)
            for ln in audit_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        entry = lines[-1]
        # Even in minimal-fallback, identity discriminators survive
        assert entry.get("by_source") == "override"
        assert entry.get("confirmation_kind") == "human_tty_nonce"
        # Size constraint respected
        line_bytes = (json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        assert len(line_bytes) <= AUDIT_MAX_LINE_BYTES
