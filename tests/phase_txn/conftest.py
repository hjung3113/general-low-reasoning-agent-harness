"""Make scripts/ importable for the phase_txn suite + scratch fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    """`.scratch/` directory with no pre-existing artefacts."""
    d = tmp_path / ".scratch"
    d.mkdir()
    return d


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    """Canonical `.harness/audit.log` location for the test repo."""
    (tmp_path / ".harness").mkdir()
    return tmp_path / ".harness" / "audit.log"


@pytest.fixture
def lock(scratch: Path):
    """Acquire the primary lock for the test and release on teardown.

    Tests that simulate crash conditions (no real lock holder) use
    `scratch` directly without this fixture.
    """
    from lib import phase_lock

    handle = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    yield handle
    phase_lock.release_primary(handle)
