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


from lib.managed_block import parse_blocks, replace_block, ParsedBlock, MissingBlockError


SAMPLE_TEXT = (
    "# Title\n\n"
    "Some prose.\n\n"
    "<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->\n"
    "- [ ] **Phase 0: A**\n"
    "<!-- HARNESS:END managed:roadmap-phases -->\n\n"
    "Trailing prose.\n"
)


class ParseBlocksTests(unittest.TestCase):
    def test_parse_blocks_returns_slug_indexed_dict(self):
        blocks = parse_blocks(SAMPLE_TEXT)
        self.assertIn("roadmap-phases", blocks)
        block = blocks["roadmap-phases"]
        self.assertIsInstance(block, ParsedBlock)
        self.assertEqual(block.payload, "- [ ] **Phase 0: A**\n")

    def test_parse_blocks_empty_when_no_markers(self):
        self.assertEqual(parse_blocks("just prose\n"), {})

    def test_parse_blocks_raises_on_unclosed_block(self):
        bad = "<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->\nlines\n"
        with self.assertRaises(ValueError):
            parse_blocks(bad)

    def test_parse_blocks_raises_on_duplicate_slug(self):
        dup = SAMPLE_TEXT + "\n" + (
            "<!-- HARNESS:BEGIN managed:roadmap-phases v1 -->\n"
            "x\n"
            "<!-- HARNESS:END managed:roadmap-phases -->\n"
        )
        with self.assertRaises(ValueError):
            parse_blocks(dup)


class ReplaceBlockTests(unittest.TestCase):
    def test_replace_block_swaps_payload_preserving_surroundings(self):
        new_text = replace_block(SAMPLE_TEXT, "roadmap-phases", "- [x] **Phase 0: A**\n")
        self.assertIn("- [x] **Phase 0: A**", new_text)
        self.assertNotIn("- [ ] **Phase 0: A**", new_text)
        self.assertTrue(new_text.startswith("# Title\n"))
        self.assertTrue(new_text.endswith("Trailing prose.\n"))

    def test_replace_block_missing_raises(self):
        with self.assertRaises(MissingBlockError):
            replace_block("no markers here\n", "roadmap-phases", "x\n")


if __name__ == "__main__":
    unittest.main()
