"""S01-A.1: default population for the new schema fields (design §1.1).

Pure-function tests for `apply_v2_defaults`. Filesystem writes are S01-A.2.
"""

from __future__ import annotations

import pytest

from lib.phase_state import (
    NEW_V2_FIELDS,
    apply_v2_defaults,
    coerce_legacy_execution_mode,
)


def test_apply_v2_defaults_populates_every_new_field():
    state = {"execution_mode": "manual", "phase": "discuss"}
    out = apply_v2_defaults(state)
    for key in NEW_V2_FIELDS:
        assert key in out, f"default not populated: {key}"


def test_apply_v2_defaults_does_not_overwrite_existing_values():
    state = {
        "plan_finalized_at": "2026-05-17T00:00:00Z",
        "execute_attempt_started_at": "2026-05-17T01:00:00Z",
    }
    out = apply_v2_defaults(state)
    assert out["plan_finalized_at"] == "2026-05-17T00:00:00Z"
    assert out["execute_attempt_started_at"] == "2026-05-17T01:00:00Z"


def test_default_timestamps_and_drafts_are_null():
    out = apply_v2_defaults({"execution_mode": "manual"})
    assert out["execute_attempt_started_at"] is None
    assert out["plan_finalized_at"] is None
    assert out["draft_verification"] is None
    assert out["draft_allowed_paths"] is None


def test_apply_v2_defaults_returns_new_dict():
    state = {"execution_mode": "manual"}
    out = apply_v2_defaults(state)
    assert out is not state


def test_apply_v2_defaults_is_idempotent():
    state = coerce_legacy_execution_mode({"automation_mode": "chain"})
    once = apply_v2_defaults(state)
    twice = apply_v2_defaults(once)
    assert twice == once
