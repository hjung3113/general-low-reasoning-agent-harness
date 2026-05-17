"""Deferred §12.10 release smoke case catalogue — placeholder pins for S13.

Each parametrize ID corresponds to a named `release_smoke_test.py --case <name>`
invocation described verbatim in §12.10 of the phase-gate hardening design spec
(docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md).

When S13 (`S13-smoke`) lands, each skip should flip to a real implementation
in `scripts/release_smoke_test.py` and this parametrize list should shrink as
cases are promoted to green. Grep for any case_id here to find the canonical
spec row.

S13 implementer checklist:
  1. Build `release_smoke_test.py --case <case_id>` infrastructure.
  2. Remove the matching case_id from the parametrize list below.
  3. Add a real test (or CI job) that exercises the case end-to-end.
  4. When list is empty, delete this file.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Release smoke harness (S13 scope) not yet implemented")
@pytest.mark.parametrize(
    "case_id",
    [
        # §12.10 table — row 1
        "run-phase",
        # §12.10 table — row 2
        "run-phase-empty-arg",
        # §12.10 table — row 3
        "run-phase-multi-arg-fail",
        # §12.10 table — row 4 (OpenCode positional-negative; S08b primary case)
        "run-phase-missing-positional-negative",
        # §12.10 table — row 5
        "run-all",
        # §12.10 table — row 6
        "run-all-empty-roadmap",
        # §12.10 table — row 7 (S10c network shim)
        "net-deny-curl-posix",
        # §12.10 table — row 8 (S11 halt diary)
        "halt-handoff-flow",
        # §12.10 table — row 9
        "status-after-halt",
        # §12.10 table — row 10 (S15 /fsd-status Roo)
        "fsd-status-roo",
        # §12.10 table — row 11 (S15 /fsd-status OpenCode)
        "fsd-status-opencode",
        # §12.10 table — row 12 (env-only spoof rejection)
        "env-only-spoof-rejected",
        # §12.10 table — row 13 (OIDC jti replay)
        "oidc-jti-replay",
        # §12.10 table — row 14 (anchor tampered)
        "anchor-tampered",
        # §12.10 table — row 15 (gitconfig rotated post-install)
        "gitconfig-rotated",
    ],
)
def test_release_smoke_case_deferred(case_id):
    """Placeholder pinned to §12.10 case catalogue. Flips to real test when S13 lands.

    Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12.10
    Slice: S13-smoke (depends_on all S08a/S08b/S09a/S09b/S10c/S11/S15/S16)
    """
    pytest.fail("S13 release_smoke_test.py infrastructure not built")
