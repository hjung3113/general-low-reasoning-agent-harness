"""Canonical path tuples for managed state + operational artifacts.

Owning plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §2

These tuples are the SOLE declaration site for the path literals.
Per CONTRACT-PIN §2 rule: "operational_paths.py is the sole declarer of
the path-tuple literals. T0-A's grep gate imports from this module."

The values below are the post-ADR pinned shape from CONTRACT-PIN §2.
T0-A may land before ADR-003a locks; if downstream slices need to
adjust the literals, the update happens in T0-3 in lockstep with the
grep gate (no parallel declaration sites permitted).
"""

from __future__ import annotations

STATE_FILE_PATHS: tuple[str, ...] = (
    ".scratch/phase-state.json",
)

OPERATIONAL_PATHS: tuple[str, ...] = (
    ".harness/audit.log",
    ".harness/session.lock",
    ".harness/backups/",
)

INSTALL_PATHS: tuple[str, ...] = (
    ".harness/installed-manifest.json",
)


__all__ = ["STATE_FILE_PATHS", "OPERATIONAL_PATHS", "INSTALL_PATHS"]
