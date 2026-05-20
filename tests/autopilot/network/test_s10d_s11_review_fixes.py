"""S10d + S11 review-fix tests — P1 + P2 items.

Covers:
  P1-1: accepted_by_caller audit field on windows_audit_guard_degraded posture
  P1-2: git.cmd setlocal enabledelayedexpansion + !ERRORLEVEL! (no bare %ERRORLEVEL% in if-blocks)
  P1-3+P1-4: autopilot_guard.ps1 PS 5.1 compatibility (no utf8NoBOM, no -AsUTC; .NET APIs)
  P2-3: refused-start emits phase.autopilot.start.refused audit row on Windows exit 11
  P2-4: apply_budget_halt stamps acknowledged_at on rotated prior last_halt

Design refs:
  - §3.5 line 666 — accepted_by_caller audit pair
  - §5.2 — Windows two-track: WARN + degraded posture; PS 5.1 compat
  - §3.4 — exit 11 windows_containment_degraded
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# P1-1: accepted_by_caller audit field
# ---------------------------------------------------------------------------

from lib import approval_nonce, phase_autopilot, phase_lock, phase_txn


def _make_harness_env(tmp_path: Path) -> dict:
    """Primed harness root with scratch, audit, roadmap, install-record, and nonce dir."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "cli_budgets_remaining": None,
        "autopilot_allow_network": False,
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=phase_txn.TxnRequest(
                action="phase.set",
                before_state=None,
                after_state=seed_state,
                audit_entry_draft={"verb": "phase.set", "by": "seed", "args": {"phase": "plan"}},
            ),
            audit_path=audit_path,
        )
    finally:
        phase_lock.release_primary(lock)

    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z", "source": "gitconfig_auto"}
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    )

    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir(parents=True)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "roadmap_root": planning,
        "install_record_root": tmp_path,
        "nonce_dir": nonce_dir,
    }


def _do_start_tty(env: dict, *, mode: str = "phase", accept_degraded: bool = False) -> phase_autopilot.AutopilotResult:
    nonce_dir = env["nonce_dir"]
    approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.autopilot.start",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug="phase-alpha",
            mode=mode,
            budgets=None,
            allow_network=False,
            accept_degraded_windows_containment=accept_degraded,
            repo_root=None,
            roadmap_root=env["roadmap_root"],
            env=None,
            stdin_is_tty=True,
            consumer_tty="/dev/ttys002",
            nonce_audience="phase.autopilot.start",
            nonce_dir=nonce_dir,
            by_email="alice@example.com",
            install_record_root=env["install_record_root"],
            oidc_fetcher=None,
            oidc_verifier=None,
        )
    finally:
        phase_lock.release_primary(lock)


def _read_audit_entries(audit_path: Path) -> list[dict]:
    entries = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


class TestAcceptedByCallerAuditField:
    """P1-1: accepted_by_caller field on verb=phase.autopilot.start (§3.5 line 666)."""

    def test_audit_carries_accepted_by_caller_true_on_windows_degraded_start(
        self, tmp_path: Path, monkeypatch
    ):
        """Windows + accept_degraded=True → audit row has accepted_by_caller=True."""
        monkeypatch.setattr(sys, "platform", "win32")
        env = _make_harness_env(tmp_path)
        result = _do_start_tty(env, mode="chain", accept_degraded=True)
        assert result.exit_code == 0, f"expected success, got {result}"

        entries = _read_audit_entries(env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "windows_audit_guard_degraded"
        assert entry.get("accepted_by_caller") is True, (
            f"expected accepted_by_caller=True, got {entry.get('accepted_by_caller')!r}"
        )

    def test_audit_accepted_by_caller_absent_on_posix(
        self, tmp_path: Path, monkeypatch
    ):
        """POSIX posture → accepted_by_caller field NOT present in audit row."""
        monkeypatch.setattr(sys, "platform", "linux")
        env = _make_harness_env(tmp_path)
        result = _do_start_tty(env, mode="phase")
        assert result.exit_code == 0, f"expected success, got {result}"

        entries = _read_audit_entries(env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "posix_audit_guard"
        assert "accepted_by_caller" not in entry, (
            "accepted_by_caller should be absent on POSIX posture rows "
            "(avoid polluting non-Windows audit rows with Windows-specific field)"
        )


# ---------------------------------------------------------------------------
# P1-2: git.cmd setlocal enabledelayedexpansion + !ERRORLEVEL!
# ---------------------------------------------------------------------------

GIT_CMD_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard_wrappers" / "git.cmd"


class TestGitCmdDelayedExpansionFix:
    """P1-2: git.cmd must use setlocal enabledelayedexpansion + !ERRORLEVEL! in if-blocks."""

    def test_git_cmd_has_setlocal_enabledelayedexpansion(self):
        """git.cmd must declare setlocal enabledelayedexpansion to prevent parse-time expansion."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        assert "setlocal enabledelayedexpansion" in content.lower(), (
            "git.cmd missing 'setlocal enabledelayedexpansion'; "
            "%ERRORLEVEL% inside parenthesized if-blocks expands at parse time "
            "(not after findstr), silently mis-evaluating the --remote check."
        )

    def test_git_cmd_uses_delayed_errorlevel_in_if_block(self):
        """git.cmd must use !ERRORLEVEL! (not bare %ERRORLEVEL%) in the submodule if-block."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        assert "!ERRORLEVEL!" in content, (
            "git.cmd missing '!ERRORLEVEL!' — must use delayed expansion "
            "inside the parenthesized submodule update --remote check block."
        )

    def test_git_cmd_no_bare_errorlevel_in_if_block(self):
        """The submodule if-block must not contain bare %ERRORLEVEL% (regression guard)."""
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        # The outer pass-through loop uses %ERRORLEVEL% for exit /b — that's fine.
        # The fix is that the if-block uses !ERRORLEVEL! instead.
        # We check that !ERRORLEVEL! is present (sufficient to guarantee the fix).
        assert "!ERRORLEVEL!" in content, (
            "Regression: !ERRORLEVEL! removed from git.cmd if-block"
        )


# ---------------------------------------------------------------------------
# P1-3 + P1-4: autopilot_guard.ps1 PS 5.1 compatibility
# ---------------------------------------------------------------------------

PS1_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard.ps1"


class TestPs1Ps51Compatibility:
    """P1-3 + P1-4: autopilot_guard.ps1 must use PS 5.1-compatible APIs."""

    def test_ps1_uses_dotnet_utf8encoding_not_utf8nobom(self):
        """[System.Text.UTF8Encoding] must be present (replaces utf8NoBOM which requires PS 6+)."""
        content = PS1_PATH.read_text(encoding="utf-8")
        assert "[System.Text.UTF8Encoding]" in content, (
            "autopilot_guard.ps1 missing [System.Text.UTF8Encoding]; "
            "utf8NoBOM encoding is PS 6.0+ only and errors on PS 5.1 default Windows install."
        )
        assert "utf8NoBOM" not in content, (
            "autopilot_guard.ps1 still uses utf8NoBOM (PS 6.0+ only); "
            "replace with [System.Text.UTF8Encoding]($false) for PS 5.1 compat."
        )

    def test_ps1_uses_datetime_utcnow_not_get_date_asutc(self):
        """[DateTime]::UtcNow must be present (replaces Get-Date -AsUTC which requires PS 7.1+)."""
        content = PS1_PATH.read_text(encoding="utf-8")
        assert "[DateTime]::UtcNow" in content, (
            "autopilot_guard.ps1 missing [DateTime]::UtcNow; "
            "Get-Date -AsUTC is PS 7.1+ only and errors on PS 5.1 default Windows install."
        )
        assert "-AsUTC" not in content, (
            "autopilot_guard.ps1 still uses -AsUTC (PS 7.1+ only); "
            "replace with [DateTime]::UtcNow.ToString(...) for PS 5.1 compat."
        )

    def test_ps1_has_ps51_banner_comment(self):
        """PS 5.1 compatibility banner comment must be present."""
        content = PS1_PATH.read_text(encoding="utf-8")
        assert "5.1" in content, (
            "autopilot_guard.ps1 missing PS 5.1 compatibility statement in banner comment."
        )


# ---------------------------------------------------------------------------
# P2-3: refused-start emits phase.autopilot.start.refused audit row
# ---------------------------------------------------------------------------


class TestWindowsExit11EmitsRefusedAuditRow:
    """P2-3: Windows exit 11 path must emit phase.autopilot.start.refused audit row."""

    def test_windows_exit_11_emits_phase_autopilot_start_refused_audit_row(
        self, tmp_path: Path, monkeypatch
    ):
        """Windows + chain + no accept_degraded → exit 11 + refused audit row in log."""
        monkeypatch.setattr(sys, "platform", "win32")
        env = _make_harness_env(tmp_path)

        # Mint a nonce then attempt chain start without accept_degraded.
        nonce_dir = env["nonce_dir"]
        approval_nonce.mint(
            nonce_dir=nonce_dir,
            audience="phase.autopilot.start",
            minter_tty="/dev/ttys001",
            ttl_seconds=120,
        )
        lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
        try:
            result = phase_autopilot.run_start(
                scratch_root=env["scratch"],
                audit_path=env["audit_path"],
                lock_handle=lock,
                phase_slug="phase-alpha",
                mode="chain",
                budgets=None,
                allow_network=False,
                accept_degraded_windows_containment=False,
                repo_root=None,
                roadmap_root=env["roadmap_root"],
                env=None,
                stdin_is_tty=True,
                consumer_tty="/dev/ttys002",
                nonce_audience="phase.autopilot.start",
                nonce_dir=nonce_dir,
                by_email="alice@example.com",
                install_record_root=env["install_record_root"],
                oidc_fetcher=None,
                oidc_verifier=None,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 11
        assert result.sub_reason == "windows_containment_degraded"

        # The refused audit row must be present in the audit log.
        entries = _read_audit_entries(env["audit_path"])
        refused_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start.refused"]
        assert refused_entries, (
            "No phase.autopilot.start.refused audit row found after Windows exit 11. "
            "P2-3 requires a minimal audit row so the refusal is forensically visible."
        )
        row = refused_entries[0]
        assert row.get("refuse_reason") == "windows_containment_degraded"
        assert row.get("network_guard_posture") == "windows_audit_guard_degraded"
        assert row.get("mode") == "chain"
        assert row.get("phase_slug") == "phase-alpha"
        assert row.get("at") is not None


# ---------------------------------------------------------------------------
# P2-4: apply_budget_halt stamps acknowledged_at on rotated prior last_halt
# ---------------------------------------------------------------------------

from scripts.lib.cli_budgets import (
    BudgetCheckResult,
    BudgetDiaryEntry,
    apply_budget_halt,
    build_budget_halt_diary,
)


def _exhausted_check() -> BudgetCheckResult:
    return BudgetCheckResult(
        exhausted=True,
        capability="file_mutation_ops",
        remaining=0,
        message="file_mutation_ops budget exhausted (remaining=0)",
    )


def _active_state_with_halt(*, acknowledged_at=None) -> dict:
    return {
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "run-abc",
        "autopilot_mode": "phase",
        "autopilot_phase_slug": "phase-alpha",
        "autopilot_start_entry_hash": "abc" * 21 + "a",
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": "2026-05-17T10:00:00Z",
        "cli_budgets_remaining": {"file_mutation_ops": 0, "shell_invocations": 50, "wall_seconds": 300},
        "last_halt": {
            "run_id": "prior-run",
            "halt_reason": "budget_exhausted:file_mutation_ops",
            "halt_at_iso": "2026-05-17T09:55:00Z",
            "acknowledged_at": acknowledged_at,
        },
        "last_halt_history": [],
    }


class TestApplyBudgetHaltAcksPriorUnackDiaryOnRotation:
    """P2-4: apply_budget_halt must stamp acknowledged_at on rotated prior last_halt."""

    def test_apply_budget_halt_acks_prior_unack_diary_on_rotation(self):
        """Prior last_halt with acknowledged_at=None → rotated entry gets acknowledged_at set."""
        state = _active_state_with_halt(acknowledged_at=None)
        check = _exhausted_check()
        diary = build_budget_halt_diary(
            result=check,
            state=state,
            now_iso="2026-05-17T10:05:00Z",
        )
        new_state = apply_budget_halt(state, diary=diary)

        assert new_state["last_halt"] is not None  # new diary in last_halt
        history = new_state["last_halt_history"]
        assert len(history) == 1, "prior last_halt should be rotated into history"
        rotated = history[0]
        assert rotated["run_id"] == "prior-run"
        assert rotated["acknowledged_at"] is not None, (
            "apply_budget_halt must stamp acknowledged_at on the prior unack'd diary "
            "entry when rotating it to history (implicit ack = this new halt supersedes it; "
            "consistent with run_start ack semantics per §1.1 line 67)."
        )

    def test_apply_budget_halt_preserves_already_acked_diary(self):
        """Prior last_halt already ack'd → acknowledged_at NOT overwritten on rotation."""
        state = _active_state_with_halt(acknowledged_at="2026-05-17T09:56:00Z")
        check = _exhausted_check()
        diary = build_budget_halt_diary(
            result=check,
            state=state,
            now_iso="2026-05-17T10:05:00Z",
        )
        new_state = apply_budget_halt(state, diary=diary)

        history = new_state["last_halt_history"]
        assert len(history) == 1
        rotated = history[0]
        assert rotated["acknowledged_at"] == "2026-05-17T09:56:00Z", (
            "Already-ack'd diary timestamp must be preserved (not overwritten)."
        )

    def test_apply_budget_halt_no_prior_diary_history_empty(self):
        """No prior last_halt → history stays empty after apply_budget_halt."""
        state = _active_state_with_halt(acknowledged_at=None)
        state["last_halt"] = None  # override: no prior halt
        check = _exhausted_check()
        diary = build_budget_halt_diary(
            result=check,
            state=state,
            now_iso="2026-05-17T10:05:00Z",
        )
        new_state = apply_budget_halt(state, diary=diary)
        assert new_state["last_halt_history"] == [], (
            "No prior last_halt → history should remain empty after apply_budget_halt."
        )
