"""Test fixtures for the phase_reopen verb suite (S04).

Ensures scripts/ is importable for `from lib.phase_reopen import ...`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
