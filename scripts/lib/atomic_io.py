"""Atomic I/O primitives for managed state and operational logs.

Owning plan: .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md (T0-A)
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1
ADR: docs/adr/2026-05-16-hardening-bundle.md (Artifact 2, G1-A, G1-D)

Exports (skeleton — bodies filled in subsequent commits per plan task order):
- atomic_write_text(path, content, *, mode=0o644)
- atomic_append_log(path, line, *, max_bytes_per_line=512)
"""

from __future__ import annotations

from pathlib import Path


def atomic_write_text(path: Path, content: str, *, mode: int = 0o644) -> None:
    """Atomic write skeleton — body lands in subsequent GREEN commits.

    Currently unimplemented; tests for happy-path/atomicity/preconditions are
    RED until the corresponding GREEN commits fill in the body.
    """
    raise NotImplementedError("atomic_write_text body not yet implemented")


def atomic_append_log(path: Path, line: str, *, max_bytes_per_line: int = 512) -> None:
    """Atomic append skeleton — body lands in subsequent GREEN commits."""
    raise NotImplementedError("atomic_append_log body not yet implemented")
