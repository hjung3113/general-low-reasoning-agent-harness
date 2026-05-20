"""T8a — harness check import-smoke tests (BUG-2).

Verifies that ``harness check`` (via check_installed_target) detects missing
lib modules early and exits non-zero with the module name in the error text.

Done-criteria
-------------
(a) clean installed target  → check rc=0  (no import errors)
(b) remove a manifest-listed lib module from target → check rc!=0 + error text
    contains the missing module's name
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

# Ensure scripts/ is on sys.path for module resolution.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import harness  # noqa: E402
import lib.check as _check_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal installed-target fixture
# ---------------------------------------------------------------------------

_AGENTS_BLOCK = (
    "# AGENTS\n\n"
    "# >>> low-reasoning-harness:AGENTS.md v0.0.0-dev+unknown\n"
    "Karpathy-Inspired Coding Guidelines\n\n"
    "If `.scratch/phase-state.json` is not `phase=execute` with `approved=true`\n\n"
    "Every roadmap phase starts with its own `discuss` pass\n"
    "# <<< low-reasoning-harness:AGENTS.md\n"
)

_PHASE_STATE = {
    "state_schema_version": 2,
    "phase": "discuss",
    "approved": False,
    "current_checkpoint": "CP-01-01",
    "checkpoint_path": ".planning/phases/01-init/01-CHECKPOINTS.md",
    "state_path": ".planning/STATE.md",
    "automation_mode": "manual",
    "auto_selected": [],
    "updated_at": "2026-05-20T00:00:00.000000000Z",
    "updated_by": "test",
}


def _make_installed_target(root: Path) -> Path:
    """Create a minimal installed-target directory that passes check cleanly.

    Structure mirrors a real harness install:
      <root>/
        scripts/
          harness.py          (minimal, imports lib.state)
          lib/
            __init__.py
            state.py          (stub)
        .harness/
          installed-manifest.json
        AGENTS.md
        .scratch/
          phase-state.json
    """
    scripts = root / "scripts"
    lib_dir = scripts / "lib"
    lib_dir.mkdir(parents=True)

    # Minimal harness.py with a from-lib import
    (scripts / "harness.py").write_text(
        "from lib.state import INSTALL_STATE\n",
        encoding="utf-8",
    )

    # lib/__init__.py
    (lib_dir / "__init__.py").write_text("", encoding="utf-8")

    # lib/state.py — stub with the imported symbol
    (lib_dir / "state.py").write_text(
        "INSTALL_STATE = '.harness/installed-manifest.json'\n",
        encoding="utf-8",
    )

    # .harness/installed-manifest.json
    harness_dir = root / ".harness"
    harness_dir.mkdir()
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps({
            "schema_version": 2,
            "version": "0.0.0-dev+unknown",
            "adapters": [],
            "profiles": [],
            "packs": [],
            "files": {},
        }),
        encoding="utf-8",
    )

    # AGENTS.md with required guardrail phrases
    (root / "AGENTS.md").write_text(_AGENTS_BLOCK, encoding="utf-8")

    # .scratch/phase-state.json
    scratch = root / ".scratch"
    scratch.mkdir()
    (scratch / "phase-state.json").write_text(
        json.dumps(_PHASE_STATE),
        encoding="utf-8",
    )

    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_check_clean_install_rc0(tmp_path):
    """(a) clean installed target → check passes (rc=0, no SystemExit)."""
    root = _make_installed_target(tmp_path)
    # Must not raise SystemExit
    _check_mod.check_installed_target(root)


def test_check_detects_missing_module(tmp_path):
    """(b) remove a module referenced by harness.py → check raises SystemExit
    and the error message names the missing module (``state``).
    """
    root = _make_installed_target(tmp_path)
    # Remove lib/state.py to simulate a manifest-gap / broken install
    (root / "scripts" / "lib" / "state.py").unlink()

    with pytest.raises(SystemExit) as exc_info:
        _check_mod.check_installed_target(root)

    exit_code = exc_info.value.code
    assert exit_code != 0, f"Expected nonzero exit, got {exit_code!r}"
    assert "state" in str(exit_code).lower(), (
        f"Expected 'state' in SystemExit message, got: {exit_code!r}"
    )


def test_import_smoke_performance(tmp_path):
    """Import-smoke phase completes in <100 ms even for a modestly-sized lib.

    Builds a target with 5 lib stubs and asserts the smoke itself is fast.
    """
    root = _make_installed_target(tmp_path)
    lib_dir = root / "scripts" / "lib"
    # Add a few extra stubs to approach real-world size
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        (lib_dir / f"{name}.py").write_text(f"# stub {name}\n", encoding="utf-8")
    # Add imports for those stubs in harness.py
    (root / "scripts" / "harness.py").write_text(
        "from lib.state import INSTALL_STATE\n"
        "from lib.alpha import *  # noqa\n"
        "from lib.beta import *  # noqa\n"
        "from lib.gamma import *  # noqa\n"
        "from lib.delta import *  # noqa\n"
        "from lib.epsilon import *  # noqa\n",
        encoding="utf-8",
    )

    start = time.monotonic()
    _check_mod.run_import_smoke(root / "scripts")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 100, f"import-smoke took {elapsed_ms:.1f}ms (>100ms budget)"
