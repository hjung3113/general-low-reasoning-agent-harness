"""Tests for .opencode/commands/fsd-status.md file presence and body shape (§12.11).

Validates that the OpenCode adapter /fsd-status slash command file exists and
contains the verbatim §12.11 body: no frontmatter, # fsd-status heading, both
harness invocations, and the requires_human conditional surface logic.
"""

from __future__ import annotations

import pytest

from tests.slash.conftest import REPO_ROOT

COMMAND_FILE = REPO_ROOT / ".opencode" / "commands" / "fsd-status.md"


class TestOpencodeFsdStatusFileExists:
    def test_command_file_exists(self):
        assert COMMAND_FILE.exists(), (
            f"{COMMAND_FILE} does not exist. "
            "Expected .opencode/commands/fsd-status.md per §12.11."
        )


class TestOpencodeFsdStatusBodyShape:
    """Validate the §12.11 verbatim body is present in the OpenCode adapter file."""

    @pytest.fixture(scope="class")
    def content(self):
        return COMMAND_FILE.read_text(encoding="utf-8")

    def test_starts_with_fsd_status_heading(self, content):
        assert content.startswith("# fsd-status"), (
            "OpenCode slash file must start with '# fsd-status' heading (no frontmatter) per §12.11."
        )

    def test_no_frontmatter(self, content):
        assert not content.startswith("---"), (
            "OpenCode slash file must NOT start with YAML frontmatter '---' per §12.11."
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
        # This constant is the authoritative §12.11 body for the OpenCode adapter.
        # If the spec changes, update this constant AND the file atomically.
        # \xe2\x80\x94 = U+2014 EM DASH (—)
        _EXPECTED = (
            b"# fsd-status\n"
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
            b" Otherwise execute `.command` only if `.agent_safe == true`;"
            b" else surface and stop.\n"
        )
        actual = COMMAND_FILE.read_bytes()
        assert actual == _EXPECTED, (
            "OpenCode fsd-status.md byte content does not match §12.11 pin.\n"
            "If the spec changed, update both the file and this constant atomically."
        )
