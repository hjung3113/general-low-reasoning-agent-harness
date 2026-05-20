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
