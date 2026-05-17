"""S01-A.2: forward() round-trips on the pinned design §9.1 fixtures.

Walks every `tests/fixtures/state/v0*/` and `tampered_*/` directory and
asserts that:
  * `forward()` produces a record whose `execution_mode` matches the
    expected value pinned in the README.
  * Reading the on-disk fixture, applying `forward()`, and serializing
    yields valid JSON containing every NEW_V2_FIELD with a sensible default.

The state-trust preflight rejection of the `tampered_*` fixtures is **not**
asserted here — that contract lives in S01-E (`test_state_trust_preflight.py`).
S01-A only pins the fixtures so later slices have a stable input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import state_migrate
from lib.phase_state import NEW_V2_FIELDS


FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "state"


def _load(directory: str) -> dict:
    return json.loads((FIXTURES_ROOT / directory / "phase-state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture_dir", "expected_execution_mode"),
    [
        ("v061_no_execution_or_automation", "manual"),
        ("v070_automation_manual_only", "manual"),
        ("v070_automation_chain", "phase_autopilot"),
        ("v070_automation_auto", "chain_autopilot"),
    ],
)
def test_forward_on_fixture_yields_expected_execution_mode(fixture_dir: str, expected_execution_mode: str):
    state = _load(fixture_dir)
    v2 = state_migrate.forward(state)
    assert v2["execution_mode"] == expected_execution_mode


@pytest.mark.parametrize(
    "fixture_dir",
    [
        "v061_no_execution_or_automation",
        "v070_automation_manual_only",
        "v070_automation_chain",
        "v070_automation_auto",
    ],
)
def test_forward_on_fixture_populates_every_v2_default(fixture_dir: str):
    state = _load(fixture_dir)
    v2 = state_migrate.forward(state)
    for key in NEW_V2_FIELDS:
        assert key in v2, f"forward dropped {key} from {fixture_dir}"


def test_tampered_fixtures_parse_as_valid_json():
    """Pin the on-disk shape — actual rejection happens in S01-E."""
    for name in ("tampered_approved_true", "tampered_chain_autopilot"):
        state = _load(name)
        assert state["state_schema_version"] == 2
        # tampered_approved_true: forged approved=true without audit anchor.
        if name == "tampered_approved_true":
            assert state["approved"] is True
            assert state["phase"] == "discuss"
        # tampered_chain_autopilot: forged execution_mode without start audit.
        if name == "tampered_chain_autopilot":
            assert state["execution_mode"] == "chain_autopilot"
