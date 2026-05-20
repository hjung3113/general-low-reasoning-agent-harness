"""Tests for exitcodes symbol completeness."""


def test_human_confirmation_required_symbol_present():
    from scripts.lib import exitcodes
    assert exitcodes.EXIT_HUMAN_CONFIRMATION_REQUIRED == 17
    assert "EXIT_HUMAN_CONFIRMATION_REQUIRED" in exitcodes.__all__


def test_exit_planning_drift_is_12():
    from scripts.lib import exitcodes
    assert exitcodes.EXIT_PLANNING_DRIFT == 12
