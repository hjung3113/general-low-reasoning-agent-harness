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


def test_projection_warns_when_schema_version_missing(tmp_path):
    root = make_minimal_planning_repo(tmp_path, schema_version_line="")
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    codes = [w.code for w in proj.warnings]
    assert "planning_doc_schema_version_missing" in codes
    # missing is non-blocking; should NOT prevent projection
    assert any(w.code == "planning_doc_schema_version_missing" and w.severity == "warning" for w in proj.warnings)


def test_projection_blocks_when_schema_version_unsupported(tmp_path):
    root = make_minimal_planning_repo(tmp_path, schema_version_line="planning_doc_schema_version: 99\n")
    from scripts.lib.planning_status import load_projection
    proj = load_projection(root)
    blocking = [w for w in proj.warnings if w.code == "planning_doc_schema_version_unsupported"]
    assert len(blocking) == 1
    assert blocking[0].severity == "blocking"
