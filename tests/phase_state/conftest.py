"""Test fixtures for the phase_state schema suite (S01-A).

Ensures scripts/ is importable for `from lib.phase_state import ...` style
imports used by the rest of the harness modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
