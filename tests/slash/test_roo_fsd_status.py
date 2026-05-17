"""Tests for .roo/commands/fsd-status.md file presence and body shape (§12.11).

Validates that the Roo adapter /fsd-status slash command file exists and
contains the verbatim §12.11 body: frontmatter with mode: ask, both
harness invocations, and the requires_human conditional surface logic.
"""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".roo" / "commands" / "fsd-status.md"


class TestRooFsdStatusFileExists:
    def test_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .roo/commands/fsd-status.md per §12.11."
        )


class TestRooFsdStatusBodyShape:
    """Validate the §12.11 verbatim body is present in the Roo adapter file."""

    @pytest.fixture(scope="class")
    def content(self):
        return COMMAND_FILE.read_text(encoding="utf-8")

    def test_starts_with_frontmatter_delimiter(self, content):
        assert content.startswith("---"), (
            "Roo slash file must start with YAML frontmatter delimiter '---'."
        )

    def test_mode_ask(self, content):
        assert "mode: ask" in content, (
            "Frontmatter must contain 'mode: ask' per §12.11."
        )

    def test_description_present(self, content):
        assert "description:" in content, (
            "Frontmatter must contain 'description:' line."
        )

    def test_harness_status_present(self, content):
        assert "harness status" in content, (
            "Body must contain 'harness status' invocation per §12.11."
        )

    def test_harness_next_json_present(self, content):
        assert "harness next --json" in content, (
            "Body must contain 'harness next --json' invocation per §12.11."
        )

    def test_requires_human_conditional_present(self, content):
        assert ".requires_human == true" in content, (
            "Body must contain '.requires_human == true' conditional per §12.11."
        )

    def test_please_run_in_terminal_prefix(self, content):
        assert "please run this in your terminal:" in content, (
            "Body must contain surface prefix "
            "'please run this in your terminal:' per §12.11."
        )

    def test_agent_safe_conditional_present(self, content):
        assert ".agent_safe == true" in content, (
            "Body must contain '.agent_safe == true' guard per §12.11."
        )

    def test_no_forbidden_literals(self, content, assert_no_forbidden_literals):
        assert_no_forbidden_literals(content)

    def test_body_byte_equal_to_spec(self):
        """Byte-equal pin to §12.11 body — spec changes must be propagated explicitly."""
        # This constant is the authoritative §12.11 body for the Roo adapter.
        # If the spec changes, update this constant AND the file atomically.
        # \xe2\x80\x94 = U+2014 EM DASH (—)
        _EXPECTED = (
            b"---\n"
            b"description: Show current phase, halt diary, and next action via the harness state machine\n"
            b"argument-hint:\n"
            b"mode: ask\n"
            b"---\n"
            b"\n"
            b"Run exactly:\n"
            b"\n"
            b"`harness status`\n"
            b"\n"
            b"Then run:\n"
            b"\n"
            b"`harness next --json`\n"
            b"\n"
            b"If `.requires_human == true` in the JSON output, surface the value of `.command`"
            b" to the user with the prefix \"please run this in your terminal:\""
            b" \xe2\x80\x94 do not execute it."
            b" Otherwise execute `.command` only if it is read-only (`.agent_safe == true`);"
            b" else surface and stop.\n"
        )
        actual = COMMAND_FILE.read_bytes()
        assert actual == _EXPECTED, (
            "Roo fsd-status.md byte content does not match §12.11 pin.\n"
            "If the spec changed, update both the file and this constant atomically."
        )
