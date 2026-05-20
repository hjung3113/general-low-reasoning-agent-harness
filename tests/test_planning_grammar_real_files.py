"""Real-file regressions: the prefix-with-separator heading matcher MUST work on these live docs."""

from pathlib import Path
import pytest
from scripts.lib.planning_grammar import heading_matches

REPO = Path(__file__).resolve().parent.parent


def _first_line_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    pytest.skip(f"no heading in {path}")


def test_concerns_md_heading_matches_target():
    path = REPO / ".planning/codebase/CONCERNS.md"
    if not path.exists():
        pytest.skip("CONCERNS.md not present")
    assert heading_matches(_first_line_heading(path), "CONCERNS")


def test_project_md_section_one_liner():
    path = REPO / ".planning/PROJECT.md"
    assert path.exists()
    # The dashboard's load_project_memory calls parse_section_paragraph(text, "One-Liner");
    # ensure that heading matcher finds the section heading.
    heading_line = next(l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("## "))
    assert heading_matches(heading_line.lstrip("#").strip(), "One-Liner") \
        or heading_matches(heading_line.lstrip("#").strip(), "One Liner")  # tolerate either canonical form


def test_state_md_active_checkpoint_heading():
    path = REPO / ".planning/STATE.md"
    text = path.read_text(encoding="utf-8")
    assert any(
        heading_matches(line.lstrip("#").strip(), "Active Checkpoint")
        for line in text.splitlines() if line.startswith("#")
    )
