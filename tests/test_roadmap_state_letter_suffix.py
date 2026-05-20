"""Regression tests for parse_state_snapshot with letter-suffix phase numbers."""


def test_parse_state_snapshot_letter_suffix():
    """parse_state_snapshot must not return None for a letter-suffix phase like '1b'."""
    from scripts.lib.roadmap_state import parse_state_snapshot

    text = (
        "---\nplanning_doc_schema_version: 1\n---\n"
        "## Current Position\n"
        "- **Phase**: 1b - Side.\n"
    )
    snap = parse_state_snapshot(text)
    # Expect the snapshot's active phase number to be 1 (digits portion of 1b).
    # StateSnapshot uses `active_phase` (int) for the digits portion.
    assert snap.active_phase == 1, f"expected active_phase=1, got {snap.active_phase!r}"


def test_parse_state_snapshot_plain_number():
    """parse_state_snapshot still works for plain integer phase like '2'."""
    from scripts.lib.roadmap_state import parse_state_snapshot

    text = (
        "---\nplanning_doc_schema_version: 1\n---\n"
        "## Current Position\n"
        "- **Phase**: 2 - Regular phase.\n"
    )
    snap = parse_state_snapshot(text)
    assert snap.active_phase == 2, f"expected active_phase=2, got {snap.active_phase!r}"


def test_parse_state_snapshot_letter_suffix_active_phase():
    """active_phase field is correctly set for letter-suffix phases."""
    from scripts.lib.roadmap_state import parse_state_snapshot

    text = (
        "---\nplanning_doc_schema_version: 1\n---\n"
        "## Current Position\n"
        "- **Phase**: 3c - Another sub-phase.\n"
    )
    snap = parse_state_snapshot(text)
    assert snap.active_phase == 3, f"expected active_phase=3, got {snap.active_phase!r}"


def test_parse_state_snapshot_no_phase_line():
    """parse_state_snapshot returns active_phase=None when no Phase line is present."""
    from scripts.lib.roadmap_state import parse_state_snapshot

    text = "---\nplanning_doc_schema_version: 1\n---\n## Current Position\n"
    snap = parse_state_snapshot(text)
    assert snap.active_phase is None
