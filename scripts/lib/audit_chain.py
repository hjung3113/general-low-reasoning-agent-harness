"""Per-entry hash chain for audit logs (design §2.2, §2.3, §2.5).

Implements the per-entry hash chain (B) from ADR D-3:
  entry_hash = sha256(canonical_json(entry_minus_entry_hash || previous_entry_hash))

Canonicalization uses rfc8785 (RFC 8785 — JSON Canonicalization Scheme).
The `previous_entry_hash` field participates in the canonical input of the
current entry. `entry_hash` itself is excluded (self-referential).

First-ever entry uses previous_entry_hash = GENESIS_HASH ("0" * 64).

Design refs: §2.2, §2.3, §2.4, §2.5, §3.4, §12.5 #1, §12.9
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Iterator, Mapping, Optional

import rfc8785


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS_HASH = "0" * 64
EXIT_CHAIN_ERROR = 10
EXIT_BOM_ERROR = 5
BOM = b"\xef\xbb\xbf"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class AuditChainError(OSError):
    """Base class for audit chain integrity errors. Maps to exit 10 (§3.4)."""
    exit_code: int = EXIT_CHAIN_ERROR

    def __init__(self, message: str, *, exit_code: int = EXIT_CHAIN_ERROR):
        super().__init__(message)
        self.exit_code = exit_code


class AuditChainGapError(AuditChainError):
    """Missing seq_global or missing rotation file — exit 10 `audit_chain_gap`."""
    pass


class AuditChainDuplicateError(AuditChainError):
    """Duplicate seq_global value — exit 10 `audit_chain_duplicate`."""
    pass


class AuditChainTruncationError(AuditChainError):
    """Tail entry_hash does not match recorded tip — exit 10 `audit_chain_truncation`."""
    pass


class AuditChainRotationSeamError(AuditChainError):
    """previous_entry_hash mismatch at rotation boundary — exit 10 `audit_chain_rotation_seam`."""
    pass


class AuditChainTamperedError(AuditChainError):
    """entry_hash recomputed differs from stored — exit 10 `audit_chain_tampered`."""
    pass


class AuditBomError(AuditChainError):
    """BOM prefix in audit log — exit 5 (§2.4)."""
    def __init__(self, message: str):
        super().__init__(message, exit_code=EXIT_BOM_ERROR)


# ---------------------------------------------------------------------------
# Canonicalization (§2.3)
# ---------------------------------------------------------------------------

def _canonical_bytes(obj: Mapping) -> bytes:
    """Return RFC 8785 canonical JSON bytes for `obj`."""
    return rfc8785.dumps(dict(obj))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def compute_entry_hash(entry_dict: Mapping) -> str:
    """Compute sha256 of the rfc8785 canonical form of `entry_dict`.

    `entry_hash` is excluded from the input (it is self-referential).
    `previous_entry_hash` IS included in the input (it links the chain).
    """
    # Exclude entry_hash from the canonical input
    d = {k: v for k, v in entry_dict.items() if k != "entry_hash"}
    canonical = _canonical_bytes(d)
    return hashlib.sha256(canonical).hexdigest()


def stamp_chain_fields(
    draft: dict,
    *,
    previous_entry_hash: str,
    seq: int,
    seq_global: int,
) -> dict:
    """Fill in chain fields on `draft` and compute `entry_hash` last.

    Modifies a copy of `draft` (does not mutate the input).
    Fields set:
      - schema_version: 2 (if not already set)
      - seq: per-file sequence number
      - seq_global: monotonic global sequence number
      - previous_entry_hash: hash of prior entry
      - entry_hash: sha256 of this entry's canonical bytes (excluding entry_hash)

    Returns the stamped dict.
    """
    result = dict(draft)
    result.setdefault("schema_version", 2)
    result["seq"] = seq
    result["seq_global"] = seq_global
    result["previous_entry_hash"] = previous_entry_hash
    # Compute entry_hash LAST (after all other fields are set)
    result["entry_hash"] = compute_entry_hash(result)
    return result


# ---------------------------------------------------------------------------
# ChainStep — yielded by walk_chain
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ChainStep:
    """One step in the chain walk."""
    entry: dict
    seq_global: Optional[int]
    file: Path


# ---------------------------------------------------------------------------
# ChainVerifyResult — returned by verify_chain
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ChainVerifyResult:
    """Result of a full chain sweep."""
    ok: bool
    entries_walked: int
    rotation_files_traversed: int
    final_tip_hash: Optional[str]
    error: Optional[AuditChainError]


# ---------------------------------------------------------------------------
# enumerate_rotated_files (re-exported for convenience)
# ---------------------------------------------------------------------------

def _enumerate_rotated_files(audit_path: Path) -> list[Path]:
    """Return [audit.log.N, ..., audit.log.1, audit.log] (oldest first)."""
    from .audit_rotation import enumerate_rotated_files
    return enumerate_rotated_files(audit_path)


# ---------------------------------------------------------------------------
# BOM check
# ---------------------------------------------------------------------------

def _check_bom(path: Path) -> None:
    """Raise AuditBomError if `path` starts with UTF-8 BOM (§2.4)."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with open(path, "rb") as f:
        header = f.read(3)
    if header == BOM:
        raise AuditBomError(
            f"BOM prefix detected in {path}. "
            f"Fix: run 'harness repair --strip-bom {path}' to migrate."
        )


# ---------------------------------------------------------------------------
# walk_chain
# ---------------------------------------------------------------------------

def walk_chain(
    audit_path: Path,
    *,
    rotation_dir: Optional[Path] = None,
) -> Iterator[ChainStep]:
    """Walk all entries in chain order, yielding ChainStep for each entry.

    If `rotation_dir` is provided, rotated files in that directory are
    also traversed (oldest first, then current).

    Raises:
      - AuditBomError (exit 5): BOM prefix in any file
      - AuditChainGapError (exit 10): missing rotation file / seq_global gap
      - AuditChainDuplicateError (exit 10): duplicate seq_global
      - AuditChainTamperedError (exit 10): entry_hash mismatch
      - AuditChainRotationSeamError (exit 10): rotation seam hash mismatch
    """
    audit_path = Path(audit_path)

    # Build ordered file list
    if rotation_dir is not None:
        files = _enumerate_rotated_files_with_gap_check(audit_path, Path(rotation_dir))
    else:
        if not audit_path.exists():
            return
        files = [audit_path]

    prev_hash = GENESIS_HASH
    last_file_last_hash: Optional[str] = None
    seen_seq_globals: set[int] = set()
    first_entry_of_new_file = False

    for file_idx, file_path in enumerate(files):
        _check_bom(file_path)

        if not file_path.exists() or file_path.stat().st_size == 0:
            continue

        is_first_file = (file_idx == 0)
        file_entries = _read_entries(file_path)

        for entry_idx, entry in enumerate(file_entries):
            # Check rotation seam: first v2 entry in non-first file must chain to last of prior file
            if not is_first_file and entry_idx == 0 and last_file_last_hash is not None:
                entry_prev = entry.get("previous_entry_hash")
                schema = entry.get("schema_version", 1)
                if schema >= 2 and entry_prev is not None:
                    if entry_prev != last_file_last_hash:
                        raise AuditChainRotationSeamError(
                            f"Rotation seam hash mismatch in {file_path} at entry 0: "
                            f"expected previous_entry_hash={last_file_last_hash!r} "
                            f"but got {entry_prev!r}. "
                            f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose."
                        )

            # Skip chain verification for legacy v1 entries
            schema = entry.get("schema_version", 1)
            if schema < 2 or "entry_hash" not in entry:
                # v1 entry — tolerate, advance prev_hash only if entry has entry_hash
                if "entry_hash" in entry:
                    prev_hash = entry["entry_hash"]
                    last_file_last_hash = prev_hash
                yield ChainStep(
                    entry=entry,
                    seq_global=entry.get("seq_global"),
                    file=file_path,
                )
                continue

            # Check duplicate seq_global and monotonic gaps
            sg = entry.get("seq_global")
            if sg is not None:
                if sg in seen_seq_globals:
                    raise AuditChainDuplicateError(
                        f"Duplicate seq_global={sg} in {file_path}. "
                        f"Fix: run 'harness verify --audit' to diagnose."
                    )
                # Check for gaps in seq_global (must be monotonically increasing)
                if seen_seq_globals:
                    max_seen = max(seen_seq_globals)
                    if sg > max_seen + 1:
                        raise AuditChainGapError(
                            f"seq_global gap detected: expected {max_seen + 1} "
                            f"but got {sg} in {file_path}. "
                            f"Fix: run 'harness verify --audit' to diagnose."
                        )
                seen_seq_globals.add(sg)

            # Verify entry_hash
            entry_for_hash = {k: v for k, v in entry.items() if k != "entry_hash"}
            computed = compute_entry_hash(entry_for_hash)
            stored = entry["entry_hash"]
            if computed != stored:
                raise AuditChainTamperedError(
                    f"entry_hash mismatch at seq_global={sg} in {file_path}: "
                    f"stored={stored!r}, computed={computed!r}. "
                    f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose."
                )

            # Verify previous_entry_hash chain link
            entry_prev = entry.get("previous_entry_hash")
            if entry_prev is not None and entry_idx > 0:
                # Within same file, previous must match last entry's hash
                if entry_prev != prev_hash:
                    raise AuditChainTamperedError(
                        f"Chain break at seq_global={sg} in {file_path}: "
                        f"previous_entry_hash={entry_prev!r} does not match "
                        f"prior entry_hash={prev_hash!r}. "
                        f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose."
                    )

            prev_hash = stored
            last_file_last_hash = stored

            yield ChainStep(
                entry=entry,
                seq_global=sg,
                file=file_path,
            )

        # After processing a file, update for next file's seam check
        # last_file_last_hash is already updated above


def _read_entries(path: Path) -> list[dict]:
    """Read all non-empty JSON lines from an audit log file."""
    entries = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            # Partial write — tolerate as a non-entry (chain verifier will catch via missing fields)
            pass
    return entries


def _enumerate_rotated_files_with_gap_check(audit_path: Path, rotation_dir: Path) -> list[Path]:
    """Return ordered list of rotation files, checking for contiguity gaps.

    Scans for ALL audit.log.N files in the rotation_dir (not just sequential
    from 1 up) so that gaps like "audit.log.2 present, audit.log.1 missing"
    are detected.
    """
    audit_path = Path(rotation_dir) / audit_path.name

    # Scan parent directory for all matching rotation files
    parent = Path(rotation_dir)
    base_name = audit_path.name
    found: dict[int, Path] = {}
    for candidate in parent.iterdir():
        if candidate.name.startswith(base_name + "."):
            suffix = candidate.name[len(base_name) + 1:]
            try:
                n = int(suffix)
                found[n] = candidate
            except ValueError:
                pass

    if not found:
        # No rotation files — just return current audit.log
        return [audit_path]

    max_n = max(found.keys())
    # Check contiguity: every N from 1 to max_n must exist
    for n in range(1, max_n + 1):
        if n not in found:
            raise AuditChainGapError(
                f"Missing rotation file {base_name}.{n} (gap detected: "
                f"{base_name}.{max_n} exists but {base_name}.{n} is missing). "
                f"Fix: run 'harness verify --audit' to diagnose."
            )

    # Return in oldest-first order: max_n down to 1, then current
    ordered: list[Path] = [found[n] for n in range(max_n, 0, -1)]
    ordered.append(audit_path)
    return ordered


# ---------------------------------------------------------------------------
# verify_chain
# ---------------------------------------------------------------------------

def verify_chain(
    audit_path: Path,
    *,
    rotation_dir: Optional[Path] = None,
) -> ChainVerifyResult:
    """Full chain sweep. Returns ChainVerifyResult (never raises on chain errors).

    BOM errors propagate as exceptions (exit 5).
    """
    audit_path = Path(audit_path)
    entries_walked = 0
    rotation_files_traversed = 0
    final_tip_hash: Optional[str] = None
    error: Optional[AuditChainError] = None

    try:
        for step in walk_chain(audit_path, rotation_dir=rotation_dir):
            entries_walked += 1
            if "entry_hash" in step.entry:
                final_tip_hash = step.entry["entry_hash"]
            if step.file != audit_path:
                rotation_files_traversed = max(rotation_files_traversed, 1)
    except AuditBomError:
        raise  # BOM is a hard exit-5 error, not a chain integrity failure
    except AuditChainError as exc:
        error = exc
        return ChainVerifyResult(
            ok=False,
            entries_walked=entries_walked,
            rotation_files_traversed=rotation_files_traversed,
            final_tip_hash=final_tip_hash,
            error=error,
        )

    return ChainVerifyResult(
        ok=True,
        entries_walked=entries_walked,
        rotation_files_traversed=rotation_files_traversed,
        final_tip_hash=final_tip_hash,
        error=None,
    )


__all__ = [
    "GENESIS_HASH",
    "EXIT_CHAIN_ERROR",
    "EXIT_BOM_ERROR",
    "AuditChainError",
    "AuditChainGapError",
    "AuditChainDuplicateError",
    "AuditChainTruncationError",
    "AuditChainRotationSeamError",
    "AuditChainTamperedError",
    "AuditBomError",
    "compute_entry_hash",
    "stamp_chain_fields",
    "ChainStep",
    "ChainVerifyResult",
    "walk_chain",
    "verify_chain",
]
