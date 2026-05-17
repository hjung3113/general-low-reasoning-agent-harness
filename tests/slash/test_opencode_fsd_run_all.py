"""Tests for .opencode/commands/fsd-run-all.md file presence and body shape (§4.4b)."""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".opencode" / "commands" / "fsd-run-all.md"


class TestOpencodesFsdRunAllFileExists:
    def test_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .opencode/commands/fsd-run-all.md per §4.4b net-new."
        )


class TestOpencodesFsdRunAllBodyShape:
    """Validate the §4.4b verbatim body is present (no frontmatter expected)."""

    @pytest.fixture(scope="class")
    def content(self):
        return COMMAND_FILE.read_text(encoding="utf-8")

    def test_no_frontmatter(self, content):
        """OpenCode commands do not use YAML frontmatter (§4.4b)."""
        assert not content.startswith("---"), (
            "OpenCode command files must NOT start with YAML frontmatter '---' "
            "(OpenCode does not support it per §4.4b)."
        )

    def test_starts_with_header(self, content):
        assert content.startswith("# fsd-run-all"), (
            "File must start with '# fsd-run-all' header per §4.4b."
        )

    def test_harness_command_present(self, content):
        assert "harness fsd-run-all" in content, (
            "Body must contain 'harness fsd-run-all' literal."
        )

    def test_chain_driver_responsibilities_header(self, content):
        assert "Chain-driver responsibilities" in content, (
            "Body must contain 'Chain-driver responsibilities' header per §4.4b."
        )

    def test_step_1_harness_status_json(self, content):
        assert "harness status --json" in content, (
            "Step 1 must reference 'harness status --json'."
        )

    def test_step_1_execution_mode_check(self, content):
        assert "chain_autopilot" in content, (
            "Step 1 must reference '.execution_mode == \"chain_autopilot\"'."
        )

    def test_step_2_drive_phase_via_opencode(self, content):
        assert ".opencode/commands/{discuss,plan,execute,done}.md" in content, (
            "Step 2 must reference '.opencode/commands/{discuss,plan,execute,done}.md'."
        )

    def test_step_3_harness_phase_set_done(self, content):
        assert "harness phase set done" in content, (
            "Step 3 must contain 'harness phase set done'."
        )

    def test_step_3_harness_phase_next_pending(self, content):
        assert "harness phase next-pending" in content, (
            "Step 3 must contain 'harness phase next-pending'."
        )

    def test_step_4_autopilot_stop(self, content):
        assert "harness phase autopilot stop" in content, (
            "Step 4 must contain 'harness phase autopilot stop'."
        )

    def test_step_5_never_reinvoke(self, content):
        assert "Never re-invoke `/fsd-run-all`" in content, (
            "Step 5 must contain 'Never re-invoke `/fsd-run-all`'."
        )

    def test_step_6_harness_next_json(self, content):
        assert "harness next --json" in content, (
            "Step 6 must contain 'harness next --json'."
        )

    def test_step_6_requires_human(self, content):
        assert "requires_human" in content, (
            "Step 6 must reference 'requires_human'."
        )

    def test_no_allow_network(self, content, assert_no_forbidden_literals):
        assert_no_forbidden_literals(content)

    def test_six_numbered_steps_present(self, content):
        for step in ("1.", "2.", "3.", "4.", "5.", "6."):
            assert step in content, (
                f"Step '{step}' missing from body per §4.4b."
            )

    def test_no_crlf(self, content):
        assert "\r\n" not in content, "File must not contain CRLF line endings."

    def test_no_bom(self):
        raw = COMMAND_FILE.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "File must not have a UTF-8 BOM."

    def test_trailing_newline(self, content):
        assert content.endswith("\n"), "File must end with a single LF newline."
