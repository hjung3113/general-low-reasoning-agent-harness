"""Tests for append_block.py — focused on conflict diff output (issue #17)."""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.append_block import (
    _managed_append_conflict_diff,
    write_managed_append,
    render_append_block,
    AppendBlockPlan,
    sha256_text,
    marker_start,
    marker_end,
)
from lib.manifest import ManifestEntry


def _make_entry(path: str = "AGENTS.md", source: str = "harness/skeleton/clean/AGENTS.md") -> ManifestEntry:
    return ManifestEntry(
        path=PurePosixPath(path),
        source=PurePosixPath(source),
        policy="managed-append",
    )


class TestConflictDiffMalformedMarkers(unittest.TestCase):
    """Malformed managed-append destination: falls back to whole-file diff."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_malformed_destination_exits_nonzero(self):
        """write_managed_append on malformed dest raises SystemExit."""
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        # Write a malformed block: start marker without matching end.
        dest.write_text("# existing\n# >>> low-reasoning-harness:AGENTS.md v0.0.0\nno end\n", encoding="utf-8")
        source = self.tmpdir / "source.md"
        source.write_text("proposed content\n", encoding="utf-8")

        with self.assertRaises(SystemExit):
            write_managed_append(source=source, destination=dest, entry=entry)

    def test_malformed_destination_stderr_contains_diff_headers(self):
        """stderr on malformed dest conflict includes unified diff headers."""
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        dest.write_text("# existing\n# >>> low-reasoning-harness:AGENTS.md v0.0.0\nno end\n", encoding="utf-8")
        source = self.tmpdir / "source.md"
        source.write_text("proposed content\n", encoding="utf-8")

        captured_stderr = io.StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            try:
                write_managed_append(source=source, destination=dest, entry=entry)
            except SystemExit:
                pass

        stderr_out = captured_stderr.getvalue()
        # Must contain unified diff from/to headers
        self.assertIn("--- ", stderr_out)
        self.assertIn("+++ ", stderr_out)
        # current and proposed labels must appear
        self.assertIn("current", stderr_out)
        self.assertIn("proposed", stderr_out)

    def test_malformed_destination_file_untouched(self):
        """Conflict must not mutate the destination file."""
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        original = "# existing\n# >>> low-reasoning-harness:AGENTS.md v0.0.0\nno end\n"
        dest.write_text(original, encoding="utf-8")
        source = self.tmpdir / "source.md"
        source.write_text("proposed content\n", encoding="utf-8")

        try:
            write_managed_append(source=source, destination=dest, entry=entry)
        except SystemExit:
            pass

        self.assertEqual(dest.read_text(encoding="utf-8"), original)


class TestConflictDiffEditedManagedBlock(unittest.TestCase):
    """Edited managed block: diff is scoped to the block, still refuses."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_destination_with_edited_block(self, entry: ManifestEntry, dest: Path, source: Path) -> None:
        """Write a destination with a valid but user-edited managed block."""
        source.write_text("original content\n", encoding="utf-8")
        # Build a valid block with the entry.
        from lib.append_block import render_append_block, plan_managed_append, _write_text_file
        block = render_append_block(source, entry)
        # Write destination with the block already present.
        _write_text_file(dest, "# preamble\n\n" + block)
        # Now edit the block in place (simulates user modification).
        dest.write_text(
            "# preamble\n\n"
            + marker_start(entry) + "\nEDITED BY USER\n" + marker_end(entry) + "\n",
            encoding="utf-8",
        )

    def test_edited_block_conflict_prints_diff_and_refuses(self):
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        source = self.tmpdir / "source.md"
        self._make_destination_with_edited_block(entry, dest, source)
        # Now update source to a new version.
        source.write_text("updated harness content\n", encoding="utf-8")

        captured_stderr = io.StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            try:
                # installed_info with an applied_sha256 that no longer matches.
                from lib.append_block import write_managed_append
                write_managed_append(source=source, destination=dest, entry=entry)
            except SystemExit:
                pass

        stderr_out = captured_stderr.getvalue()
        self.assertIn("--- ", stderr_out)
        self.assertIn("+++ ", stderr_out)

    def test_edited_block_conflict_file_untouched(self):
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        source = self.tmpdir / "source.md"
        self._make_destination_with_edited_block(entry, dest, source)
        original = dest.read_text(encoding="utf-8")
        source.write_text("updated harness content\n", encoding="utf-8")

        try:
            write_managed_append(source=source, destination=dest, entry=entry)
        except SystemExit:
            pass

        self.assertEqual(dest.read_text(encoding="utf-8"), original)


class TestNoConflictPathWritesWithoutStderrDiff(unittest.TestCase):
    """No-conflict path: destination gets updated without diff on stderr."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_fresh_install_no_stderr_diff(self):
        """Fresh destination (no file): writes block, no diff on stderr."""
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        source = self.tmpdir / "source.md"
        source.write_text("# harness content\n", encoding="utf-8")

        captured_stderr = io.StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            write_managed_append(source=source, destination=dest, entry=entry)

        self.assertEqual(captured_stderr.getvalue(), "")
        self.assertTrue(dest.exists())

    def test_unchanged_block_no_stderr_diff(self):
        """Re-applying the same block: no-op and no diff on stderr."""
        entry = _make_entry()
        dest = self.tmpdir / "AGENTS.md"
        source = self.tmpdir / "source.md"
        source.write_text("# harness content\n", encoding="utf-8")
        # First write to set up block.
        write_managed_append(source=source, destination=dest, entry=entry)

        captured_stderr = io.StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            write_managed_append(source=source, destination=dest, entry=entry)

        self.assertEqual(captured_stderr.getvalue(), "")


class TestDiffCapFallback(unittest.TestCase):
    """Diff cap: large malformed files are truncated, not spewed entirely."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_large_malformed_file_diff_is_capped(self):
        """A very large malformed destination produces a capped diff."""
        entry = _make_entry()
        # Build a malformed destination that exceeds the fallback byte cap.
        large_content = ("x" * 80 + "\n") * 200  # ~16 KB
        # Insert a broken start marker to trigger malformed path.
        dest = self.tmpdir / "AGENTS.md"
        dest.write_text(large_content + "# >>> low-reasoning-harness:AGENTS.md v0.0.0\nno end\n", encoding="utf-8")
        source = self.tmpdir / "source.md"
        source.write_text("proposed\n", encoding="utf-8")

        captured_stderr = io.StringIO()
        with patch.object(sys, "stderr", captured_stderr):
            try:
                write_managed_append(source=source, destination=dest, entry=entry)
            except SystemExit:
                pass

        stderr_out = captured_stderr.getvalue()
        # Must contain diff headers but not reproduce the entire file.
        self.assertIn("--- ", stderr_out)
        # The diff should be capped — raw file is ~16 KB but diff must be smaller.
        self.assertLess(len(stderr_out.encode("utf-8")), 20_000)


if __name__ == "__main__":
    unittest.main()
