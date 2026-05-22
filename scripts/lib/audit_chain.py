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

Design refs: §2.2, §2.3, §2.5
Phase 2 Item 5: verify/walk path removed.
"""
from __future__ import annotations

import hashlib
from typing import Mapping, Optional

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


__all__ = [
    "GENESIS_HASH",
    "compute_entry_hash",
    "stamp_chain_fields",
]
