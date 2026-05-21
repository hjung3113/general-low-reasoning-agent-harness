"""Per-entry hash chain for audit logs (design §2.2, §2.3, §2.5).

Implements the per-entry hash chain (B) from ADR D-3:
  entry_hash = sha256(rfc8785.dumps({k:v for k,v in e.items()
                                      if k not in ("entry_hash","previous_entry_hash")})
                      + previous_entry_hash.encode())

Canonicalization uses rfc8785 (RFC 8785 — JSON Canonicalization Scheme).
Both `entry_hash` and `previous_entry_hash` are EXCLUDED from the canonical
dict; `previous_entry_hash` is then concatenated as raw bytes after the
canonical JSON. This matches design §2.2 line 109 + line 116 + ADR D-3 pin.

First-ever entry uses previous_entry_hash = GENESIS_HASH ("0" * 64).

Design refs: §2.2, §2.3, §2.4, §2.5, §3.4, §12.5 #1, §12.9
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Iterator, Mapping, Optional

try:
    import rfc8785
except ImportError as _rfc8785_exc:  # pragma: no cover - environment-dependent
    # v0.7.1 P0 fix: see phase_lock.py for rationale.
    raise SystemExit(
        "harness: missing runtime dependency 'rfc8785' "
        f"({_rfc8785_exc.__class__.__name__}: {_rfc8785_exc}).\n"
        "Install harness runtime dependencies before invoking phase/audit commands:\n"
        "    python3 -m pip install -e .\n"
        "  (or, minimal:  python3 -m pip install psutil rfc8785)\n"
        "Source-checkout users: pyproject.toml lists runtime deps; the source\n"
        "harness is not dependency-free. See README §Install."
    ) from _rfc8785_exc


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

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = EXIT_CHAIN_ERROR,
        sub_reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.sub_reason = sub_reason


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

_HASH_EXCLUDED_FIELDS = frozenset({
    "entry_hash",
    "previous_entry_hash",
    # next_file_seed_previous_entry_hash is a forward-pointer set AFTER
    # entry_hash is computed; excluding it keeps the seam entry verifiable
    # without a circular dependency.
    "next_file_seed_previous_entry_hash",
})


def compute_entry_hash(entry_dict: Mapping) -> str:
    """Compute sha256 per the ADR D-3 pin (§2.2 line 109 + line 116).

    Formula:
        entry_hash = sha256(rfc8785.dumps(entry_minus_excluded_fields)
                            + previous_entry_hash.encode())

    Excluded fields: ``entry_hash``, ``previous_entry_hash``,
    ``next_file_seed_previous_entry_hash`` (forward-pointer metadata on
    rotation seam entries; set after entry_hash is finalized).

    ``previous_entry_hash`` is concatenated as raw UTF-8 bytes after the
    canonical JSON so it links the chain without being part of the
    canonicalized object (avoiding self-reference and length-extension
    ambiguity).

    If ``previous_entry_hash`` is absent in *entry_dict* (legacy v1 entry
    being hashed inline), GENESIS_HASH is used as the tail concatenation.
    """
    prev = entry_dict.get("previous_entry_hash", GENESIS_HASH)
    d = {k: v for k, v in entry_dict.items() if k not in _HASH_EXCLUDED_FIELDS}
    canonical = _canonical_bytes(d)
    return hashlib.sha256(canonical + prev.encode()).hexdigest()


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
    final_after_sha256: Optional[str]  # last entry's after_sha256 (state file sha256)
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
      - AuditChainTamperedError (exit 10): entry_hash mismatch (incl. v1 after v2)
      - AuditChainRotationSeamError (exit 10): rotation seam hash mismatch or
          missing audit.rotated seam entry at rotation boundary
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
    # P1-2: forward-only migration — once a v2 entry is seen, subsequent v1
    # entries are rejected as a v1_after_v2_downgrade (downgrade backdoor).
    chain_started: bool = False

    for file_idx, file_path in enumerate(files):
        _check_bom(file_path)

        if not file_path.exists() or file_path.stat().st_size == 0:
            continue

        is_first_file = (file_idx == 0)
        file_entries = _read_entries(file_path)

        # P1-3: At the start of each non-first file, check that the previous
        # file ended with an audit.rotated seam entry IF that prior file
        # contained any v2 entries.  A v1-only prior file is exempt (legacy).
        if not is_first_file and last_file_last_hash is not None and chain_started:
            # Verify seam: the previous file must have ended with verb=audit.rotated
            prev_file = files[file_idx - 1]
            if prev_file.exists() and prev_file.stat().st_size > 0:
                prev_entries = _read_entries(prev_file)
                # Find the last non-empty entry
                last_prev_entry = None
                for pe in reversed(prev_entries):
                    if pe:
                        last_prev_entry = pe
                        break
                if (last_prev_entry is None
                        or last_prev_entry.get("verb") != "audit.rotated"):
                    raise AuditChainRotationSeamError(
                        f"Rotation seam missing in {prev_file}: "
                        f"last entry verb is not 'audit.rotated'. "
                        f"Expected last entry of rotated-out file to carry "
                        f"verb=audit.rotated and next_file_seed_previous_entry_hash. "
                        f"Fix: this rotation was performed without seam emission; "
                        f"run 'harness verify --audit --fixture <dir>' to diagnose."
                    )
                # Verify the new file's first entry chains from the seam seed
                seed_hash = last_prev_entry.get("next_file_seed_previous_entry_hash")
                if seed_hash is not None and file_entries:
                    first_v2 = next(
                        (e for e in file_entries
                         if e.get("schema_version", 1) >= 2 and "entry_hash" in e),
                        None,
                    )
                    if first_v2 is not None:
                        first_prev = first_v2.get("previous_entry_hash")
                        if first_prev is not None and first_prev != seed_hash:
                            raise AuditChainRotationSeamError(
                                f"Rotation seam seed mismatch in {file_path}: "
                                f"first entry previous_entry_hash={first_prev!r} "
                                f"does not match seam seed={seed_hash!r} from {prev_file}. "
                                f"Fix: run 'harness verify --audit --fixture <dir>'."
                            )

        for entry_idx, entry in enumerate(file_entries):
            # P1-2: reject v1 entries once the chain has seen any v2 entry
            schema = entry.get("schema_version", 1)
            if schema < 2 or "entry_hash" not in entry:
                if chain_started:
                    # v1 entry after v2 seen — downgrade backdoor
                    raise AuditChainTamperedError(
                        f"v1 entry after v2 entry detected at "
                        f"file={file_path}, entry_idx={entry_idx}. "
                        f"Forward-only migration: once v2 is seen all subsequent "
                        f"entries must be v2 (sub_reason=v1_after_v2_downgrade). "
                        f"Fix: run 'harness verify --audit --fixture <dir>'.",
                        sub_reason="v1_after_v2_downgrade",
                    )
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

            # This is a v2 entry — mark chain as started
            chain_started = True

            # Check rotation seam for the current-file first-entry (legacy path,
            # kept for files without explicit audit.rotated): first v2 entry in
            # a non-first file must chain to last_file_last_hash.
            if not is_first_file and entry_idx == 0 and last_file_last_hash is not None:
                entry_prev = entry.get("previous_entry_hash")
                if entry_prev is not None and entry_prev != last_file_last_hash:
                    raise AuditChainRotationSeamError(
                        f"Rotation seam hash mismatch in {file_path} at entry 0: "
                        f"expected previous_entry_hash={last_file_last_hash!r} "
                        f"but got {entry_prev!r}. "
                        f"Fix: run 'harness verify --audit --fixture <dir>' to diagnose."
                    )

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

            # Verify entry_hash (entry_for_hash retains previous_entry_hash so
            # compute_entry_hash can read it for the tail concatenation)
            entry_for_hash = {k: v for k, v in entry.items() if k != "entry_hash"}
            computed = compute_entry_hash(entry_for_hash)
            stored = entry["entry_hash"]
            if computed != stored:
                raise AuditChainTamperedError(
                    f"entry_hash mismatch at seq_global={sg} in {file_path}: "
                    f"stored={stored!r}, computed={computed!r}. "
                    f"Fix: run 'harness verify --audit --fixture {file_path.parent}'."
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
                        f"Fix: run 'harness verify --audit --fixture {file_path.parent}'."
                    )

            prev_hash = stored
            last_file_last_hash = stored

            yield ChainStep(
                entry=entry,
                seq_global=sg,
                file=file_path,
            )

        # After processing a file, last_file_last_hash is updated above


def _read_entries(path: Path) -> list[dict]:
    """Read all non-empty JSON lines from an audit log file.

    Raises AuditChainTruncationError (exit 10) if the LAST non-empty line
    cannot be parsed as JSON — this indicates a partial write / corrupt tail
    (§2.5 row 3, P1-5).  Interior malformed lines are tolerated (unlikely
    but not harmful — they will fail entry_hash verification and surface as
    AuditChainTamperedError during the walk).
    """
    entries = []
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    non_empty_lines = [ln for ln in lines if ln]

    for i, line in enumerate(non_empty_lines):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            is_last = (i == len(non_empty_lines) - 1)
            if is_last:
                raise AuditChainTruncationError(
                    f"Partial JSON tail in {path}: last non-empty line is not "
                    f"valid JSON (likely a partial write). "
                    f"Fix: truncate the incomplete line with "
                    f"'harness verify --audit --repair-tail'."
                )
            # Interior malformed line — tolerate (will fail hash check in walk)
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
    final_after_sha256: Optional[str] = None
    error: Optional[AuditChainError] = None

    try:
        for step in walk_chain(audit_path, rotation_dir=rotation_dir):
            entries_walked += 1
            if "entry_hash" in step.entry:
                final_tip_hash = step.entry["entry_hash"]
            if "after_sha256" in step.entry:
                final_after_sha256 = step.entry["after_sha256"]
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
            final_after_sha256=final_after_sha256,
            error=error,
        )

    return ChainVerifyResult(
        ok=True,
        entries_walked=entries_walked,
        rotation_files_traversed=rotation_files_traversed,
        final_tip_hash=final_tip_hash,
        final_after_sha256=final_after_sha256,
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
