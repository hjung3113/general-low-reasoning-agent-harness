"""Test seed policy: write once on install, never overwrite on upgrade.

Seed policy requirements:
1. File is written to target on init if it doesn't exist
2. File modifications in target are preserved on upgrade (never overwritten)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo-root / scripts path
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

HARNESS_PY = str(SCRIPTS_DIR / "harness.py")
_PYTHON = sys.executable

_DEV_ENV = {
    **os.environ,
}


def _run(*args: str, cwd: str | None = None, env: dict | None = None):
    """Run harness.py with given args; return (rc, stdout, stderr)."""
    cmd = [_PYTHON, HARNESS_PY, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(REPO_ROOT),
        env=env or _DEV_ENV,
    )
    return result.returncode, result.stdout, result.stderr


# ===========================================================================
# Test: seed file exists after init with pack
# ===========================================================================

class TestSeedPolicyInit:
    """Seed files should be created on init if pack is selected."""

    def test_codebase_recon_created_after_init_with_pack(self, tmp_path: Path) -> None:
        """Test that .planning/codebase-recon.md is created when workflow-m0-orient pack is selected."""
        # Step 1: initialise a fresh git repo in tmp_path
        subprocess.run(
            ["git", "init", "-q"],
            cwd=str(tmp_path),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init-for-test", "-q"],
            cwd=str(tmp_path),
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )

        # Step 2: init with workflow-m0-orient pack
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--adapters", "none",
            "--packs", "workflow-m0-orient",
        )
        assert rc_init == 0, (
            f"init with workflow-m0-orient pack must exit 0.\n"
            f"stdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 3: verify the file exists and has the expected template content
        recon_file = tmp_path / ".planning" / "codebase-recon.md"
        assert recon_file.exists(), (
            f"Expected .planning/codebase-recon.md to exist after init with "
            f"workflow-m0-orient pack"
        )

        content = recon_file.read_text(encoding="utf-8")
        assert "# Codebase Recon" in content, (
            f"Expected template content with '# Codebase Recon' heading"
        )
        assert "## 1. One-liner — what is this project?" in content, (
            f"Expected template section 1"
        )
        assert "## 2. Tech stack" in content, (
            f"Expected template section 2"
        )
        assert "## 3. Top-level structure (depth 2)" in content, (
            f"Expected template section 3"
        )
        assert "## 4. Existing docs found" in content, (
            f"Expected template section 4"
        )
        assert "## 5. Open questions" in content, (
            f"Expected template section 5"
        )


# ===========================================================================
# Test: seed file modifications are preserved on upgrade
# ===========================================================================

class TestSeedPolicyUpgrade:
    """Seed files should NOT be overwritten on upgrade."""

    def test_seed_file_modifications_preserved_on_upgrade(self, tmp_path: Path) -> None:
        """Test that modifications to seed files are preserved on upgrade."""
        # Step 1: initialise a fresh git repo
        subprocess.run(
            ["git", "init", "-q"],
            cwd=str(tmp_path),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init-for-test", "-q"],
            cwd=str(tmp_path),
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )

        # Step 2: init with workflow-m0-orient pack
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--adapters", "none",
            "--packs", "workflow-m0-orient",
        )
        assert rc_init == 0, (
            f"init must exit 0.\nstdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 3: modify the seed file
        recon_file = tmp_path / ".planning" / "codebase-recon.md"
        original_content = recon_file.read_text(encoding="utf-8")

        modified_content = original_content.replace(
            "## 1. One-liner — what is this project?",
            "## 1. One-liner — what is this project?\nMy awesome project"
        )
        recon_file.write_text(modified_content, encoding="utf-8")

        # Step 4: run upgrade (which should preserve the modification)
        rc_upgrade, stdout_upgrade, stderr_upgrade = _run(
            "upgrade",
            "--target", str(tmp_path),
            "--force",
        )
        assert rc_upgrade == 0, (
            f"upgrade must exit 0.\nstdout={stdout_upgrade}\nstderr={stderr_upgrade}"
        )

        # Step 5: verify the modification is preserved
        after_upgrade = recon_file.read_text(encoding="utf-8")
        assert "My awesome project" in after_upgrade, (
            f"Expected user modifications to seed file to be preserved after upgrade.\n"
            f"Before: {modified_content}\n"
            f"After: {after_upgrade}"
        )
        # Also verify that the file wasn't reset to the original template
        assert after_upgrade == modified_content, (
            f"Seed file content changed unexpectedly after upgrade.\n"
            f"Expected: {modified_content}\n"
            f"Got: {after_upgrade}"
        )


# ===========================================================================
# Test: seed file not created when pack not selected
# ===========================================================================

class TestSeedPolicyNoPack:
    """Seed files should NOT be created if the pack is not selected."""

    def test_codebase_recon_not_created_without_pack(self, tmp_path: Path) -> None:
        """Test that .planning/codebase-recon.md is NOT created without workflow-m0-orient pack."""
        # Step 1: initialise a fresh git repo
        subprocess.run(
            ["git", "init", "-q"],
            cwd=str(tmp_path),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "init-for-test", "-q"],
            cwd=str(tmp_path),
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"},
        )

        # Step 2: init WITHOUT workflow-m0-orient pack
        rc_init, stdout_init, stderr_init = _run(
            "init",
            "--target", str(tmp_path),
            "--adapters", "none",
        )
        assert rc_init == 0, (
            f"init must exit 0.\nstdout={stdout_init}\nstderr={stderr_init}"
        )

        # Step 3: verify the file does NOT exist
        recon_file = tmp_path / ".planning" / "codebase-recon.md"
        assert not recon_file.exists(), (
            f"Expected .planning/codebase-recon.md to NOT exist when pack is not selected"
        )
