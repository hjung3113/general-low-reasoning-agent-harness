"""Tests for .roo/commands/fsd-run-phase.md file presence and body shape (§4.3a)."""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".roo" / "commands" / "fsd-run-phase.md"
OLD_COMMAND_FILE = REPO_ROOT / ".roo" / "commands" / "fsd-phase.md"


class TestFsdRunPhaseFileExists:
    def test_new_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .roo/commands/fsd-run-phase.md per §4.3a rename."
        )

    def test_old_command_file_removed(self):
        assert not OLD_COMMAND_FILE.exists(), (
            f"{OLD_COMMAND_FILE} still exists. "
            "Expected it to be deleted per §4.1 rename (fsd-phase → fsd-run-phase)."
        )


class TestFsdRunPhaseBodyShape:
    """Validate the §4.3a verbatim body is present."""

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
        expected = "description: Run a single phase end-to-end via the canonical phase gate (autopilot, mode=phase)"
        assert expected in content, (
            f"Expected exact description line:\n  {expected!r}\nGot content:\n{content[:300]!r}"
        )

    def test_argument_hint_present(self, content):
        assert "argument-hint: [phase-slug]" in content

    def test_mode_orchestrator(self, content):
        assert "mode: orchestrator" in content

    def test_harness_command_present(self, content):
        assert "harness fsd-run-phase $ARGUMENTS" in content, (
            "Body must contain 'harness fsd-run-phase $ARGUMENTS' literal."
        )

    def test_no_allow_network(self, content):
        assert "Do not pass `--allow-network`" in content

    def test_references_fsd_run_all_for_chaining(self, content):
        assert "/fsd-run-all" in content, (
            "Body must reference /fsd-run-all for chaining (per §4.3a)."
        )

    def test_phase_lifecycle_steps(self, content):
        assert "harness status" in content
        assert "harness phase set done" in content
        assert "harness status --json" in content

    def test_no_old_slash_command_reference(self, content):
        # The file body must not reference the old /fsd-phase command name.
        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            # Allow the file itself to say /fsd-run-phase; forbid /fsd-phase
            # but not as part of /fsd-run-phase or /fsd-chain-phase.
            import re
            if re.search(r'/fsd-phase(?!-)', line):
                pytest.fail(
                    f"Line {lineno} contains old '/fsd-phase' reference: {line!r}"
                )
