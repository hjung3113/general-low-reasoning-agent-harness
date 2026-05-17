"""Make scripts/ importable + provide scratch fixture for phase_lock suite."""

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
    """Empty `.scratch/` directory for one test."""
    d = tmp_path / ".scratch"
    d.mkdir()
    return d
