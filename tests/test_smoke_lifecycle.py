"""T15 — Full lifecycle smoke: fresh init → discuss → plan → execute → done.

Success criteria (Plan §2, T15):
  - init with --approver-email creates install-record.json
  - harness next, status, check all succeed after init
  - Full phase walk (discuss → plan → approve → execute → approve → done)
  - No ModuleNotFoundError on any verb
  - `harness next` and `harness status` Next action line agree (NEW-4 parity)
  - `harness check` rc=0 after clean init
  - `harness check --verify-hashes` rc=0 after clean init

Smoke contract (tests/SMOKE_CONTRACT.md):
  - All subprocesses captured via subprocess.run(..., capture_output=True, text=True)
  - rc asserted explicitly; no pipe-to-tail  # smoke-contract: allow doc-comment describes the forbidden pattern not uses it
  - HARNESS_SMOKE_TEST=1 + HARNESS_SMOKE_BYPASS_SPEED_BUMP=1 set ONLY for
    `phase approve` and `phase reopen` subprocess invocations (codex M-9)
  - All other verbs (next, status, check, phase set) use plain os.environ
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HARNESS_PY = str(SCRIPTS_DIR / "harness.py")
_PYTHON = sys.executable

APPROVER_EMAIL = "smoke-test@example.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    *args: str,
    cwd: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run harness.py with given args; return CompletedProcess."""
    cmd = [_PYTHON, HARNESS_PY, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env if env is not None else dict(os.environ),
    )


def _approve_env() -> dict:
    """Return env dict for phase approve / reopen subprocesses only (codex M-9)."""
    return {
        **os.environ,
        "HARNESS_SMOKE_TEST": "1",
        "HARNESS_SMOKE_BYPASS_SPEED_BUMP": "1",
    }


def _init_target(target: Path) -> None:
    """Run harness init on target; assert rc=0."""
    result = _run(
        "init",
        "--target", str(target),
        "--adapters", "none",
        "--approver-email", APPROVER_EMAIL,
    )
    assert result.returncode == 0, (
        f"init must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    # Seed verification immediately after init (before any audit chain is written).
    _seed_initial_state(target)


def _read_phase_state(target: Path) -> dict:
    state_path = target / ".scratch" / "phase-state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


def _seed_initial_state(target: Path) -> None:
    """Seed verification + allowed_paths into phase-state.json before any audit ops.

    Must be called BEFORE the first ``phase set`` command so the audit chain
    has not yet been established.  Direct state writes after the first
    ``phase set`` would break the sha256 chain and cause phase approve to
    refuse with a trust-preflight error.
    """
    state_path = target / ".scratch" / "phase-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["verification"] = ["echo smoke-ok"]
    state["allowed_paths"] = ["scripts/"]
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def fresh_target(tmp_path: Path) -> Path:
    """A freshly-inited harness target (discuss phase)."""
    _init_target(tmp_path)
    return tmp_path


# ===========================================================================
# Test 1: install-record exists after init
# ===========================================================================


class TestInitCreatesInstallRecord:
    def test_init_with_approver_email_creates_install_record(
        self, tmp_path: Path
    ) -> None:
        _init_target(tmp_path)
        record_path = tmp_path / ".harness" / "install-record.json"
        assert record_path.exists(), f"install-record.json must exist at {record_path}"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert "approvers" in record, "install-record must have approvers field"
        assert isinstance(record["approvers"], list), "approvers must be a list"
        assert len(record["approvers"]) >= 1, "approvers must have at least one entry"
        emails = [
            a.get("email", a) if isinstance(a, dict) else a
            for a in record["approvers"]
        ]
        assert APPROVER_EMAIL in emails, (
            f"approver {APPROVER_EMAIL!r} not found in {emails}"
        )


# ===========================================================================
# Test 2: harness check rc=0 after fresh init
# ===========================================================================


class TestCheckAfterInit:
    def test_harness_check_clean_install_rc0(self, fresh_target: Path) -> None:
        result = _run("check", cwd=str(fresh_target))
        assert result.returncode == 0, (
            f"harness check must exit 0 after init.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_harness_check_verify_hashes_clean_rc0(self, fresh_target: Path) -> None:
        result = _run("check", "--verify-hashes", cwd=str(fresh_target))
        assert result.returncode == 0, (
            f"harness check --verify-hashes must exit 0 after init.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


# ===========================================================================
# Test 3: harness next after init
# ===========================================================================


class TestHarnessNextAfterInit:
    def test_harness_next_after_init(self, fresh_target: Path) -> None:
        result = _run("next", cwd=str(fresh_target))
        assert result.returncode == 0, (
            f"harness next must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        output = result.stdout.strip()
        assert output, "harness next must emit a non-empty command"
        # Should not contain newlines (single concrete command)
        assert "\n" not in output, (
            f"harness next must emit a single command, got multi-line: {output!r}"
        )


# ===========================================================================
# Test 4: status / next parity (NEW-4)
# ===========================================================================


class TestStatusNextParity:
    def test_status_next_parity(self, fresh_target: Path) -> None:
        """harness status 'Next action:' line must equal `harness next` canonical output.

        Parity is tested in HARNESS_ADVANCED=1 mode where both status and next
        use compute_next_action verbatim (NEW-4 contract).  In normal mode
        harness next maps agent-safe transitions to 'harness run' for UX, which
        intentionally diverges from the canonical phase command shown by status.
        """
        advanced_env = {**os.environ, "HARNESS_ADVANCED": "1"}
        next_result = _run("next", cwd=str(fresh_target), env=advanced_env)
        assert next_result.returncode == 0, (
            f"harness next (advanced) failed: {next_result.stderr}"
        )
        status_result = _run("status", cwd=str(fresh_target))
        assert status_result.returncode == 0, (
            f"harness status failed: {status_result.stderr}"
        )

        next_cmd = next_result.stdout.strip()

        # Extract "Next action     : <command>" from status output
        next_action_line = None
        for line in status_result.stdout.splitlines():
            if line.startswith("Next action"):
                next_action_line = line.split(":", 1)[1].strip()
                break
        assert next_action_line is not None, (
            f"No 'Next action' line in status output:\n{status_result.stdout}"
        )

        assert next_cmd == next_action_line, (
            f"harness next ADVANCED ({next_cmd!r}) != status 'Next action' ({next_action_line!r})"
        )


# ===========================================================================
# Test 5: no ModuleNotFoundError on common verbs
# ===========================================================================


class TestNoModuleNotFound:
    def test_no_module_not_found(self, fresh_target: Path) -> None:
        """Every common verb runs without ModuleNotFoundError (BUG-1)."""
        verbs = [
            ["next"],
            ["status"],
            ["check"],
            ["phase", "set", "plan", "--plan-id", "smoke-plan"],
            ["next"],
            ["status"],
        ]
        for verb_args in verbs:
            result = _run(*verb_args, cwd=str(fresh_target))
            assert "ModuleNotFoundError" not in result.stdout, (
                f"ModuleNotFoundError in stdout for {verb_args}: {result.stdout}"
            )
            assert "ModuleNotFoundError" not in result.stderr, (
                f"ModuleNotFoundError in stderr for {verb_args}: {result.stderr}"
            )


# ===========================================================================
# Test 6: Full lifecycle walk discuss → plan → execute → done
# ===========================================================================


class TestLifecycleToDone:
    def test_lifecycle_to_done_via_explicit_phase_verbs(
        self, tmp_path: Path
    ) -> None:
        """Walk: discuss → plan (approve) → execute (approve) → done.

        Phase approve invocations use HARNESS_SMOKE_TEST + HARNESS_SMOKE_BYPASS_SPEED_BUMP
        (codex M-9: ONLY for approve subprocesses, not for phase set / next / check).
        """
        _init_target(tmp_path)

        # --- discuss → plan ---
        result = _run(
            "phase", "set", "plan", "--plan-id", "lifecycle-smoke",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set plan must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        state = _read_phase_state(tmp_path)
        assert state["phase"] == "plan", f"Expected plan phase, got {state['phase']}"

        # Approve plan phase with a far-future --at so the second-precision
        # approved_at is guaranteed to post-date plan_finalized_at's microsecond
        # precision (ADR-001 §3.6 stale-approval check).
        # Smoke env scoped to this subprocess only (codex M-9).
        result = _run(
            "phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-01-01T00:00:00Z",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase approve (plan) must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        state = _read_phase_state(tmp_path)
        assert state.get("approved") is True, "State must be approved after phase approve"

        # --- plan → execute ---
        result = _run(
            "phase", "set", "execute",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set execute must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        state = _read_phase_state(tmp_path)
        assert state["phase"] == "execute", f"Expected execute phase, got {state['phase']}"

        # Approve execute phase (same far-future --at trick)
        result = _run(
            "phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-06-01T00:00:00Z",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase approve (execute) must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # --- execute → done ---
        result = _run(
            "phase", "set", "done",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set done must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        state = _read_phase_state(tmp_path)
        assert state["phase"] == "done", f"Expected done phase, got {state['phase']}"

        # harness next at done says 'workflow complete'
        result = _run("next", cwd=str(tmp_path))
        assert result.returncode == 0, (
            f"harness next at done must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "complete" in result.stdout.lower() or result.stdout.strip() == "", (
            f"harness next at done should indicate completion: {result.stdout!r}"
        )

    def test_each_transition_creates_audit_row(self, tmp_path: Path) -> None:
        """Each phase transition writes an audit row to .harness/audit.log."""
        _init_target(tmp_path)

        _run("phase", "set", "plan", "--plan-id", "audit-smoke", cwd=str(tmp_path))
        _run("phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-01-01T00:00:00Z",
             cwd=str(tmp_path), env=_approve_env())
        _run("phase", "set", "execute", cwd=str(tmp_path))
        _run("phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-06-01T00:00:00Z",
             cwd=str(tmp_path), env=_approve_env())
        _run("phase", "set", "done", cwd=str(tmp_path))

        audit_path = tmp_path / ".harness" / "audit.log"
        assert audit_path.exists(), "audit.log must exist after lifecycle"
        rows = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verbs = [r.get("verb") for r in rows]
        assert "phase.set" in verbs, f"Expected phase.set audit row; got {verbs}"
        assert "phase.approve" in verbs, f"Expected phase.approve audit row; got {verbs}"


# ===========================================================================
# Test 7: phase reopen coverage (MAJOR-4)
# ===========================================================================


class TestPhaseReopen:
    """Exercise phase reopen with smoke bypass (codex M-9).

    MAJOR-4 fix: plan §7.6 introduces phase.reopen.bypass as a distinct
    classification for smoke-bypassed reopens.  T12 (commit 659fb78)
    implemented this as verb=phase.reopen + proof_class=smoke_bypass.
    These tests verify:
      (a) reopen from done → plan with smoke env: rc=0 + phase.reopen audit row
      (b) proof_class=smoke_bypass is set when HARNESS_SMOKE_BYPASS_SPEED_BUMP=1
      (c) backward-move guard: reopen from approved=True requires --reset-approval
    """

    def _full_lifecycle_to_done(self, tmp_path: Path) -> None:
        """Walk discuss → plan (approve) → execute (approve) → done."""
        _init_target(tmp_path)

        result = _run(
            "phase", "set", "plan", "--plan-id", "reopen-smoke",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set plan failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        result = _run(
            "phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-01-01T00:00:00Z",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase approve (plan) failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        result = _run(
            "phase", "set", "execute",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set execute failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        result = _run(
            "phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-06-01T00:00:00Z",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase approve (execute) failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        result = _run(
            "phase", "set", "done",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set done failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_phase_reopen_from_done_to_plan(self, tmp_path: Path) -> None:
        """phase reopen --to plan from done phase succeeds with smoke env.

        Verifies:
          - rc=0
          - audit row with verb=phase.reopen is written
          - proof_class=smoke_bypass is set (T12 / plan §7.6 phase.reopen.bypass
            contract: smoke-bypassed reopens are identified via proof_class)
          - state rolls back to plan phase
        """
        self._full_lifecycle_to_done(tmp_path)

        # Reopen: done → plan.  Smoke env required to bypass TTY gate (codex M-9).
        result = _run(
            "phase", "reopen",
            "--to", "plan",
            "--by", APPROVER_EMAIL,
            "--reason", "smoke test: reopen done to plan",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase reopen must exit 0.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # State must be rolled back to plan.
        state = _read_phase_state(tmp_path)
        assert state["phase"] == "plan", (
            f"Expected phase=plan after reopen; got {state['phase']}"
        )

        # Audit row must be present.
        audit_path = tmp_path / ".harness" / "audit.log"
        assert audit_path.exists(), "audit.log must exist after reopen"
        rows = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reopen_rows = [r for r in rows if r.get("verb") == "phase.reopen"]
        assert reopen_rows, (
            f"Expected phase.reopen audit row; verbs found: {[r.get('verb') for r in rows]}"
        )

        # T12 / plan §7.6: smoke-bypassed reopens carry proof_class=smoke_bypass.
        row = reopen_rows[0]
        assert row.get("proof_class") == "smoke_bypass", (
            f"Expected proof_class=smoke_bypass on smoke-bypassed reopen; "
            f"row={row}"
        )

    def test_phase_reopen_backward_move_requires_reset_approval(
        self, tmp_path: Path
    ) -> None:
        """Reopen from approved=True state refuses without --reset-approval.

        NEW-7 contract (T12): backward move (approved=True at reopen) requires
        the caller to pass --reset-approval to acknowledge the approval is
        being revoked.  Omitting the flag must produce rc=6.
        """
        _init_target(tmp_path)

        # Advance to plan and approve it (state becomes approved=True).
        result = _run(
            "phase", "set", "plan", "--plan-id", "reopen-backward-smoke",
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"phase set plan failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        result = _run(
            "phase", "approve", "--by", APPROVER_EMAIL, "--at", "2030-01-01T00:00:00Z",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase approve failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )

        # Without --reset-approval, reopen from approved plan → discuss must fail.
        result = _run(
            "phase", "reopen",
            "--to", "discuss",
            "--by", APPROVER_EMAIL,
            "--reason", "smoke test: backward without reset-approval",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode != 0, (
            f"phase reopen without --reset-approval must exit non-zero "
            f"when approved=True (NEW-7 guard).\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        # With --reset-approval, the same reopen must succeed.
        result = _run(
            "phase", "reopen",
            "--to", "discuss",
            "--by", APPROVER_EMAIL,
            "--reason", "smoke test: backward with reset-approval",
            "--reset-approval",
            cwd=str(tmp_path),
            env=_approve_env(),
        )
        assert result.returncode == 0, (
            f"phase reopen with --reset-approval must exit 0.\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        state = _read_phase_state(tmp_path)
        assert state["phase"] == "discuss", (
            f"Expected phase=discuss after reset-approval reopen; got {state['phase']}"
        )


# ===========================================================================
# Test 8: smoke contract compliance self-check
# ===========================================================================


class TestSmokeContractCompliance:
    def test_smoke_contract_compliance(self) -> None:
        """This file itself passes the smoke contract lint (T2 M-10)."""
        lint_script = REPO_ROOT / "scripts" / "test_smoke_contract.py"
        if not lint_script.exists():
            pytest.skip("test_smoke_contract.py not found — T2 not yet landed")
        result = subprocess.run(
            [_PYTHON, str(lint_script)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"Smoke contract violations in test_smoke_lifecycle.py:\n{result.stdout}"
        )
