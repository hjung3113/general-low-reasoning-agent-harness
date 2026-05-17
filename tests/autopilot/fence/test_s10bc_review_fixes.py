"""S10b+S10c review-fix tests — P2-3 fs_fence execution_mode missing fail-closed.

Covers:
  P2-3: check_write_path fails closed when execution_mode is absent from state
        (corrupt/fresh state must not allow all writes by defaulting to manual)

Design refs: §5.1 fail-closed requirement
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.fs_fence import FenceCheckResult, check_write_path


# ---------------------------------------------------------------------------
# P2-3: execution_mode missing → fail-closed
# ---------------------------------------------------------------------------


def test_check_write_path_fails_closed_when_execution_mode_missing(tmp_path: Path) -> None:
    """P2-3: state without execution_mode key must fail-closed (deny), NOT default to manual.

    Before the fix, state.get("execution_mode", "manual") defaulted a missing
    field to "manual", which allowed all writes from corrupt/fresh state.
    The fix returns FenceCheckResult(allowed=False, reason="execution_mode_missing_fail_closed").
    """
    anchor = tmp_path / "anchor"
    anchor.mkdir()

    # State with NO execution_mode key at all.
    state_no_exec_mode: dict = {
        "allowed_paths": ["scripts/"],
        "autopilot_run_id": "abc",
    }

    result = check_write_path("scripts/foo.py", anchor=anchor, state=state_no_exec_mode)
    assert isinstance(result, FenceCheckResult)
    assert result.allowed is False, (
        "P2-3 REGRESSION: check_write_path returned allowed=True for state without "
        "execution_mode. This defaults missing field to manual, allowing writes from "
        "corrupt/fresh state (§5.1 fail-closed requirement)."
    )
    assert result.reason == "execution_mode_missing_fail_closed", (
        f"Expected reason='execution_mode_missing_fail_closed', got {result.reason!r}"
    )


def test_check_write_path_fails_closed_when_execution_mode_is_none(tmp_path: Path) -> None:
    """P2-3: state with execution_mode=None must fail-closed."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()

    state_none_exec_mode: dict = {
        "execution_mode": None,
        "allowed_paths": ["scripts/"],
    }

    result = check_write_path("scripts/foo.py", anchor=anchor, state=state_none_exec_mode)
    assert result.allowed is False
    assert result.reason == "execution_mode_missing_fail_closed"


def test_check_write_path_empty_state_fails_closed(tmp_path: Path) -> None:
    """P2-3: completely empty state fails closed (no execution_mode key)."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()

    result = check_write_path("scripts/foo.py", anchor=anchor, state={})
    assert result.allowed is False
    assert result.reason == "execution_mode_missing_fail_closed"


def test_check_write_path_manual_mode_still_allowed_after_fix(tmp_path: Path) -> None:
    """P2-3 regression guard: explicit execution_mode='manual' still allows writes."""
    anchor = tmp_path / "anchor"
    anchor.mkdir()

    state_manual: dict = {
        "execution_mode": "manual",
        "allowed_paths": [],
    }

    result = check_write_path("scripts/foo.py", anchor=anchor, state=state_manual)
    assert result.allowed is True
    assert result.reason == "fence_disabled_manual_mode"


def test_check_write_path_autopilot_mode_with_allowed_paths_still_works(tmp_path: Path) -> None:
    """P2-3 regression guard: explicit execution_mode autopilot + allowed_paths still works."""
    anchor = tmp_path / "anchor"
    (anchor / "scripts").mkdir(parents=True)

    state_autopilot: dict = {
        "execution_mode": "phase_autopilot",
        "allowed_paths": ["scripts/"],
    }

    result = check_write_path("scripts/foo.py", anchor=anchor, state=state_autopilot)
    assert result.allowed is True
    assert result.reason == "allowed"
