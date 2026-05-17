"""Manifest v2 schema: read/write helpers for installed-manifest.json (§6).

Schema additions over v1 (state_schema_version=2):
- Top-level ``schema_version: 2``
- Top-level ``harness_version`` — e.g. "v0.7.0"
- Per-entry ``installed_sha256`` — content hash at install time (trust root)
- Per-entry ``current_sha256`` — content hash at last-known-good upgrade
- Top-level ``installed_files_chain_hash`` — deterministic self-verifier (see
  manifest_reconciler.compute_manifest_hash_chain)

Backward compat: callers that read schema_version < 2 (or absent) receive a
SystemExit with a clear message so they can upgrade or fall back to fresh-
install-after-prior-install mode.

CRLF→LF normalization (§2.3): CRLF in the on-disk JSON is silently
canonicalized to LF before parsing.
BOM rejection (§2.4): UTF-8 BOM is a hard exit 5.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION: int = 2

#: UTF-8 BOM bytes (§2.4 — forbidden in all managed JSON files).
_BOM = b"\xef\xbb\xbf"

#: Exit code for BOM / CRLF / parse errors (§2.4, §exitcodes.EXIT_UNPARSEABLE_JSON).
_EXIT_PARSE_ERROR = 5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_manifest(manifest: dict[str, Any], *, path: Path) -> None:
    """Write *manifest* to *path* as canonical installed-manifest v2 JSON.

    Stamps ``schema_version: 2`` unconditionally. Output is:
    - sorted-keys JSON (§2.3 Round-2 BLOCK fix)
    - LF line endings (no CRLF, no BOM)
    - trailing newline

    Creates parent directories as needed.
    """
    payload = dict(manifest)
    payload["schema_version"] = MANIFEST_SCHEMA_VERSION
    canonical = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    # Enforce LF line endings regardless of platform
    canonical_lf = canonical.replace("\r\n", "\n").replace("\r", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_lf.encode("utf-8"))


def read_manifest(path: Path) -> dict[str, Any]:
    """Read and validate an installed-manifest v2 JSON file.

    Validation steps (in order):
    1. Reject UTF-8 BOM → exit 5 (§2.4)
    2. Canonicalize CRLF→LF (§2.3 Windows compat)
    3. Parse JSON — exit 5 on parse failure
    4. Reject schema_version != 2 → SystemExit with clear message

    Returns the parsed dict on success.
    """
    raw: bytes = path.read_bytes()

    # Step 1: BOM check (§2.4)
    if raw.startswith(_BOM):
        raise SystemExit(
            _EXIT_PARSE_ERROR  # exit code 5
            # SystemExit with an int code; message is logged by caller
        )

    # Step 2: CRLF → LF normalization (§2.3)
    text = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")

    # Step 3: JSON parse
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        import sys as _sys
        _sys.stderr.write(f"installed-manifest parse error (exit 5): {exc}\n")
        raise SystemExit(_EXIT_PARSE_ERROR) from exc

    # Step 4: schema_version check
    sv = data.get("schema_version")
    if sv != MANIFEST_SCHEMA_VERSION:
        import sys as _sys
        _sys.stderr.write(
            f"installed-manifest schema_version must be {MANIFEST_SCHEMA_VERSION}, "
            f"got {sv!r}. Run 'harness install' to upgrade.\n"
        )
        raise SystemExit(
            f"installed-manifest schema_version must be {MANIFEST_SCHEMA_VERSION}, "
            f"got {sv!r}. Run 'harness install' to upgrade."
        )

    return data


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "write_manifest",
    "read_manifest",
]
