"""Deterministic fixture scratch-dir preparation (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §6.1 task 6.

`prepare_scratch_dir(fixture, dest)` writes `.scratch/phase-state.json` from
the fixture's `initial_state` and creates an empty `.harness/` directory. It
is fully deterministic: no clock reads, no PID stamping, JSON serialized
with sort_keys=True so two invocations produce byte-identical trees.
"""
from __future__ import annotations

import json
from pathlib import Path


def prepare_scratch_dir(fixture: dict, dest: Path) -> Path:
    """Write fixture's initial_state to `dest/.scratch/phase-state.json` and
    create an empty `.harness/` peer. Returns `dest`.

    The output is byte-identical across invocations with the same fixture
    (sort_keys=True, indent=2, no clock-derived fields).
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".harness").mkdir(exist_ok=True)
    scratch = dest / ".scratch"
    scratch.mkdir(exist_ok=True)
    state_path = scratch / "phase-state.json"
    payload = json.dumps(fixture["initial_state"], sort_keys=True, indent=2) + "\n"
    state_path.write_text(payload, encoding="utf-8")
    return dest


def load_fixture(path: Path) -> dict:
    """Load and validate a fixture JSON file.

    Required keys: fixture_id, flow, initial_state, prompt_template,
    expected_target_phase, diagnostic_keywords, allowed_verbs.
    """
    text = Path(path).read_text(encoding="utf-8")
    fixture = json.loads(text)
    required = {
        "fixture_id",
        "flow",
        "initial_state",
        "prompt_template",
        "expected_target_phase",
        "diagnostic_keywords",
        "allowed_verbs",
    }
    missing = required - set(fixture.keys())
    if missing:
        raise ValueError(f"fixture {path} missing required keys: {sorted(missing)}")
    return fixture


def load_all_fixtures(fixtures_dir: Path) -> list[dict]:
    """Load every fixture-*.json from `fixtures_dir`, sorted by fixture_id."""
    fixtures = []
    for path in sorted(Path(fixtures_dir).glob("fixture-*.json")):
        fixtures.append(load_fixture(path))
    return fixtures
