import io
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import state_cli


class StateCliTests(unittest.TestCase):
    def _make_root(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".planning").mkdir()
        (tmp / ".scratch").mkdir()
        (tmp / ".planning/ROADMAP.md").write_text(
            "# R\n\n## Phases\n\n- [ ] **Phase 0: A**\n", encoding="utf-8"
        )
        (tmp / ".planning/STATE.md").write_text(
            "---\nprogress:\n  total_phases: 1\n  completed_phases: 0\n  percent: 0\n---\n\n"
            "# S\n\n## Current Position\n\n- **Phase**: 0\n",
            encoding="utf-8",
        )
        (tmp / ".scratch/phase-state.json").write_text(
            json.dumps({"phase": "discuss", "state_path": ".planning/STATE.md"}),
            encoding="utf-8",
        )
        return tmp

    def test_show_command_prints_summary(self):
        root = self._make_root()
        buf = io.StringIO()
        rc = state_cli.run_show(root=root, stream=buf, fmt="text")
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("phase", out.lower())

    def test_show_command_json(self):
        root = self._make_root()
        buf = io.StringIO()
        rc = state_cli.run_show(root=root, stream=buf, fmt="json")
        data = json.loads(buf.getvalue())
        self.assertEqual(rc, 0)
        self.assertIn("phase", data)

    def test_repair_command_writes_markers(self):
        root = self._make_root()
        buf = io.StringIO()
        rc = state_cli.run_repair(root=root, stream=buf)
        self.assertEqual(rc, 0)
        roadmap = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("HARNESS:BEGIN managed:roadmap-phases", roadmap)


if __name__ == "__main__":
    unittest.main()
