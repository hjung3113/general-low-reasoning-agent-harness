from tests._helpers.planning_repo import make_minimal_planning_repo


def test_projection_recognizes_letter_suffix_phase(tmp_path):
    root = make_minimal_planning_repo(tmp_path)
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    assert proj.phase_id == "02b"
    assert proj.active_checkpoint_id == "CP-02b-01"
    assert proj.verification_path == ".planning/phases/02b-hardening/02b-VERIFICATION.md"
    assert proj.active_checkpoint_status == "in_progress"


def test_projection_phase_title_strips_trailing_bold(tmp_path):
    root = make_minimal_planning_repo(tmp_path, roadmap_title="Hardening **(in progress)**")
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    assert proj.phase_id == "02b"
    # Roadmap title is the source of truth here; STATE title parser strips trailing bold.
    assert "**" not in proj.phase_title
