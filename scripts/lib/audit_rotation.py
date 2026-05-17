"""Audit log rotation helpers (design §2.5).

Provides:
  - enumerate_rotated_files: returns [audit.log.N, ..., audit.log.1, audit.log]
  - RotationResult: dataclass for rotate() results (rotation is handled
    by audit.py's existing _rotate(); this module adds the ordering/seam logic)
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional


@dataclasses.dataclass
class RotationResult:
    """Result of a log rotation operation."""
    rotated_to: Path  # The new audit.log.1 file (old audit.log)
    new_log: Path     # The fresh audit.log
    seed_previous_entry_hash: str  # last entry_hash of rotated-out file


def enumerate_rotated_files(audit_path: Path) -> list[Path]:
    """Return audit.log files in oldest-first order.

    Ordering: [audit.log.N, ..., audit.log.2, audit.log.1, audit.log]

    Only files that actually exist are included. The current audit.log
    is always last (even if empty). Rotated files are ordered by number
    descending (highest number = oldest).
    """
    audit_path = Path(audit_path)
    files: list[tuple[int, Path]] = []

    # Scan for audit.log.N files
    parent = audit_path.parent
    base_name = audit_path.name
    n = 1
    while True:
        candidate = parent / f"{base_name}.{n}"
        if candidate.exists():
            files.append((n, candidate))
            n += 1
        else:
            break

    # Sort by number descending (highest = oldest)
    files.sort(key=lambda x: x[0], reverse=True)
    ordered: list[Path] = [p for _, p in files]

    # Current audit.log is always last
    ordered.append(audit_path)

    return ordered


__all__ = [
    "RotationResult",
    "enumerate_rotated_files",
]
