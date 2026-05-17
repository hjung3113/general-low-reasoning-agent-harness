"""Tests for scripts/lib/cli_budgets.py — budget decrement helpers,
exhaustion check, and halt-diary builder per §1.1, §3.5, §5.3.

RED phase: written before implementation exists (TDD discipline).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.cli_budgets import (
    CAPABILITIES,
    BudgetCheckResult,
    BudgetDiaryEntry,
    apply_budget_halt,
    budget_check,
    build_budget_halt_diary,
    clear_autopilot_started_at,
    decrement,
    stamp_autopilot_started_at,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_state(
    *,
    execution_mode: str = "autopilot",
    shell_invocations: int | None = 10,
    file_mutation_ops: int | None = 5,
    wall_seconds: int | None = 120,
    autopilot_started_at_iso: str | None = None,
    autopilot_run_id: str | None = "run-abc",
    autopilot_phase_slug: str | None = "execute",
    autopilot_mode: str | None = "step",
    autopilot_start_entry_hash: str | None = "deadbeef",
    autopilot_allow_network: bool = False,
    last_halt: dict | None = None,
    last_halt_history: list | None = None,
) -> dict:
    budgets = None
    if shell_invocations is not None or file_mutation_ops is not None or wall_seconds is not None:
        budgets = {}
        if shell_invocations is not None:
            budgets["shell_invocations"] = shell_invocations
        if file_mutation_ops is not None:
            budgets["file_mutation_ops"] = file_mutation_ops
        if wall_seconds is not None:
            budgets["wall_seconds"] = wall_seconds

    return {
        "execution_mode": execution_mode,
        "cli_budgets_remaining": budgets,
        "autopilot_started_at_iso": autopilot_started_at_iso,
        "autopilot_run_id": autopilot_run_id,
        "autopilot_phase_slug": autopilot_phase_slug,
        "autopilot_mode": autopilot_mode,
        "autopilot_start_entry_hash": autopilot_start_entry_hash,
        "autopilot_allow_network": autopilot_allow_network,
        "last_halt": last_halt,
        "last_halt_history": last_halt_history or [],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_offset(seconds: int) -> str:
    """Return an ISO-Z string for `seconds` ago (negative = future)."""
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CAPABILITIES constant
# ---------------------------------------------------------------------------


def test_capabilities_constant_has_all_three():
    assert set(CAPABILITIES) == {"shell_invocations", "file_mutation_ops", "wall_seconds"}


# ---------------------------------------------------------------------------
# budget_check — None budgets
# ---------------------------------------------------------------------------


def test_budget_check_none_budgets_returns_not_exhausted():
    state = _make_state(shell_invocations=None, file_mutation_ops=None, wall_seconds=None)
    result = budget_check(state, capability="shell_invocations")
    assert isinstance(result, BudgetCheckResult)
    assert result.exhausted is False


def test_budget_check_none_budgets_file_mutation_ops_returns_not_exhausted():
    state = _make_state(shell_invocations=None, file_mutation_ops=None, wall_seconds=None)
    result = budget_check(state, capability="file_mutation_ops")
    assert result.exhausted is False


# ---------------------------------------------------------------------------
# budget_check — manual mode
# ---------------------------------------------------------------------------


def test_budget_check_manual_mode_returns_not_exhausted_even_with_budgets():
    state = _make_state(execution_mode="manual", shell_invocations=0)
    result = budget_check(state, capability="shell_invocations")
    assert result.exhausted is False


def test_budget_check_manual_mode_wall_seconds_not_exhausted():
    state = _make_state(
        execution_mode="manual",
        wall_seconds=10,
        autopilot_started_at_iso=_iso_offset(100),
    )
    result = budget_check(state, capability="wall_seconds")
    assert result.exhausted is False


# ---------------------------------------------------------------------------
# budget_check — shell_invocations
# ---------------------------------------------------------------------------


def test_budget_check_shell_invocations_zero_exhausted():
    state = _make_state(shell_invocations=0)
    result = budget_check(state, capability="shell_invocations")
    assert result.exhausted is True
    assert result.capability == "shell_invocations"
    assert result.remaining == 0


def test_budget_check_shell_invocations_below_zero_exhausted():
    state = _make_state(shell_invocations=-1)
    result = budget_check(state, capability="shell_invocations")
    assert result.exhausted is True
    assert result.remaining == 0


def test_budget_check_shell_invocations_five_not_exhausted():
    state = _make_state(shell_invocations=5)
    result = budget_check(state, capability="shell_invocations")
    assert result.exhausted is False
    assert result.capability is None
    assert result.remaining == 5


def test_budget_check_shell_invocations_result_has_message():
    state = _make_state(shell_invocations=0)
    result = budget_check(state, capability="shell_invocations")
    assert isinstance(result.message, str)
    assert len(result.message) > 0


# ---------------------------------------------------------------------------
# budget_check — file_mutation_ops
# ---------------------------------------------------------------------------


def test_budget_check_file_mutation_ops_zero_exhausted():
    state = _make_state(file_mutation_ops=0)
    result = budget_check(state, capability="file_mutation_ops")
    assert result.exhausted is True
    assert result.capability == "file_mutation_ops"
    assert result.remaining == 0


def test_budget_check_file_mutation_ops_positive_not_exhausted():
    state = _make_state(file_mutation_ops=3)
    result = budget_check(state, capability="file_mutation_ops")
    assert result.exhausted is False
    assert result.remaining == 3


# ---------------------------------------------------------------------------
# budget_check — wall_seconds
# ---------------------------------------------------------------------------


def test_budget_check_wall_seconds_exceeded_exhausted():
    # 100 seconds elapsed, budget is 60 → exhausted
    state = _make_state(
        wall_seconds=60,
        autopilot_started_at_iso=_iso_offset(100),
    )
    result = budget_check(state, capability="wall_seconds", now_iso=_now_iso())
    assert result.exhausted is True
    assert result.capability == "wall_seconds"


def test_budget_check_wall_seconds_not_exceeded_not_exhausted():
    # 30 seconds elapsed, budget is 60 → not exhausted, ~30 remaining
    state = _make_state(
        wall_seconds=60,
        autopilot_started_at_iso=_iso_offset(30),
    )
    result = budget_check(state, capability="wall_seconds", now_iso=_now_iso())
    assert result.exhausted is False
    assert result.remaining == pytest.approx(30, abs=2)


def test_budget_check_wall_seconds_no_anchor_returns_not_exhausted():
    # No autopilot_started_at_iso → cannot compute elapsed → skip check
    state = _make_state(
        wall_seconds=10,
        autopilot_started_at_iso=None,
    )
    result = budget_check(state, capability="wall_seconds", now_iso=_now_iso())
    assert result.exhausted is False


def test_budget_check_wall_seconds_now_iso_optional():
    # now_iso defaults to None — implementation may use datetime.now internally
    state = _make_state(
        wall_seconds=60,
        autopilot_started_at_iso=_iso_offset(30),
    )
    result = budget_check(state, capability="wall_seconds")
    assert result.exhausted is False


# ---------------------------------------------------------------------------
# decrement — shell_invocations
# ---------------------------------------------------------------------------


def test_decrement_shell_invocations_by_one():
    state = _make_state(shell_invocations=5)
    new_state = decrement(state, capability="shell_invocations")
    assert new_state["cli_budgets_remaining"]["shell_invocations"] == 4


def test_decrement_shell_invocations_custom_by():
    state = _make_state(shell_invocations=10)
    new_state = decrement(state, capability="shell_invocations", by=3)
    assert new_state["cli_budgets_remaining"]["shell_invocations"] == 7


def test_decrement_clamps_at_zero_not_negative():
    state = _make_state(shell_invocations=1)
    new_state = decrement(state, capability="shell_invocations", by=5)
    assert new_state["cli_budgets_remaining"]["shell_invocations"] == 0


def test_decrement_does_not_mutate_original_state():
    state = _make_state(shell_invocations=5)
    original = copy.deepcopy(state)
    _ = decrement(state, capability="shell_invocations")
    assert state == original


def test_decrement_file_mutation_ops():
    state = _make_state(file_mutation_ops=8)
    new_state = decrement(state, capability="file_mutation_ops", by=2)
    assert new_state["cli_budgets_remaining"]["file_mutation_ops"] == 6


# ---------------------------------------------------------------------------
# decrement — wall_seconds is a no-op
# ---------------------------------------------------------------------------


def test_decrement_wall_seconds_is_noop():
    state = _make_state(wall_seconds=100)
    new_state = decrement(state, capability="wall_seconds")
    assert new_state["cli_budgets_remaining"]["wall_seconds"] == 100


# ---------------------------------------------------------------------------
# decrement — None budgets is a no-op
# ---------------------------------------------------------------------------


def test_decrement_none_budgets_returns_state_unchanged():
    state = _make_state(shell_invocations=None, file_mutation_ops=None, wall_seconds=None)
    new_state = decrement(state, capability="shell_invocations")
    assert new_state["cli_budgets_remaining"] is None


# ---------------------------------------------------------------------------
# stamp_autopilot_started_at / clear_autopilot_started_at
# ---------------------------------------------------------------------------


def test_stamp_autopilot_started_at_sets_field():
    state = _make_state(autopilot_started_at_iso=None)
    now = _now_iso()
    new_state = stamp_autopilot_started_at(state, now_iso=now)
    assert new_state["autopilot_started_at_iso"] == now


def test_stamp_autopilot_started_at_replaces_existing():
    # Design choice: REPLACE on every start (resets wall-clock anchor).
    old_ts = _iso_offset(200)
    state = _make_state(autopilot_started_at_iso=old_ts)
    new_ts = _now_iso()
    new_state = stamp_autopilot_started_at(state, now_iso=new_ts)
    assert new_state["autopilot_started_at_iso"] == new_ts


def test_stamp_autopilot_started_at_does_not_mutate_original():
    state = _make_state(autopilot_started_at_iso=None)
    original = copy.deepcopy(state)
    _ = stamp_autopilot_started_at(state, now_iso=_now_iso())
    assert state == original


def test_clear_autopilot_started_at_sets_none():
    state = _make_state(autopilot_started_at_iso=_now_iso())
    new_state = clear_autopilot_started_at(state)
    assert new_state["autopilot_started_at_iso"] is None


def test_clear_autopilot_started_at_does_not_mutate_original():
    state = _make_state(autopilot_started_at_iso=_now_iso())
    original = copy.deepcopy(state)
    _ = clear_autopilot_started_at(state)
    assert state == original


def test_stamp_clear_round_trip():
    state = _make_state(autopilot_started_at_iso=None)
    now = _now_iso()
    stamped = stamp_autopilot_started_at(state, now_iso=now)
    cleared = clear_autopilot_started_at(stamped)
    assert cleared["autopilot_started_at_iso"] is None


# ---------------------------------------------------------------------------
# build_budget_halt_diary
# ---------------------------------------------------------------------------


def _make_exhausted_result(capability: str = "shell_invocations") -> BudgetCheckResult:
    return BudgetCheckResult(
        exhausted=True,
        capability=capability,
        remaining=0,
        message=f"{capability} budget exhausted",
    )


def test_build_budget_halt_diary_required_fields():
    state = _make_state()
    result = _make_exhausted_result("shell_invocations")
    now = _now_iso()
    diary = build_budget_halt_diary(result=result, state=state, now_iso=now)

    assert isinstance(diary, BudgetDiaryEntry)
    assert diary.at == now
    assert diary.reason == "budget_exhausted:shell_invocations"
    assert diary.capability == "shell_invocations"
    assert diary.remaining_at_halt == 0
    assert diary.autopilot_run_id == "run-abc"
    assert diary.autopilot_phase_slug == "execute"
    assert "budget" in diary.suggested_next_command.lower() or "stop" in diary.suggested_next_command
    assert diary.suggested_next_command_requires_human is False
    assert diary.acknowledged_at is None


def test_build_budget_halt_diary_no_verb_key():
    # S04 review-fix lesson: last_halt must NOT contain a 'verb' field
    state = _make_state()
    result = _make_exhausted_result()
    diary = build_budget_halt_diary(result=result, state=state, now_iso=_now_iso())
    diary_dict = diary.__dict__
    assert "verb" not in diary_dict


def test_build_budget_halt_diary_file_mutation_ops():
    state = _make_state()
    result = _make_exhausted_result("file_mutation_ops")
    diary = build_budget_halt_diary(result=result, state=state, now_iso=_now_iso())
    assert diary.capability == "file_mutation_ops"
    assert diary.reason == "budget_exhausted:file_mutation_ops"


def test_build_budget_halt_diary_wall_seconds():
    state = _make_state()
    result = _make_exhausted_result("wall_seconds")
    diary = build_budget_halt_diary(result=result, state=state, now_iso=_now_iso())
    assert diary.capability == "wall_seconds"
    assert diary.reason == "budget_exhausted:wall_seconds"


def test_build_budget_halt_diary_null_run_id_when_state_has_none():
    state = _make_state(autopilot_run_id=None, autopilot_phase_slug=None)
    result = _make_exhausted_result()
    diary = build_budget_halt_diary(result=result, state=state, now_iso=_now_iso())
    assert diary.autopilot_run_id is None
    assert diary.autopilot_phase_slug is None


def test_build_budget_halt_diary_suggested_next_command_is_string():
    state = _make_state()
    result = _make_exhausted_result()
    diary = build_budget_halt_diary(result=result, state=state, now_iso=_now_iso())
    assert isinstance(diary.suggested_next_command, str)
    assert len(diary.suggested_next_command) > 0


# ---------------------------------------------------------------------------
# apply_budget_halt
# ---------------------------------------------------------------------------


def _make_diary() -> BudgetDiaryEntry:
    return BudgetDiaryEntry(
        at=_now_iso(),
        reason="budget_exhausted:shell_invocations",
        capability="shell_invocations",
        remaining_at_halt=0,
        autopilot_run_id="run-abc",
        autopilot_phase_slug="execute",
        suggested_next_command="harness phase autopilot stop --reason 'budget exhausted'",
        suggested_next_command_requires_human=False,
        acknowledged_at=None,
    )


def test_apply_budget_halt_sets_manual_mode():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert new_state["execution_mode"] == "manual"


def test_apply_budget_halt_clears_autopilot_identity_fields():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert new_state["autopilot_run_id"] is None
    assert new_state["autopilot_mode"] is None
    assert new_state["autopilot_phase_slug"] is None
    assert new_state["autopilot_start_entry_hash"] is None
    assert new_state["autopilot_allow_network"] is None
    assert new_state["autopilot_started_at_iso"] is None


def test_apply_budget_halt_clears_cli_budgets_remaining():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert new_state["cli_budgets_remaining"] is None


def test_apply_budget_halt_populates_last_halt():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert new_state["last_halt"] == diary.__dict__


def test_apply_budget_halt_last_halt_no_verb_key():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert "verb" not in new_state["last_halt"]


def test_apply_budget_halt_last_halt_has_suggested_next_command_requires_human():
    state = _make_state()
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert "suggested_next_command_requires_human" in new_state["last_halt"]
    assert new_state["last_halt"]["suggested_next_command_requires_human"] is False


def test_apply_budget_halt_last_halt_history_grows():
    state = _make_state(last_halt_history=[])
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    # history itself doesn't grow (no prior last_halt to rotate)
    assert isinstance(new_state["last_halt_history"], list)


def test_apply_budget_halt_rotates_prior_last_halt_to_history():
    prior = {
        "at": _iso_offset(300),
        "reason": "budget_exhausted:file_mutation_ops",
        "capability": "file_mutation_ops",
        "remaining_at_halt": 0,
        "autopilot_run_id": "run-old",
        "autopilot_phase_slug": "execute",
        "suggested_next_command": "...",
        "suggested_next_command_requires_human": False,
        "acknowledged_at": None,
    }
    state = _make_state(last_halt=prior, last_halt_history=[])
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    # Prior last_halt should move to history.
    assert len(new_state["last_halt_history"]) == 1
    rotated = new_state["last_halt_history"][0]
    # P2-4 fix: unack'd prior halt gets acknowledged_at stamped on rotation
    # (implicit ack: the new budget-halt supersedes it, consistent with §1.1 line 67).
    assert rotated.get("acknowledged_at") is not None, (
        "apply_budget_halt must stamp acknowledged_at on unack'd prior last_halt "
        "when rotating to history (P2-4 fix, §1.1 line 67 implicit ack semantics)."
    )
    # All other fields should be preserved.
    for key in ("at", "reason", "capability", "remaining_at_halt", "autopilot_run_id"):
        assert rotated[key] == prior[key]


def test_apply_budget_halt_cap_5_rotation():
    # Pre-fill history with 4 entries + 1 prior last_halt → after cap, only 5 remain
    old_diaries = [
        {"at": _iso_offset(600 - i * 60), "reason": f"old-{i}"} for i in range(4)
    ]
    prior_last_halt = {"at": _iso_offset(60), "reason": "prior"}
    state = _make_state(last_halt=prior_last_halt, last_halt_history=old_diaries)
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    # prior_last_halt was appended to old 4 = 5, capped at 5
    assert len(new_state["last_halt_history"]) == 5


def test_apply_budget_halt_cap_5_with_overflow():
    # Pre-fill history with 5 entries already + prior last_halt → oldest is dropped
    old_diaries = [
        {"at": _iso_offset(700 - i * 100), "reason": f"old-{i}"} for i in range(5)
    ]
    prior_last_halt = {"at": _iso_offset(10), "reason": "prior"}
    state = _make_state(last_halt=prior_last_halt, last_halt_history=old_diaries)
    diary = _make_diary()
    new_state = apply_budget_halt(state, diary=diary)
    assert len(new_state["last_halt_history"]) == 5
    # newest entry should be the prior_last_halt (with acknowledged_at stamped — P2-4 fix)
    last = new_state["last_halt_history"][-1]
    assert last["at"] == prior_last_halt["at"]
    assert last["reason"] == prior_last_halt["reason"]
    # acknowledged_at stamped on rotation (implicit ack — §1.1 line 67)
    assert last.get("acknowledged_at") is not None


def test_apply_budget_halt_does_not_mutate_original_state():
    state = _make_state()
    original = copy.deepcopy(state)
    diary = _make_diary()
    _ = apply_budget_halt(state, diary=diary)
    assert state == original
