"""Shared Roo mode constants (single source of truth).

Centralises the set of Roo built-in mode slugs so that check.py,
doctor.py, and any future consumer import from one place.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §12
"""

from __future__ import annotations

# Built-in Roo mode slugs that always exist regardless of .roomodes config.
# These must not appear in .roomodes customModes (they are implicit).
ROO_BUILTIN_MODES: frozenset[str] = frozenset(
    {"ask", "code", "architect", "debug", "orchestrator"}
)

__all__ = ["ROO_BUILTIN_MODES"]
