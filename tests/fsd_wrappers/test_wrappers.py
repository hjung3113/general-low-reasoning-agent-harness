"""S07-prep step 4 — `harness fsd-run-phase` / `harness fsd-run-all` wrapper tests.

Design refs:
  - §3.5 (lines 632-660) — adapter-safe wrapper contract, slug regex,
      empty/single/multi-token rules, Roo vs OpenCode parity table.

Fault classes asserted:
  - multi_token_argument       exit 2   — whitespace in argument
  - slug_regex_mismatch        exit 2   — uppercase / leading-hyphen / too-long
  - all_phases_done            exit 0   — next-pending returned all_done
  - started                    exit 0   — happy path (forwarded from run_start)
  - windows_containment_degraded exit 11 — forwarded from run_start (run_fsd_run_all)

All tests use `skip_anchor_preflight` semantics via `anchor_verified=True` +
`repo_root=None` (same pattern as phase_autopilot tests).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib import fsd_wrappers, phase_autopilot
from tests.fsd_wrappers.conftest import (
    ci_env_github,
    common_kwargs,
    fake_oidc_fetcher,
    fake_oidc_verifier,
    mint_nonce,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_state(env: dict) -> dict:
    state_path = env["scratch"] / "phase-state.json"
    return json.loads(state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Argument validation — multi-token (exit 2)
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_multi_token_space(harness_env):
    """argument with space → exit 2 sub=multi_token_argument."""
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument="phase x", **kwargs)
    assert result.exit_code == 2
    assert result.sub_reason == "multi_token_argument"


def test_run_fsd_run_phase_multi_token_tab(harness_env):
    """argument with tab → exit 2 sub=multi_token_argument."""
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument="phase\ttoo", **kwargs)
    assert result.exit_code == 2
    assert result.sub_reason == "multi_token_argument"


# ---------------------------------------------------------------------------
# 2. Argument validation — slug_regex_mismatch (exit 2)
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_uppercase_slug(harness_env):
    """Uppercase slug → exit 2 sub=slug_regex_mismatch."""
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument="Phase-X", **kwargs)
    assert result.exit_code == 2
    assert result.sub_reason == "slug_regex_mismatch"


def test_run_fsd_run_phase_leading_hyphen(harness_env):
    """Leading hyphen → exit 2 sub=slug_regex_mismatch."""
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument="-foo", **kwargs)
    assert result.exit_code == 2
    assert result.sub_reason == "slug_regex_mismatch"


def test_run_fsd_run_phase_too_long(harness_env):
    """65-char slug → exit 2 sub=slug_regex_mismatch."""
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument="a" * 65, **kwargs)
    assert result.exit_code == 2
    assert result.sub_reason == "slug_regex_mismatch"


def test_run_fsd_run_phase_max_len_ok(harness_env):
    """64-char slug passes regex (1 + 63)."""
    # Regex: ^[a-z0-9][a-z0-9-]{0,63}$ → total max 64 chars.
    slug_64 = "a" + "b" * 63  # 64 chars
    result = fsd_wrappers._validate_argument(slug_64)
    assert result == (slug_64, None)


def test_run_fsd_run_phase_slug_with_numbers(harness_env):
    """Slug starting with digit passes regex."""
    result = fsd_wrappers._validate_argument("01-foo")
    assert result == ("01-foo", None)


# ---------------------------------------------------------------------------
# 3. Argument=None / "" → next-pending path
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_none_uses_next_pending_slug(harness_env):
    """argument=None → calls next-pending, uses returned slug, mode=phase."""
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument=None, **kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "started"
    # Confirm the autopilot phase slug is the next-pending result (phase-alpha).
    state = _read_state(harness_env)
    assert state["autopilot_phase_slug"] == "phase-alpha"
    assert state["autopilot_mode"] == "phase"


def test_run_fsd_run_phase_empty_string_uses_next_pending_slug(harness_env):
    """argument="" → same as None: calls next-pending, uses returned slug."""
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument="", **kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "started"
    state = _read_state(harness_env)
    assert state["autopilot_phase_slug"] == "phase-alpha"


# ---------------------------------------------------------------------------
# 4. Explicit slug — happy path (mode=phase)
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_explicit_slug_happy_path(harness_env):
    """argument='phase-alpha' → uses it directly, mode=phase, exit 0."""
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "started"
    state = _read_state(harness_env)
    assert state["autopilot_phase_slug"] == "phase-alpha"
    assert state["autopilot_mode"] == "phase"


def test_run_fsd_run_phase_slug_01_foo(harness_env):
    """argument='01-foo' (numeric-start slug) → validates and uses, mode=phase."""
    # Add '01-foo' to roadmap so slug validation passes.
    (harness_env["roadmap_root"] / "01-foo").mkdir()
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument="01-foo", **kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "started"
    state = _read_state(harness_env)
    assert state["autopilot_phase_slug"] == "01-foo"


# ---------------------------------------------------------------------------
# 5. Lock acquired and released (no leak)
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_lock_acquired_and_released(harness_env):
    """Wrapper acquires lock before run_start and releases it afterward."""
    from lib import phase_lock
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs)
    assert result.exit_code == 0
    # If lock were not released, this would timeout.
    lock = phase_lock.acquire_primary(harness_env["scratch"], timeout_s=1.0)
    phase_lock.release_primary(lock)


# ---------------------------------------------------------------------------
# 6. next-pending returns all-done → exit 0, run_start NOT called
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_all_phases_done(harness_env):
    """When all roadmap phases are done, exit 0 sub=all_phases_done; no start."""
    # Mark all phases as done.
    for slug in ("phase-alpha", "phase-beta"):
        phase_dir = harness_env["roadmap_root"] / slug
        (phase_dir / "phase-state.json").write_text(
            json.dumps({"phase": "done"}), encoding="utf-8"
        )
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_phase(argument=None, **kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "all_phases_done"
    assert result.autopilot_result is None
    # State must not have changed to autopilot.
    state = _read_state(harness_env)
    assert state["execution_mode"] == "manual"


# ---------------------------------------------------------------------------
# 7. run_fsd_run_all — happy path (mode=chain)
# ---------------------------------------------------------------------------


def test_run_fsd_run_all_happy_path_uses_next_pending_mode_chain(harness_env):
    """run_fsd_run_all: calls next-pending, then run_start with mode=chain."""
    kwargs = common_kwargs(harness_env)
    # run_fsd_run_all doesn't take 'argument'.
    kwargs_all = {k: v for k, v in kwargs.items()}
    result = fsd_wrappers.run_fsd_run_all(**kwargs_all)
    assert result.exit_code == 0
    assert result.sub_reason == "started"
    state = _read_state(harness_env)
    assert state["autopilot_phase_slug"] == "phase-alpha"
    assert state["autopilot_mode"] == "chain"


# ---------------------------------------------------------------------------
# 8. run_fsd_run_all — all-done → exit 0
# ---------------------------------------------------------------------------


def test_run_fsd_run_all_all_phases_done(harness_env):
    """run_fsd_run_all: all-done → exit 0 sub=all_phases_done; no run_start."""
    for slug in ("phase-alpha", "phase-beta"):
        phase_dir = harness_env["roadmap_root"] / slug
        (phase_dir / "phase-state.json").write_text(
            json.dumps({"phase": "done"}), encoding="utf-8"
        )
    kwargs = common_kwargs(harness_env, mint=False)
    result = fsd_wrappers.run_fsd_run_all(**kwargs)
    assert result.exit_code == 0
    assert result.sub_reason == "all_phases_done"
    assert result.autopilot_result is None


# ---------------------------------------------------------------------------
# 9. run_fsd_run_all — Windows degraded containment forwarded (exit 11)
# ---------------------------------------------------------------------------


def test_run_fsd_run_all_windows_degraded_forwarded(harness_env, monkeypatch):
    """run_fsd_run_all + Windows + chain → exit 11 windows_containment_degraded."""
    monkeypatch.setattr(sys, "platform", "win32")
    kwargs = common_kwargs(harness_env)
    # accept_degraded_windows_containment=False (default) + allow_network=False.
    result = fsd_wrappers.run_fsd_run_all(**kwargs)
    assert result.exit_code == 11
    assert result.sub_reason == "windows_containment_degraded"
    assert result.autopilot_result is not None


# ---------------------------------------------------------------------------
# 10. Error propagation — run_start errors forwarded with original exit_code
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_propagates_run_start_errors(harness_env):
    """Wrapper forwards run_start exit_code + sub_reason on error (e.g. already active)."""
    # Start once (success).
    kwargs = common_kwargs(harness_env)
    r1 = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs)
    assert r1.exit_code == 0

    # Second start → autopilot_already_active (exit 15).
    kwargs2 = common_kwargs(harness_env)
    r2 = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs2)
    assert r2.exit_code == 15
    assert r2.sub_reason == "autopilot_already_active"
    assert r2.autopilot_result is not None
    assert r2.autopilot_result.exit_code == 15


def test_run_fsd_run_all_propagates_run_start_errors(harness_env):
    """run_fsd_run_all forwards run_start error exit_code + sub_reason."""
    # Start once via run_phase.
    kwargs = common_kwargs(harness_env)
    r1 = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs)
    assert r1.exit_code == 0

    # run_fsd_run_all → autopilot_already_active (exit 15).
    kwargs2 = common_kwargs(harness_env)
    r2 = fsd_wrappers.run_fsd_run_all(**kwargs2)
    assert r2.exit_code == 15
    assert r2.sub_reason == "autopilot_already_active"


# ---------------------------------------------------------------------------
# 11. FsdWrapperResult carries autopilot_result on success
# ---------------------------------------------------------------------------


def test_run_fsd_run_phase_autopilot_result_populated_on_success(harness_env):
    """FsdWrapperResult.autopilot_result is an AutopilotResult on success."""
    kwargs = common_kwargs(harness_env)
    result = fsd_wrappers.run_fsd_run_phase(argument="phase-alpha", **kwargs)
    assert result.exit_code == 0
    assert isinstance(result.autopilot_result, phase_autopilot.AutopilotResult)
    assert result.autopilot_result.autopilot_run_id is not None


# ---------------------------------------------------------------------------
# 12. xfail-strict pin: live CLI routing (deferred — step 5)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CLI argparse wiring for `harness fsd-run-phase` / `harness fsd-run-all` "
        "not yet landed (deferred to step 5 per S07-prep scope). "
        "Flip to xpass when harness.py dispatches to fsd_wrappers."
    ),
)
def test_live_cli_routes_through_fsd_wrappers(harness_env):
    """Smoke: `harness fsd-run-phase` must route through fsd_wrappers.run_fsd_run_phase.

    This test is xfail-strict until CLI argparse wiring is added in step 5.
    The xfail pin prevents silent skipping — if the CLI is accidentally wired
    before this test is updated it will flip to xpass and alert the committer
    to remove the mark.
    """
    import os
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "scripts.harness", "fsd-run-phase"],
        capture_output=True,
        text=True,
        cwd=str(harness_env["tmp_path"]),
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "scripts"),
        },
    )
    # Expect exit 0 when CLI is wired. Until then this fails xfail=strict.
    assert result.returncode == 0, f"CLI not wired: {result.stderr[:300]}"
