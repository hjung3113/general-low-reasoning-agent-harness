"""Test fixtures for the phase_approve verb suite (S02).

Ensures scripts/ is importable for `from lib.phase_approve import ...`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import phase_lock, phase_txn  # noqa: E402 — path must be set first


def seed_scratch(scratch: Path, audit_path: Path) -> None:
    """Bootstrap a minimal phase_state so state_trust preflight passes.

    Shared helper used by test_speed_bump_prompt.py and can be used by
    test_approve_provenance.py when deduplication is desired.
    """
    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={
                "verb": "phase.set",
                "by": "seed",
                "args": {"phase": "plan"},
            },
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)
