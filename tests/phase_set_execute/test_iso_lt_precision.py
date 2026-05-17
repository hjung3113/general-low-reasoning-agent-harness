"""Review-fix P2-2 regression — `_iso_lt` parses ISO-Z via datetime,
no longer relies on lexical compare.

Reviewer counter-example: `"2026-05-17T12:00:00.999Z"` vs
`"2026-05-17T12:00:01Z"`. Chronologically the first is earlier; under
lexical comparison the answer is correct only by coincidence (the `.`
character sorts before `Z`). The fractional vs same-second-zero case
(`"2026-05-17T12:00:01.000Z"` vs `"2026-05-17T12:00:01Z"`) DOES misorder
lexically, so we now parse and compare as `datetime`.
"""

from __future__ import annotations

import pytest

from lib import transition


def test_fractional_compares_correctly_vs_seconds_only():
    """The reviewer's exact counter-example."""
    a = "2026-05-17T12:00:00.999Z"
    b = "2026-05-17T12:00:01Z"
    # a < b chronologically.
    assert transition._iso_lt(a, b) is True
    assert transition._iso_lt(b, a) is False


def test_same_second_fractional_zero_vs_no_fraction():
    """`12:00:01.000Z` and `12:00:01Z` represent the same instant —
    neither is strictly less than the other."""
    a = "2026-05-17T12:00:01.000Z"
    b = "2026-05-17T12:00:01Z"
    assert transition._iso_lt(a, b) is False
    assert transition._iso_lt(b, a) is False


def test_nanos_precision_compares_correctly():
    a = "2026-05-17T12:00:01.000001Z"
    b = "2026-05-17T12:00:01.000002Z"
    assert transition._iso_lt(a, b) is True


def test_non_z_suffix_rejected():
    """Producer drift defense — any non-`Z` shape must raise loudly
    rather than silently mis-compare."""
    with pytest.raises(ValueError):
        transition._iso_lt(
            "2026-05-17T12:00:00+00:00", "2026-05-17T12:00:01Z"
        )
    with pytest.raises(ValueError):
        transition._iso_lt(
            "2026-05-17T12:00:00Z", "2026-05-17T12:00:01+00:00"
        )


def test_none_inputs_return_false():
    assert transition._iso_lt(None, "2026-05-17T12:00:00Z") is False
    assert transition._iso_lt("2026-05-17T12:00:00Z", None) is False
    assert transition._iso_lt(None, None) is False
