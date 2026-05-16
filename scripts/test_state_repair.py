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


if __name__ == "__main__":
    unittest.main()
