"""Tests for .opencode/commands/fsd-run-phase.md file presence and body shape (§4.3b)."""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".opencode" / "commands" / "fsd-run-phase.md"
OLD_COMMAND_FILE = REPO_ROOT / ".opencode" / "commands" / "fsd-phase.md"


class TestOpencodesFsdRunPhaseFileExists:
    def test_new_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .opencode/commands/fsd-run-phase.md per §4.3b net-new."
        )

    def test_old_command_file_removed(self):
        assert not OLD_COMMAND_FILE.exists(), (
            f"{OLD_COMMAND_FILE} still exists. "
            "Expected it to be deleted per §4.1 rename (fsd-phase → fsd-run-phase)."
        )


class TestOpencodesFsdRunPhaseBodyShape:
    """Validate the §4.3b verbatim body is present (no frontmatter expected)."""

    @pytest.fixture(scope="class")
    def content(self):
        return COMMAND_FILE.read_text(encoding="utf-8")

    def test_no_frontmatter(self, content):
        """OpenCode commands do not use YAML frontmatter (§4.3b)."""
        assert not content.startswith("---"), (
            "OpenCode command files must NOT start with YAML frontmatter '---' "
            "(OpenCode does not support it per §4.3b)."
        )

    def test_starts_with_header(self, content):
        assert content.startswith("# fsd-run-phase"), (
            "File must start with '# fsd-run-phase' header per §4.3b."
        )

    def test_harness_command_present(self, content):
        assert "harness fsd-run-phase" in content, (
            "Body must contain 'harness fsd-run-phase' literal."
        )

    def test_no_allow_network(self, content):
        assert "Do not pass `--allow-network`" in content, (
            "Body must include 'Do not pass `--allow-network`' instruction."
        )

    def test_positional_args_unsupported_note(self, content):
        assert "positional" in content.lower() or "NO positional argument" in content, (
            "Body must note that OpenCode positional substitution is unsupported."
        )

    def test_phase_lifecycle_steps(self, content):
        assert "harness status" in content
        assert "harness phase set done" in content
        assert "harness status --json" in content

    def test_no_old_slash_command_reference(self, content):
        import re
        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if re.search(r"/fsd-phase(?![-\w])", line):
                pytest.fail(
                    f"Line {lineno} contains old '/fsd-phase' reference: {line!r}"
                )
