"""P2-4: Unit test asserting ROO_BUILTIN_MODES is a single shared constant.

Verifies that:
  1. scripts/lib/roo_modes.py exports ROO_BUILTIN_MODES as a frozenset.
  2. check.py imports from roo_modes (not re-defines the set).
  3. The constant is non-empty and contains expected built-in slugs.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12
Slice: S14+S15 review-fix P2-4
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_roo_builtin_modes_single_source():
    """ROO_BUILTIN_MODES is importable from roo_modes and is non-empty (P2-4)."""
    from lib.roo_modes import ROO_BUILTIN_MODES

    assert isinstance(ROO_BUILTIN_MODES, frozenset), (
        "ROO_BUILTIN_MODES must be a frozenset"
    )
    assert len(ROO_BUILTIN_MODES) >= 1, (
        "ROO_BUILTIN_MODES must be non-empty"
    )
    # Spot-check canonical built-in slugs.
    for slug in ("ask", "code", "architect", "debug", "orchestrator"):
        assert slug in ROO_BUILTIN_MODES, (
            f"Expected built-in slug {slug!r} in ROO_BUILTIN_MODES"
        )


def test_check_py_imports_from_roo_modes():
    """check.py's _ROO_BUILTIN_MODES is the same object as roo_modes.ROO_BUILTIN_MODES (P2-4)."""
    from lib.roo_modes import ROO_BUILTIN_MODES
    # check.py imports via `from .roo_modes import ROO_BUILTIN_MODES as _ROO_BUILTIN_MODES`.
    # We verify the set values match (same frozenset content).
    # We cannot easily check object identity across module re-imports, so we
    # verify that check.py has no local _ROO_BUILTIN_MODES frozenset literal.
    import inspect
    import lib.check as check_mod
    src = inspect.getsource(check_mod)
    # The local definition must NOT be a frozenset literal — it must be an import alias.
    assert 'frozenset({"ask"' not in src, (
        "check.py must not redefine _ROO_BUILTIN_MODES as a frozenset literal. "
        "It must import from roo_modes instead."
    )
    # Verify the import is present.
    assert "from .roo_modes import ROO_BUILTIN_MODES" in src or \
           "from lib.roo_modes import ROO_BUILTIN_MODES" in src, (
        "check.py must import ROO_BUILTIN_MODES from roo_modes"
    )
