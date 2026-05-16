import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.managed_block import render_block, BEGIN_MARKER_FMT, END_MARKER_FMT


class RenderBlockTests(unittest.TestCase):
    def test_render_block_wraps_content_with_markers(self):
        rendered = render_block("roadmap-phases", "- [ ] **Phase 0: Hydration**\n")
        self.assertEqual(
            rendered,
            "<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->\n"
            "- [ ] **Phase 0: Hydration**\n"
            "<!-- HARNESS:END managed:roadmap-phases -->\n",
        )

    def test_render_block_canonicalizes_payload(self):
        rendered = render_block("roadmap-phases", "- [ ] x  \r\n\r\n\r\n")
        self.assertEqual(
            rendered,
            "<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->\n"
            "- [ ] x\n"
            "<!-- HARNESS:END managed:roadmap-phases -->\n",
        )

    def test_render_block_rejects_invalid_slug(self):
        with self.assertRaises(ValueError):
            render_block("Roadmap-Phases", "x\n")
        with self.assertRaises(ValueError):
            render_block("1-bad", "x\n")
        with self.assertRaises(ValueError):
            render_block("", "x\n")


if __name__ == "__main__":
    unittest.main()
