import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.state_repair import (
    canonical_roadmap_phases_payload,
    canonical_state_current_payload,
    repair,
    RepairReport,
)
from lib.roadmap_state import RoadmapPhase


class CanonicalRenderTests(unittest.TestCase):
    def test_canonical_roadmap_phases_payload_renders_checkbox_list(self):
        phases = [
            RoadmapPhase(number=0, title="Planning Hydration", completed=True),
            RoadmapPhase(number=1, title="Schema Module", completed=False),
        ]
        payload = canonical_roadmap_phases_payload(phases)
        self.assertEqual(
            payload,
            "- [x] **Phase 0: Planning Hydration**\n"
            "- [ ] **Phase 1: Schema Module**\n",
        )

    def test_canonical_state_current_payload_renders_section(self):
        payload = canonical_state_current_payload(
            phase=1,
            phase_title="Schema Module",
            checkpoint="CP-01-01",
            checkpoint_path=".planning/phases/01-schema/01-CHECKPOINTS.md",
        )
        self.assertIn("- **Phase**: 1 - Schema Module", payload)
        self.assertIn("- **Checkpoint**: CP-01-01", payload)
        self.assertIn(
            "- **Checkpoint file**: `.planning/phases/01-schema/01-CHECKPOINTS.md`",
            payload,
        )


ROADMAP_BEFORE = """# ROADMAP

## Phases

- [x] **Phase 0: Planning Hydration**
- [ ] **Phase 1: Schema Module**

## Notes

Free-form notes here.
"""

STATE_BEFORE = """---
gsd_state_version: 1.0
milestone: m0
progress:
  total_phases: 2
  completed_phases: 1
  percent: 50
---

# STATE

## Current Position

- **Phase**: 1 - Schema Module

## Active Checkpoint

- **Checkpoint**: CP-01-01
- **Checkpoint file**: `.planning/phases/01-schema/01-CHECKPOINTS.md`
"""

PHASE_STATE_BEFORE = {
    "phase": "discuss",
    "state_path": ".planning/STATE.md",
    "checkpoint_path": ".planning/phases/01-schema/01-CHECKPOINTS.md",
    "current_checkpoint": "CP-01-01",
}


class RepairEndToEndTests(unittest.TestCase):
    def _make_target(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".planning").mkdir()
        (tmp / ".scratch").mkdir()
        (tmp / ".planning/ROADMAP.md").write_text(ROADMAP_BEFORE, encoding="utf-8")
        (tmp / ".planning/STATE.md").write_text(STATE_BEFORE, encoding="utf-8")
        (tmp / ".scratch/phase-state.json").write_text(
            json.dumps(PHASE_STATE_BEFORE), encoding="utf-8"
        )
        return tmp

    def test_repair_adds_markers_when_missing(self):
        root = self._make_target()
        report = repair(root)
        roadmap = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        state = (root / ".planning/STATE.md").read_text(encoding="utf-8")
        self.assertIn("HARNESS:BEGIN managed:roadmap-phases", roadmap)
        self.assertIn("HARNESS:END managed:roadmap-phases", roadmap)
        self.assertIn("HARNESS:BEGIN managed:state-current", state)
        self.assertIn(".planning/ROADMAP.md", report.markers_added)
        self.assertIn(".planning/STATE.md", report.markers_added)

    def test_repair_preserves_free_form_notes(self):
        root = self._make_target()
        repair(root)
        roadmap = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("## Notes\n\nFree-form notes here.", roadmap)

    def test_repair_is_idempotent(self):
        root = self._make_target()
        repair(root)
        first = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        report = repair(root)
        second = (root / ".planning/ROADMAP.md").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(report.files_updated, [])


if __name__ == "__main__":
    unittest.main()
