"""Tests for .roo/commands/fsd-run-all.md file presence and body shape (§4.4a)."""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".roo" / "commands" / "fsd-run-all.md"
OLD_COMMAND_FILE = REPO_ROOT / ".roo" / "commands" / "fsd-chain-phase.md"


class TestRooFsdRunAllFileExists:
    def test_new_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .roo/commands/fsd-run-all.md per §4.4a rename."
        )

    def test_old_command_file_removed(self):
        assert not OLD_COMMAND_FILE.exists(), (
            f"{OLD_COMMAND_FILE} still exists. "
            "Expected it to be deleted per §4.1 rename (fsd-chain-phase → fsd-run-all)."
        )


class TestRooFsdRunAllBodyShape:
    """Validate the §4.4a verbatim body is present."""

    @pytest.fixture(scope="class")
    def content(self):
        return COMMAND_FILE.read_text(encoding="utf-8")

    def test_starts_with_frontmatter_delimiter(self, content):
        assert content.startswith("---"), (
            "File must start with YAML frontmatter delimiter '---'."
        )

    def test_description_line_present(self, content):
        assert "description:" in content, (
            "Frontmatter must contain 'description:' line."
        )

    def test_description_exact(self, content):
        expected = "description: Chain roadmap phases under chain_autopilot until next-pending is empty"
        assert expected in content, (
            f"Expected exact description line:\n  {expected!r}\nGot content:\n{content[:300]!r}"
        )

    def test_mode_orchestrator(self, content):
        assert "mode: orchestrator" in content

    def test_harness_command_present(self, content):
        assert "harness fsd-run-all" in content, (
            "Body must contain 'harness fsd-run-all' literal."
        )

    def test_no_allow_network(self, content):
        # §4.4a body does not include --allow-network; absence verifies it was not added
        assert "--allow-network" not in content, (
            "Body must NOT contain '--allow-network' (not applicable to fsd-run-all)."
        )

    def test_chain_driver_steps_present(self, content):
        assert "chain_autopilot" in content
        assert "harness phase set done" in content
        assert "harness phase next-pending" in content
        assert "harness phase autopilot stop" in content

    def test_no_recursive_invoke(self, content):
        assert "Do NOT recursively invoke `/fsd-run-all`" in content, (
            "Body must contain the anti-recursive-invoke guard."
        )

    def test_requires_human_check(self, content):
        assert "requires_human" in content, (
            "Body must reference 'requires_human' field from harness next --json."
        )

    def test_no_old_slash_command_reference(self, content):
        import re
        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            if re.search(r"/fsd-chain-phase(?![-\w])", line):
                pytest.fail(
                    f"Line {lineno} contains old '/fsd-chain-phase' reference: {line!r}"
                )
