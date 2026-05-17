"""P1-4: validate that release.yml shell: values are in the GH Actions recognized set
OR match the '<name> {0}' custom-shell template form.

GitHub Actions recognized shell names (from docs):
  bash, pwsh, python, sh, cmd, powershell

Custom shell form: '<executable> {0}'  (must contain '{0}')

Spec: §7.1 (matrix shells).
Slice: S14 review-fix.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

# GitHub Actions built-in recognized shell names (lowercase)
_GH_RECOGNIZED_SHELLS = frozenset(["bash", "pwsh", "python", "sh", "cmd", "powershell"])

# Custom-shell template form: must contain {0}
_CUSTOM_SHELL_RE = re.compile(r"\{0\}")


def _load_workflow_matrix_shells() -> list[str]:
    """Parse `shell:` values from the release.yml matrix include rows only.

    Uses PyYAML if available, otherwise falls back to regex parsing of the
    matrix include block.  Does NOT include step-level `shell: ${{ matrix.shell }}`
    references.
    """
    try:
        import yaml  # type: ignore[import]
        workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
        matrix_include = (
            workflow
            .get("jobs", {})
            .get("release-smoke", {})
            .get("strategy", {})
            .get("matrix", {})
            .get("include", [])
        )
        return [row["shell"] for row in matrix_include if "shell" in row]
    except ImportError:
        # yaml not available — parse with simple regex of the matrix include block
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        shells = []
        # Find matrix include rows: lines like "- { os: ..., shell: ..., ... }"
        for line in text.splitlines():
            stripped = line.strip()
            # Only process lines that look like matrix row definitions (contain 'os:')
            if stripped.startswith("- {") and "os:" in stripped:
                # Try single-quoted value first: shell: 'value'
                m = re.search(r"shell:\s*'([^']*)'", stripped)
                if m:
                    shells.append(m.group(1).strip())
                    continue
                # Then double-quoted: shell: "value"
                m = re.search(r'shell:\s*"([^"]*)"', stripped)
                if m:
                    shells.append(m.group(1).strip())
                    continue
                # Unquoted: shell: value (stop at comma or })
                m = re.search(r"shell:\s+([^,}\s'\"]+)", stripped)
                if m:
                    shells.append(m.group(1).strip())
        return shells


class TestReleaseYmlShellValidity:
    def test_workflow_exists(self) -> None:
        assert WORKFLOW_PATH.exists(), f"release.yml not found at {WORKFLOW_PATH}"

    def test_all_shell_values_valid(self) -> None:
        """Every shell: value in release.yml must be GH-Actions-recognized or custom-shell form."""
        shells = _load_workflow_matrix_shells()
        assert shells, "No shell: values found in release.yml matrix rows"

        invalid = []
        for shell in shells:
            lower = shell.lower()
            if lower in _GH_RECOGNIZED_SHELLS:
                continue  # built-in
            if _CUSTOM_SHELL_RE.search(shell):
                continue  # custom-shell template form (e.g. 'zsh -e {0}')
            invalid.append(shell)

        assert not invalid, (
            f"Invalid shell value(s) in release.yml: {invalid}\n"
            "GitHub Actions only recognizes: bash, pwsh, python, sh, cmd, powershell.\n"
            "For other shells use the template form: '<executable> {0}' (e.g. 'zsh -e {0}')."
        )

    def test_no_git_bash_shell(self) -> None:
        """'Git Bash' is not a valid GH Actions shell — must be replaced with bash."""
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "Git Bash" not in text, (
            "Found 'Git Bash' as a shell value in release.yml. "
            "Replace with 'bash' — Git Bash on Windows runners IS the bash shell."
        )

    def test_no_bare_zsh_shell(self) -> None:
        """Bare 'shell: zsh' is invalid — must use 'zsh -e {0}' template form."""
        shells = _load_workflow_matrix_shells()
        bare_zsh = [s for s in shells if s.strip().lower() == "zsh"]
        assert not bare_zsh, (
            "Found bare 'shell: zsh' in release.yml matrix rows. "
            "Replace with 'shell: zsh -e {0}' (custom-shell template form)."
        )
