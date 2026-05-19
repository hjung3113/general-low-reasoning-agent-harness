"""Test fixtures for the phase_approve verb suite (S02).

Ensures scripts/ is importable for `from lib.phase_approve import ...`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import phase_txn  # noqa: E402 — path must be set first


def seed_scratch(scratch: Path, audit_path: Path) -> None:  # noqa: ARG001
    """Bootstrap a minimal phase_state for speed-bump tests.

    Writes the canonical phase-state JSON directly to scratch/ WITHOUT
    writing an audit entry.  This is intentional: the new speed-bump
    tests use skip_anchor_preflight=True which also skips state_trust
    preflight (see phase_approve.run_approve).  The audit_path parameter
    is accepted for API compatibility but is NOT written to, so that
    tests asserting ``audit_path.read_text() == ""`` after a cancelled
    approve remain valid.

    Tests that require a fully wired audit chain (e.g. test_approve_provenance)
    seed their own state+audit via commit_transaction directly.
    """
    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    state_path = scratch / phase_txn.STATE_NAME
    canonical = phase_txn._canonical_bytes(seed_state)
    state_path.write_bytes(canonical)
