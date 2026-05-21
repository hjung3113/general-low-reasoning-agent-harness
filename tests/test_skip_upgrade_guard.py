"""T6 — Skip-upgrade guard with bilingual error + missing-version safety.

Test cases:
1. v0.9.4 → v0.9.7 no env → UpgradeRefused; message has Korean + English + override hint
2. v0.9.4 → v0.9.7 with HARNESS_ALLOW_SKIP_UPGRADE=1 → proceeds (no exception)
3. v0.9.5 → v0.9.7 → no guard
4. v0.9.6 → v0.9.7 → no guard
5. Missing/empty version → UpgradeRefused (defensive)
"""
from __future__ import annotations

import os
import sys

import pytest

_SCRIPTS_DIR = (
    __import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.upgrade import UpgradeRefused, _check_skip_upgrade_guard  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: v0.9.4 → v0.9.7 → UpgradeRefused with bilingual message
# ---------------------------------------------------------------------------


def test_v094_to_v097_raises_upgrade_refused():
    """T6-1: v0.9.4 → v0.9.7 blocked; message includes Korean + English + override hint."""
    prior_state = {"version": "0.9.4"}

    with pytest.raises(UpgradeRefused) as exc_info:
        _check_skip_upgrade_guard(prior_state, "0.9.7")

    msg = str(exc_info.value)
    # Korean text present
    assert "v0.9.4" in msg
    assert "v0.9.7" in msg or "0.9.7" in msg
    # English text present (bracketed)
    assert "[" in msg and "]" in msg
    # Override hint
    assert "HARNESS_ALLOW_SKIP_UPGRADE" in msg
    # Must contain v0.9.5 (the required intermediate)
    assert "0.9.5" in msg


# ---------------------------------------------------------------------------
# Test 2: v0.9.4 → v0.9.7 with HARNESS_ALLOW_SKIP_UPGRADE=1 → no exception
# ---------------------------------------------------------------------------


def test_v094_to_v097_with_override_env(monkeypatch):
    """T6-2: HARNESS_ALLOW_SKIP_UPGRADE=1 allows the skip."""
    monkeypatch.setenv("HARNESS_ALLOW_SKIP_UPGRADE", "1")
    prior_state = {"version": "0.9.4"}

    # Should NOT raise
    _check_skip_upgrade_guard(prior_state, "0.9.7")


# ---------------------------------------------------------------------------
# Test 3: v0.9.5 → v0.9.7 → no guard
# ---------------------------------------------------------------------------


def test_v095_to_v097_no_guard():
    """T6-3: v0.9.5 → v0.9.7 is allowed (no guard triggered)."""
    prior_state = {"version": "0.9.5"}
    # Should not raise
    _check_skip_upgrade_guard(prior_state, "0.9.7")


# ---------------------------------------------------------------------------
# Test 4: v0.9.6 → v0.9.7 → no guard
# ---------------------------------------------------------------------------


def test_v096_to_v097_no_guard():
    """T6-4: v0.9.6 → v0.9.7 is allowed."""
    prior_state = {"version": "0.9.6"}
    _check_skip_upgrade_guard(prior_state, "0.9.7")


# ---------------------------------------------------------------------------
# Test 5: Missing/empty version → UpgradeRefused (defensive)
# ---------------------------------------------------------------------------


def test_missing_version_raises_upgrade_refused():
    """T6-5: prior state with missing version raises UpgradeRefused."""
    # Empty string version
    with pytest.raises(UpgradeRefused) as exc_info:
        _check_skip_upgrade_guard({"version": ""}, "0.9.7")
    assert "state show" in str(exc_info.value) or "상태 점검" in str(exc_info.value)

    # No version key
    with pytest.raises(UpgradeRefused):
        _check_skip_upgrade_guard({}, "0.9.7")

    # "unknown" version
    with pytest.raises(UpgradeRefused):
        _check_skip_upgrade_guard({"version": "unknown"}, "0.9.7")
