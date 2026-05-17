"""P2-5: Consistency test asserting release_terms.FORBIDDEN ⊆ stale_terms.FORBIDDEN.

Every term checked by grep_gate_release_terms.py (the narrow, adapter-only
release gate) must also be checked by grep_gate_stale_terms.py (the
consolidated full sweep). This guarantees the full sweep is at least as
strict as the release gate — an operator can run either gate and trust that
the release gate's coverage is fully subsumed.

Direction rationale:
  stale_terms covers ALL term categories from S14 (launchers, deprecated CLI
  flags, deprecated fields, deprecated verbs, deprecated env vars).
  release_terms covers a subset (§7 line 1022: the mandatory pre-release set).
  Therefore: release_terms.FORBIDDEN ⊆ stale_terms.FORBIDDEN (strict subset
  or equal); stale_terms may have additional terms beyond release_terms.

If this test fails it means a term was added to release_terms without a
corresponding entry in stale_terms (or vice versa if the subset direction
is reversed). Document the intent with a code comment in both gate scripts.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §7 + §9
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _collect_stale_terms() -> frozenset[str]:
    """Extract all forbidden term strings from grep_gate_stale_terms.py's CATEGORIES."""
    from smoke.grep_gate_stale_terms import LAUNCHER_TERMS, _FULL_CATEGORIES

    terms: set[str] = set(LAUNCHER_TERMS)
    for _label, term_tuple, _globs in _FULL_CATEGORIES:
        terms.update(term_tuple)
    return frozenset(terms)


def _collect_release_terms() -> frozenset[str]:
    """Extract RELEASE_TERMS from grep_gate_release_terms.py."""
    from smoke.grep_gate_release_terms import RELEASE_TERMS

    return frozenset(RELEASE_TERMS)


class TestGateTermOverlap:
    """release_terms.FORBIDDEN must be a subset of stale_terms.FORBIDDEN."""

    def test_release_terms_subset_of_stale_terms(self):
        """Every term in release_terms must also appear in stale_terms (P2-5).

        stale_terms is the consolidated S14 sweep; release_terms is the
        mandatory §7 pre-release set. The full sweep must subsume the release
        gate's coverage.
        """
        stale = _collect_stale_terms()
        release = _collect_release_terms()
        not_in_stale = release - stale
        assert not not_in_stale, (
            f"release_terms has term(s) not covered by stale_terms: {sorted(not_in_stale)}\n"
            "Fix: add the missing term(s) to grep_gate_stale_terms.py's _FULL_CATEGORIES "
            "or LAUNCHER_TERMS, or document why stale_terms intentionally excludes them "
            "with a code comment + test annotation."
        )

    def test_both_term_sets_nonempty(self):
        """Sanity: both gate term sets must be non-empty."""
        stale = _collect_stale_terms()
        release = _collect_release_terms()
        assert len(stale) >= 1, "stale_terms has no terms — import likely broken"
        assert len(release) >= 1, "release_terms has no terms — import likely broken"
