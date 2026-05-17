"""S11 — `halt-diary clear` admin verb + §12.12 (execute→done) unack guard.

Design refs:
  - §5.3  — halt diary contract
  - §12.7 — halt-diary clear registered as TTY-required verb
  - §12.12 — (execute→done) transition validator must refuse on last_halt_unacknowledged
  - §1.1  — last_halt schema (acknowledged_at, last_halt_history cap=5)

Tests target:
  A. `scripts/lib/halt_diary.py:run_clear` — fault classes + happy path
  B. `scripts/lib/transition.py:validate_transition_with_state` — §12.12 guard
  C. `scripts/lib/phase_autopilot.py:run_start` — rotates prior last_halt
  D. Fixture round-trip validation
  E. CLI argparse smoke (xfail until confirmed)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from scripts.lib import halt_diary, phase_lock, phase_txn, transition
from scripts.lib.halt_diary import ClearResult, run_clear


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
_HALT_DIARY_FIXTURES = _FIXTURES_ROOT / "halt_diary"


def _make_seed_state(
    *,
    phase: str = "execute",
    execution_mode: str = "manual",
    last_halt: Optional[dict] = None,
    last_halt_history: Optional[list] = None,
    approved: bool = True,
    approved_at: str = "2026-05-18T10:00:00Z",
    execute_attempt_started_at: str = "2026-05-18T10:00:00Z",
) -> dict:
    return {
        "phase": phase,
        "approved": approved,
        "approved_at": approved_at,
        "approved_by": "alice@example.com",
        "execution_mode": execution_mode,
        "state_schema_version": 2,
        "verification": ["pytest tests/ -q"],
        "allowed_paths": ["scripts/"],
        "draft_verification": None,
        "draft_allowed_paths": None,
        "plan_finalized_at": "2026-05-18T09:50:00Z",
        "execute_attempt_started_at": execute_attempt_started_at,
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "autopilot_allow_network": False,
        "autopilot_started_at_iso": None,
        "cli_budgets_remaining": None,
        "last_halt": last_halt,
        "last_halt_history": last_halt_history if last_halt_history is not None else [],
    }


def _sample_diary(*, acknowledged_at: Optional[str] = None) -> dict:
    return {
        "run_id": "abc123",
        "mode": "phase_autopilot",
        "phase_slug": "02c-hardening",
        "last_successful_transition": None,
        "halt_reason": "budget_exhausted:file_mutation_ops",
        "halt_at_iso": "2026-05-18T09:55:00Z",
        "suggested_next_command": "harness phase autopilot stop --reason 'budget exhausted'",
        "suggested_next_command_requires_human": False,
        "acknowledged_at": acknowledged_at,
    }


def _seed_env(
    tmp_path: Path,
    *,
    state: dict,
) -> dict:
    """Create a primed harness environment with the given initial state."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=phase_txn.TxnRequest(
                action="seed",
                before_state=None,
                after_state=state,
                audit_entry_draft={"verb": "seed", "args": {}},
            ),
            audit_path=audit_path,
        )
    finally:
        phase_lock.release_primary(lock)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
    }


# ---------------------------------------------------------------------------
# A. run_clear — fault classes
# ---------------------------------------------------------------------------


class TestRunClearFaultClasses:
    """A. run_clear fault classes per §5.3 + §12.7."""

    def test_non_tty_blocked(self, tmp_path: Path):
        """Non-TTY → exit 6 sub=non_tty_halt_diary_clear_blocked."""
        env = _seed_env(tmp_path, state=_make_seed_state())
        scratch = env["scratch"]
        audit_path = env["audit_path"]
        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                stdin_is_tty=False,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 6
        assert result.sub_reason == "non_tty_halt_diary_clear_blocked"
        assert result.cleared is False

    def test_anchor_fail_closed(self, tmp_path: Path):
        """anchor_verified=False → exit 6 sub=anchor_preflight_unwired (fail-closed)."""
        env = _seed_env(tmp_path, state=_make_seed_state())
        scratch = env["scratch"]
        audit_path = env["audit_path"]
        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=False,  # <-- fail-closed
                stdin_is_tty=True,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 6
        assert result.sub_reason == "anchor_preflight_unwired"
        assert result.cleared is False

    def test_nothing_to_clear_no_diary(self, tmp_path: Path):
        """last_halt=None → exit 0 sub=nothing_to_clear (no audit row written)."""
        env = _seed_env(tmp_path, state=_make_seed_state(last_halt=None))
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        # Count audit lines before.
        lines_before = (
            audit_path.read_text(encoding="utf-8").strip().splitlines()
            if audit_path.exists()
            else []
        )

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                stdin_is_tty=True,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0
        assert result.sub_reason == "nothing_to_clear"
        assert result.cleared is False

        # No audit row added.
        lines_after = (
            audit_path.read_text(encoding="utf-8").strip().splitlines()
            if audit_path.exists()
            else []
        )
        assert len(lines_after) == len(lines_before)

    def test_lock_missing_raises(self, tmp_path: Path):
        """No lock held → TxnLockMissingError raised."""
        env = _seed_env(
            tmp_path,
            state=_make_seed_state(last_halt=_sample_diary()),
        )
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        with pytest.raises(phase_txn.TxnLockMissingError):
            run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=None,
                anchor_verified=True,
                stdin_is_tty=True,
            )


# ---------------------------------------------------------------------------
# A. run_clear — happy path
# ---------------------------------------------------------------------------


class TestRunClearHappyPath:
    """A. run_clear happy path: diary → history, last_halt=None, audit row."""

    def test_clears_diary_and_rotates_to_history(self, tmp_path: Path):
        """last_halt non-null + stdin_is_tty=True → cleared, last_halt=None,
        diary in last_halt_history with acknowledged_at populated."""
        diary = _sample_diary(acknowledged_at=None)
        env = _seed_env(tmp_path, state=_make_seed_state(last_halt=diary))
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                stdin_is_tty=True,
                by="alice@example.com",
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0
        assert result.sub_reason == "cleared"
        assert result.cleared is True

        # Verify state on disk.
        state_path = scratch / phase_txn.STATE_NAME
        after_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert after_state["last_halt"] is None
        assert len(after_state["last_halt_history"]) == 1
        hist_entry = after_state["last_halt_history"][0]
        assert hist_entry["run_id"] == "abc123"
        assert hist_entry["acknowledged_at"] is not None  # stamped

        # Verify audit row.
        assert audit_path.exists()
        last_line = audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        row = json.loads(last_line)
        assert row["verb"] == "halt_diary.clear"
        assert row["by"] == "alice@example.com"
        assert row.get("cleared_diary") is not None
        assert row["cleared_diary"]["run_id"] == "abc123"

    def test_already_acked_diary_still_clears(self, tmp_path: Path):
        """Diary with acknowledged_at already set: still clears, doesn't double-stamp."""
        diary = _sample_diary(acknowledged_at="2026-05-18T10:00:00Z")
        env = _seed_env(tmp_path, state=_make_seed_state(last_halt=diary))
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                stdin_is_tty=True,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0
        assert result.cleared is True
        state_path = scratch / phase_txn.STATE_NAME
        after_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert after_state["last_halt"] is None
        assert len(after_state["last_halt_history"]) == 1
        # Original ack preserved (not overwritten).
        assert after_state["last_halt_history"][0]["acknowledged_at"] == "2026-05-18T10:00:00Z"

    def test_cap_5_enforced(self, tmp_path: Path):
        """Existing 5-entry history: adding one more drops oldest (cap=5)."""
        old_history = [
            {
                "run_id": f"old-{i}",
                "halt_at_iso": f"2026-05-18T0{i}:00:00Z",
                "acknowledged_at": f"2026-05-18T0{i}:01:00Z",
            }
            for i in range(5)
        ]
        diary = _sample_diary(acknowledged_at=None)
        env = _seed_env(
            tmp_path,
            state=_make_seed_state(last_halt=diary, last_halt_history=old_history),
        )
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = run_clear(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                stdin_is_tty=True,
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0
        state_path = scratch / phase_txn.STATE_NAME
        after_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert after_state["last_halt"] is None
        # Cap 5 enforced: 5 old + 1 new → 5 total (oldest dropped).
        assert len(after_state["last_halt_history"]) == 5
        # Last entry is the newly cleared diary.
        assert after_state["last_halt_history"][-1]["run_id"] == "abc123"


# ---------------------------------------------------------------------------
# B. §12.12 (execute→done) transition validator: last_halt_unacknowledged
# ---------------------------------------------------------------------------


class TestExecuteToDoneUnackGuard:
    """B. §12.12 — (execute→done) refuses when last_halt unacknowledged."""

    def _valid_state(self, **overrides) -> dict:
        state = {
            "phase": "execute",
            "approved": True,
            "approved_at": "2026-05-18T10:30:00Z",
            "plan_finalized_at": "2026-05-18T09:50:00Z",
            "execute_attempt_started_at": "2026-05-18T10:00:00Z",
            "execution_mode": "manual",
            "verification": ["pytest tests/ -q"],
            "allowed_paths": ["scripts/"],
        }
        state.update(overrides)
        return state

    def test_refuses_when_last_halt_acknowledged_at_null(self):
        """last_halt present, acknowledged_at=None → exit 2 sub=last_halt_unacknowledged."""
        state = self._valid_state(
            last_halt=_sample_diary(acknowledged_at=None),
        )
        with pytest.raises(SystemExit) as exc_info:
            transition.validate_transition_with_state(
                state, "done", reset_approval=False
            )
        assert exc_info.value.code == 2
        assert isinstance(exc_info.value, transition.StaleApprovalError)
        assert exc_info.value.sub_reason == "last_halt_unacknowledged"

    def test_fix_line_mentions_halt_diary_clear(self):
        """Fix: message must reference 'halt-diary clear'."""
        state = self._valid_state(
            last_halt=_sample_diary(acknowledged_at=None),
        )
        with pytest.raises(transition.StaleApprovalError) as exc_info:
            transition.validate_transition_with_state(
                state, "done", reset_approval=False
            )
        msg = exc_info.value.format_message()
        assert "halt-diary clear" in msg

    def test_fix_line_mentions_phase_reopen(self):
        """Fix: message must also reference 'phase reopen --to plan'."""
        state = self._valid_state(
            last_halt=_sample_diary(acknowledged_at=None),
        )
        with pytest.raises(transition.StaleApprovalError) as exc_info:
            transition.validate_transition_with_state(
                state, "done", reset_approval=False
            )
        msg = exc_info.value.format_message()
        assert "phase reopen" in msg

    def test_accepts_when_last_halt_acknowledged_at_set(self):
        """last_halt.acknowledged_at non-null → accepted (no exception)."""
        state = self._valid_state(
            last_halt=_sample_diary(acknowledged_at="2026-05-18T10:05:00Z"),
        )
        # Should not raise.
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )

    def test_accepts_when_last_halt_is_null(self):
        """last_halt=None → accepted (regression — existing behavior preserved)."""
        state = self._valid_state(last_halt=None)
        # Should not raise.
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )

    def test_accepts_when_last_halt_absent_from_state(self):
        """State without last_halt key at all → accepted (backward compat)."""
        state = self._valid_state()
        # Should not raise.
        transition.validate_transition_with_state(
            state, "done", reset_approval=False
        )


# ---------------------------------------------------------------------------
# C. phase_autopilot.run_start — rotates prior last_halt into history
# ---------------------------------------------------------------------------


class TestRunStartRotatesLastHalt:
    """C. run_start rotates prior last_halt → history before stamping new run."""

    def _make_env(self, tmp_path: Path, *, last_halt: Optional[dict] = None) -> dict:
        from scripts.lib import phase_txn, phase_lock

        scratch = tmp_path / ".scratch"
        scratch.mkdir()
        harness = tmp_path / ".harness"
        harness.mkdir()
        audit_path = harness / "audit.log"

        state = _make_seed_state(
            phase="plan",
            execution_mode="manual",
            last_halt=last_halt,
            last_halt_history=[],
            # Clear exec-centric fields for plan phase.
            execute_attempt_started_at=None,
            approved=False,
            approved_at=None,
        )
        # Override execute-specific fields to None for plan phase.
        state["execute_attempt_started_at"] = None
        state["approved"] = False
        state["approved_at"] = None

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            phase_txn.commit_transaction(
                scratch,
                lock=lock,
                request=phase_txn.TxnRequest(
                    action="seed",
                    before_state=None,
                    after_state=state,
                    audit_entry_draft={"verb": "seed", "args": {}},
                ),
                audit_path=audit_path,
            )
        finally:
            phase_lock.release_primary(lock)

        planning = tmp_path / ".planning" / "phases"
        planning.mkdir(parents=True)
        (planning / "phase-alpha").mkdir()
        (planning / "phase-beta").mkdir()

        install_record = {
            "harness_version": "v0.7.0",
            "installed_at": "2026-05-18T03:14:15Z",
            "adapters": ["roo"],
            "git_present_at_install": True,
            "approvers": [
                {
                    "email": "ci-bot@example.com",
                    "added_at": "2026-05-18T03:14:15Z",
                    "source": "gitconfig_auto",
                }
            ],
        }
        (harness / "install-record.json").write_text(
            json.dumps(install_record, indent=2) + "\n"
        )

        return {
            "tmp_path": tmp_path,
            "scratch": scratch,
            "harness": harness,
            "audit_path": audit_path,
            "roadmap_root": planning,
        }

    def _ci_env(self) -> dict:
        return {
            "HARNESS_AUTOMATION": "phase",
            "HARNESS_BY_TRUST": "ci-bot@example.com",
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "999",
            "GITHUB_REPOSITORY": "org/repo",
            "GITHUB_SHA": "abc123",
            "GITHUB_WORKFLOW": "ci.yml",
            "GITHUB_RUN_ATTEMPT": "1",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
        }

    def _fake_oidc_fetcher(self, url: str) -> str:
        return "fake-token"

    def _fake_oidc_verifier(self, token: str, expected_claims: dict) -> dict:
        return {
            "iss": "https://token.actions.githubusercontent.com",
            "sub": "repo:org/repo:ref:refs/heads/main",
            "repository": "org/repo",
            "ref": "refs/heads/main",
            "sha": "abc123",
        }

    def _do_start(self, env: dict) -> object:
        from scripts.lib import phase_autopilot, phase_lock

        scratch = env["scratch"]
        audit_path = env["audit_path"]
        roadmap_root = env["roadmap_root"]

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = phase_autopilot.run_start(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                phase_slug="phase-alpha",
                mode="phase",
                budgets=None,
                allow_network=False,
                anchor_verified=True,
                skip_anchor_preflight=True,
                repo_root=None,
                roadmap_root=roadmap_root,
                env=self._ci_env(),
                stdin_is_tty=False,
                oidc_fetcher=self._fake_oidc_fetcher,
                oidc_verifier=self._fake_oidc_verifier,
            )
        finally:
            phase_lock.release_primary(lock)
        return result

    def test_run_start_rotates_prior_last_halt_into_history(self, tmp_path: Path):
        """run_start: prior last_halt non-null → after.last_halt=None,
        after.last_halt_history[-1] is moved diary with acknowledged_at set."""
        diary = _sample_diary(acknowledged_at=None)
        env = self._make_env(tmp_path, last_halt=diary)

        result = self._do_start(env)
        assert result.exit_code == 0

        scratch = env["scratch"]
        state_path = scratch / phase_txn.STATE_NAME
        after_state = json.loads(state_path.read_text(encoding="utf-8"))

        assert after_state["last_halt"] is None
        assert len(after_state["last_halt_history"]) == 1
        hist_entry = after_state["last_halt_history"][-1]
        assert hist_entry["run_id"] == "abc123"
        assert hist_entry["acknowledged_at"] is not None  # implicit ack by new run

    def test_run_start_no_last_halt_history_unchanged(self, tmp_path: Path):
        """run_start with no prior diary: last_halt_history stays empty."""
        env = self._make_env(tmp_path, last_halt=None)
        result = self._do_start(env)
        assert result.exit_code == 0

        scratch = env["scratch"]
        state_path = scratch / phase_txn.STATE_NAME
        after_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert after_state["last_halt"] is None
        assert after_state.get("last_halt_history", []) == []

    def test_run_start_history_cap_5(self, tmp_path: Path):
        """History never exceeds 5 entries even after many run_start calls."""
        # Seed with an already-existing 5-item history + a current last_halt.
        old_history = [
            {
                "run_id": f"hist-{i}",
                "halt_at_iso": f"2026-05-18T0{i}:00:00Z",
                "acknowledged_at": f"2026-05-18T0{i}:01:00Z",
            }
            for i in range(5)
        ]
        diary = _sample_diary(acknowledged_at=None)
        env = self._make_env(tmp_path, last_halt=diary)

        # Manually set the history in the seeded state via a second txn.
        scratch = env["scratch"]
        audit_path = env["audit_path"]
        state_path = scratch / phase_txn.STATE_NAME
        current = json.loads(state_path.read_text(encoding="utf-8"))
        current["last_halt_history"] = old_history
        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            phase_txn.commit_transaction(
                scratch,
                lock=lock,
                request=phase_txn.TxnRequest(
                    action="seed2",
                    before_state=current,
                    after_state=current,
                    audit_entry_draft={"verb": "seed2", "args": {}},
                ),
                audit_path=audit_path,
            )
        finally:
            phase_lock.release_primary(lock)

        result = self._do_start(env)
        assert result.exit_code == 0

        after_state = json.loads(state_path.read_text(encoding="utf-8"))
        assert after_state["last_halt"] is None
        assert len(after_state["last_halt_history"]) <= 5


# ---------------------------------------------------------------------------
# D. Fixture round-trip validation
# ---------------------------------------------------------------------------


class TestFixtureRoundTrip:
    """D. Validate that the test fixtures are valid JSON with required fields."""

    def test_recent_halt_fixture_has_last_halt_unacknowledged(self):
        fixture_path = _HALT_DIARY_FIXTURES / "recent_halt" / "phase-state.json"
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        state = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert state.get("last_halt") is not None
        assert state["last_halt"].get("acknowledged_at") is None

    def test_cleared_on_restart_fixture_has_null_last_halt(self):
        fixture_path = _HALT_DIARY_FIXTURES / "cleared_on_restart" / "phase-state.json"
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        state = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert state.get("last_halt") is None
        history = state.get("last_halt_history", [])
        assert len(history) >= 1
        # History entry must have acknowledged_at set (implicit ack by new run).
        assert history[-1].get("acknowledged_at") is not None


# ---------------------------------------------------------------------------
# E. CLI argparse smoke test
# ---------------------------------------------------------------------------


class TestArgparseRouting:
    """E. Argparse + dispatch wiring smoke for `harness halt-diary clear`."""

    def test_cli_harness_halt_diary_clear_routes_through_run_clear(
        self, monkeypatch, tmp_path
    ):
        """Argparse routing: `harness halt-diary clear` dispatches to
        halt_diary_cli.cmd_halt_diary_clear which calls halt_diary.run_clear.

        Verifies the wiring without a real lock or anchor (uses monkeypatching).
        """
        import sys as _sys
        import types

        # Build a minimal args namespace.
        args = types.SimpleNamespace(
            command="halt-diary",
            halt_diary_command="clear",
            by="alice@example.com",
        )

        captured: list = []

        def fake_run_clear(**kwargs):
            captured.append(kwargs)
            return ClearResult(
                exit_code=0,
                sub_reason="cleared",
                message='{"ok": true}',
                cleared=True,
            )

        from scripts.lib import halt_diary_cli, halt_diary as _hd

        monkeypatch.setattr(_hd, "run_clear", fake_run_clear)

        # Patch the internal helpers so it doesn't need a real repo.
        monkeypatch.setattr(
            halt_diary_cli,
            "_cwd_repo_root",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            halt_diary_cli,
            "_verify_anchor",
            lambda cwd: (True, 0, ""),
        )

        # Also patch phase_lock and phase_preflight to avoid real disk access.
        from scripts.lib import phase_lock as _pl, phase_preflight as _pp

        class FakeLock:
            pass

        monkeypatch.setattr(_pl, "acquire_primary", lambda *a, **k: FakeLock())
        monkeypatch.setattr(_pl, "release_primary", lambda lock: None)
        monkeypatch.setattr(_pp, "run_state_trust_preflight", lambda **k: None)
        monkeypatch.setattr(_pp, "default_gitconfig_email_lookup", lambda: "alice@example.com")

        # Monkey-patch scratch/audit paths on the module so they resolve to tmp_path.
        monkeypatch.setattr(halt_diary_cli, "SCRATCH_ROOT", tmp_path / ".scratch")
        monkeypatch.setattr(halt_diary_cli, "AUDIT_PATH", tmp_path / ".harness" / "audit.log")
        (tmp_path / ".scratch").mkdir(exist_ok=True)
        (tmp_path / ".harness").mkdir(exist_ok=True)

        exit_code = halt_diary_cli.cmd_halt_diary_clear(args)
        assert exit_code == 0
        assert len(captured) == 1
        assert captured[0]["stdin_is_tty"] == _sys.stdin.isatty()
