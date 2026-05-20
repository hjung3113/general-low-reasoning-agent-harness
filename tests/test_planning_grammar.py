import pytest
from scripts.lib.planning_grammar import parse_frontmatter


def test_parse_frontmatter_flat_keys():
    text = "---\nfoo: bar\nbaz: qux\n---\nbody\n"
    assert parse_frontmatter(text) == {"foo": "bar", "baz": "qux"}


def test_parse_frontmatter_nested_dotted_keys():
    text = "---\nprogress:\n  percent: 50\n  total_phases: 2\n---\n"
    fm = parse_frontmatter(text)
    assert fm["progress.percent"] == "50"
    assert fm["progress.total_phases"] == "2"


def test_parse_frontmatter_value_with_colon_preserved():
    assert parse_frontmatter("---\nurl: https://example.com/foo\n---\n")["url"] == "https://example.com/foo"


def test_parse_frontmatter_no_frontmatter_returns_empty():
    assert parse_frontmatter("# Title\n") == {}


from scripts.lib.planning_grammar import (
    PHASE_FOLDER_REGEX,
    canonical_phase_id,
    display_phase_id,
)


def test_canonical_phase_id_plain_numeric():
    assert canonical_phase_id(".planning/phases/02-foo") == "02"


def test_canonical_phase_id_letter_suffix():
    assert canonical_phase_id(".planning/phases/02b-hardening") == "02b"


def test_canonical_phase_id_two_digit():
    assert canonical_phase_id(".planning/phases/10-release") == "10"


def test_canonical_phase_id_non_phase_folder_returns_empty():
    assert canonical_phase_id(".planning/phases/scratch-junk") == ""


def test_canonical_phase_id_no_slash_just_folder_name():
    assert canonical_phase_id("02c-extra") == "02c"


def test_display_phase_id_strips_leading_zero():
    assert display_phase_id("02b") == "2b"
    assert display_phase_id("02") == "2"
    assert display_phase_id("10") == "10"
    assert display_phase_id("") == ""


def test_display_phase_id_non_digit_input_returns_input():
    assert display_phase_id("xy") == "xy"


from scripts.lib.planning_grammar import (
    parse_state_phase_line,
    parse_state_checkpoint_line,
    parse_roadmap_phase_bullets,
    heading_matches,
)


def test_parse_state_phase_line_trailing_period():
    text = "- **Phase**: 2 - v0.8.0 Minimal Workflow Release.\n"
    assert parse_state_phase_line(text) == ("02", "v0.8.0 Minimal Workflow Release")


def test_parse_state_phase_line_no_period():
    assert parse_state_phase_line("- **Phase**: 2 - v0.8.0 Minimal Workflow Release\n") == (
        "02", "v0.8.0 Minimal Workflow Release",
    )


def test_parse_state_phase_line_letter_suffix():
    assert parse_state_phase_line("- **Phase**: 2b - Hardening.\n") == ("02b", "Hardening")


def test_parse_state_phase_line_strips_trailing_bold():
    text = "- **Phase**: 2 - v0.8.0 **(in progress)**.\n"
    pid, title = parse_state_phase_line(text)
    assert pid == "02"
    assert title == "v0.8.0"  # trailing bold annotation stripped


def test_parse_state_checkpoint_line_numeric():
    pid, title = parse_state_checkpoint_line("- **Checkpoint**: CP-02-02 - contract and behavior.\n")
    assert pid == "CP-02-02"
    assert title == "contract and behavior"


def test_parse_state_checkpoint_line_letter_suffix():
    pid, title = parse_state_checkpoint_line("- **Checkpoint**: CP-02b-01 - foo.\n")
    assert pid == "CP-02b-01"
    assert title == "foo"


def test_parse_roadmap_phase_bullets_basic():
    text = (
        "- [x] **Phase 1: Generalized Harness Release** - one\n"
        "- [ ] **Phase 2: v0.8.0** - two\n"
    )
    bullets = parse_roadmap_phase_bullets(text)
    assert [(b.phase_id, b.completed, b.title) for b in bullets] == [
        ("01", True, "Generalized Harness Release"),
        ("02", False, "v0.8.0"),
    ]


def test_parse_roadmap_phase_bullets_letter_suffix():
    bullets = parse_roadmap_phase_bullets("- [ ] **Phase 2b: Hardening** - p\n")
    assert bullets[0].phase_id == "02b"
    assert bullets[0].title == "Hardening"


def test_heading_matches_exact():
    assert heading_matches("Blockers", "Blockers")


def test_heading_matches_separator():
    assert heading_matches("CONCERNS - General Harness", "CONCERNS")
    assert heading_matches("One-Liner — short", "One-Liner")
    assert heading_matches("Blockers (active)", "Blockers")
    assert heading_matches("Scope / extras", "Scope")


def test_heading_matches_case_insensitive():
    assert heading_matches("blockers", "Blockers")


def test_heading_matches_rejects_superstring_without_separator():
    assert not heading_matches("BlockersResolved", "Blockers")


def test_heading_matches_rejects_substring_inside_phrase():
    assert not heading_matches("Known Blockers", "Blockers")
    assert not heading_matches("Concerns / Blockers", "Blockers")


from scripts.lib.planning_grammar import (
    PLANNING_DOC_SCHEMA_VERSION,
    extract_planning_doc_schema_version,
    PlanningDocSchemaVersionError,
)


def test_planning_doc_schema_constant_is_1():
    assert PLANNING_DOC_SCHEMA_VERSION == 1


def test_extract_planning_doc_schema_version_present():
    text = "---\nplanning_doc_schema_version: 1\n---\n"
    assert extract_planning_doc_schema_version(text) == 1


def test_extract_planning_doc_schema_version_missing_returns_none():
    assert extract_planning_doc_schema_version("---\nfoo: bar\n---\n") is None


def test_extract_planning_doc_schema_version_wrong_raises():
    with pytest.raises(PlanningDocSchemaVersionError):
        extract_planning_doc_schema_version("---\nplanning_doc_schema_version: 99\n---\n")


def test_extract_planning_doc_schema_version_non_integer_raises():
    with pytest.raises(PlanningDocSchemaVersionError):
        extract_planning_doc_schema_version("---\nplanning_doc_schema_version: oops\n---\n")
