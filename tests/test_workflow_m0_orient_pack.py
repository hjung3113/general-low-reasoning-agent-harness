"""Tests for workflow-m0-orient skill-pack (issue #29).

Covers:
- harness init --packs workflow-m0-orient installs the SKILL.md
- workflow-m0-orient appears in KNOWN_PACKS
- unknown-pack rejection works for common misspellings
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWorkflowCodebaseReconPack:
    def test_known_packs_includes_workflow_codebase_recon(self) -> None:
        """workflow-m0-orient must be listed in KNOWN_PACKS."""
        from lib.manifest import KNOWN_PACKS
        assert "workflow-m0-orient" in KNOWN_PACKS

    def test_init_with_pack_installs_skill_md(self) -> None:
        """harness init --packs workflow-m0-orient must install the SKILL.md."""
        import harness

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            harness.run(
                [
                    "init",
                    "--target", str(target),
                    "--adapters", "none",
                    "--packs", "workflow-m0-orient",
                ]
            )
            skill_path = target / ".agents/skills/workflow-m0-orient/SKILL.md"
            assert skill_path.exists(), "SKILL.md must be installed by pack"
            content = skill_path.read_text(encoding="utf-8")
            assert "workflow-m0-orient" in content
            assert ".planning/codebase-recon.md" in content

    def test_init_rejects_misspelled_pack_names(self) -> None:
        """Misspelled pack names must be rejected with a clear error."""
        import harness

        misspellings = [
            "workflow-codbase-recon",        # missing 'e'
            "workflow-m0-orient-typo",  # extra suffix
            "codebase-recon",                # missing workflow- prefix
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            for bad_pack in misspellings:
                with pytest.raises(SystemExit) as exc_info:
                    harness.run(["init", "--target", str(target), "--packs", bad_pack])
                assert bad_pack in str(exc_info.value), (
                    f"Error message must mention the bad pack name: {bad_pack}"
                )
