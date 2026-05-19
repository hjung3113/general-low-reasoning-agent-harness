"""Tests for exitcodes symbol completeness."""


def test_human_confirmation_required_symbol_present():
    from scripts.lib import exitcodes
    assert exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED == 17
    assert "EXIT_HUMAN_CONFIRMATION_REQUIRED" in exitcodes.__all__
