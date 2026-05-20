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
