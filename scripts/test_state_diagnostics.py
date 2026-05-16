#!/usr/bin/env python3
"""Tests for scripts/lib/state_diagnostics.py (T1-M malformed-state helper).

Plan: .planning/phases/02b-hardening/plans/02b-09-T1-M-PLAN.md
Contract: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §3, §4, §5.1, §7
ADR: docs/adr/2026-05-16-hardening-bundle.md (ADR-005, ADR-003a Artifact 1)
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import state_diagnostics  # noqa: E402
from lib.exitcodes import EXIT_UNPARSEABLE_JSON  # noqa: E402


# ---------------------------------------------------------------------------
# load_state_json: happy + empty + truncated (plan tests 1-3)
# ---------------------------------------------------------------------------


class TestLoadStateJsonHappyPath(unittest.TestCase):
    def test_returns_dict_on_valid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            payload = {"phase": "discuss", "approved": False}
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = state_diagnostics.load_state_json(path)
            self.assertEqual(result, payload)


class TestLoadStateJsonTruncated(unittest.TestCase):
    def test_truncated_raises_systemexit_5_with_file_line_col(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            # Truncated JSON: open string, no close brace.
            path.write_text('{"phase": "exec', encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            # JSONDecodeError supplies line + col; the diagnostic surfaces them.
            self.assertRegex(err, r"line\s+\d+")
            self.assertRegex(err, r"col\s*\d+|column\s*\d+")
            # Remediation hint sentence per ADR-003a / ADR-005.
            self.assertIn("fix the JSON", err)


class TestLoadStateJsonEmptyFile(unittest.TestCase):
    def test_empty_file_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "phase-state.json"
            path.write_text("", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("empty file", err.lower())


# ---------------------------------------------------------------------------
# Remediation hint precedence: sidecar > backup-listing > default
# (plan tests 4-6)
# ---------------------------------------------------------------------------


def _write_broken_state(repo: Path) -> Path:
    state_dir = repo / ".scratch"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "phase-state.json"
    path.write_text('{"phase":', encoding="utf-8")  # truncated
    return path


class TestRemediationHints(unittest.TestCase):
    def test_diagnostic_suggests_resume_when_sidecar_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backups = repo / ".harness" / "backups"
            backups.mkdir(parents=True)
            sidecar = (
                backups
                / "phase-state.json.pre-repair.20260516T193045123456789Z.12345.bak.resume.json"
            )
            sidecar.write_text("{}", encoding="utf-8")
            path = _write_broken_state(repo)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.load_state_json(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            self.assertIn("harness migrate state --resume", buf.getvalue())

    def test_diagnostic_lists_backups_when_present_and_no_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backups = repo / ".harness" / "backups"
            backups.mkdir(parents=True)
            for stamp in (
                "20260514T100000000000000Z.111.bak",
                "20260515T100000000000000Z.222.bak",
                "20260516T100000000000000Z.333.bak",
            ):
                (backups / f"phase-state.json.pre-repair.{stamp}").write_text("{}", encoding="utf-8")
            path = _write_broken_state(repo)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    state_diagnostics.load_state_json(path)
            err = buf.getvalue()
            # Newest by lexical sort is the 20260516 one.
            self.assertIn(
                "phase-state.json.pre-repair.20260516T100000000000000Z.333.bak",
                err,
            )
            self.assertIn("restore from .harness/backups/", err)

    def test_diagnostic_omits_resume_and_backups_when_neither_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".scratch").mkdir()
            (repo / ".harness").mkdir()
            path = _write_broken_state(repo)
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit):
                    state_diagnostics.load_state_json(path)
            err = buf.getvalue()
            self.assertNotIn("harness migrate state --resume", err)
            self.assertNotIn("restore from .harness/backups/", err)
            self.assertIn("fix the JSON", err)


# ---------------------------------------------------------------------------
# parse_state_markdown: duplicate slug + unbalanced + invalid slug
# (plan tests 7-9)
# ---------------------------------------------------------------------------


class TestParseStateMarkdownDuplicateSlug(unittest.TestCase):
    def test_duplicate_slug_raises_systemexit_5_with_two_line_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "first\n"
                "<!-- HARNESS:END managed:foo -->\n"
                "\n"
                "intermediate\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "second\n"
                "<!-- HARNESS:END managed:foo -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("foo", err)
            # Both BEGIN line numbers must appear: line 3 and line 9.
            self.assertIn("3", err)
            self.assertIn("9", err)


class TestParseStateMarkdownUnbalanced(unittest.TestCase):
    def test_unbalanced_markers_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "payload without close\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("3", err)  # BEGIN line number
            self.assertIn("unbalanced", err.lower())


class TestParseStateMarkdownInvalidSlug(unittest.TestCase):
    def test_invalid_slug_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "<!-- HARNESS:BEGIN managed:Foo_BAD v1 -->\n"
                "x\n"
                "<!-- HARNESS:END managed:Foo_BAD -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            self.assertIn("Foo_BAD", err)


# ---------------------------------------------------------------------------
# Frontmatter delimiter validation (plan tests 10-11)
# ---------------------------------------------------------------------------


class TestParseStateMarkdownFrontmatter(unittest.TestCase):
    def test_unclosed_frontmatter_raises_systemexit_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "---\n"
                "phase: 1\n"
                "progress:\n"
                "  total_phases: 3\n"
                "# (no closing --- before body)\n"
                "\n"
                "## Section\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            self.assertIn(str(path), err)
            # Start line of the frontmatter is 1.
            self.assertIn("line 1", err)
            self.assertIn("closing", err.lower())
            self.assertIn("---", err)

    def test_valid_frontmatter_then_invalid_body_partial_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "STATE.md"
            text = (
                "---\n"
                "phase: 1\n"
                "---\n"
                "\n"
                "# Title\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "first\n"
                "<!-- HARNESS:END managed:foo -->\n"
                "\n"
                "<!-- HARNESS:BEGIN managed:foo v1 -->\n"
                "dup\n"
                "<!-- HARNESS:END managed:foo -->\n"
            )
            path.write_text(text, encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    state_diagnostics.parse_state_markdown(path)
            self.assertEqual(ctx.exception.code, EXIT_UNPARSEABLE_JSON)
            err = buf.getvalue()
            # Body-section failure must cite the duplicate slug (one of the
            # duplicate BEGIN line numbers).
            self.assertIn("foo", err)
            self.assertIn("7", err)  # first BEGIN
            self.assertIn("11", err)  # second BEGIN
            # Frontmatter ack: the diagnostic must NOT discard the fact that
            # frontmatter parsed — operator should see context that the
            # failure is in the body, not the header.
            self.assertIn("body", err.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
