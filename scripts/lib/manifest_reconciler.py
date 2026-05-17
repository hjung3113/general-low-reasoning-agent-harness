"""Manifest reconciler — 3-way decision logic for installed-manifest v2 (§6).

Per §6 lines 962-968, during an upgrade the reconciler compares the on-disk
content hash against two reference hashes:

  1. ``release_installed_sha256`` — the trust root: the hash the release
     recorded at first install.
  2. ``prior_current_sha256`` — the hash recorded after the most recent
     known-good upgrade.

Decision table:
  disk == release  → UNCHANGED_SAFE_REPLACE   (file untouched since install)
  disk == prior    → UPGRADED_SAFE_REPLACE    (harness itself upgraded it; safe)
  else             → USER_MODIFIED_QUARANTINE (user edited; move to conflicts/)

Backward compat: if the prior manifest has schema_version < 2 (or absent),
``prior_current_sha256`` is treated as None for all entries and the path
falls through to the UNCHANGED_SAFE_REPLACE branch (no upgrade history →
behave like a fresh install-after-prior-install).

Hash chain:
  ``compute_manifest_hash_chain`` produces a sha256 over the canonicalized
  content of the manifest (schema_version, harness_version, sorted file
  entries, sorted removed_in_version list). Stored as top-level
  ``manifest_chain_hash`` and checked on read to detect manifest tampering.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enum + dataclass
# ---------------------------------------------------------------------------

class ReconcileDecision(Enum):
    UNCHANGED_SAFE_REPLACE = "unchanged_safe_replace"
    UPGRADED_SAFE_REPLACE = "upgraded_safe_replace"
    USER_MODIFIED_QUARANTINE = "user_modified_quarantine"


@dataclass
class ReconcileResult:
    path: str
    decision: ReconcileDecision
    quarantine_path: str | None = None
    disk_sha256: str = ""
    release_installed_sha256: str = ""
    prior_current_sha256: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sanitize_ts(now_iso: str) -> str:
    """Return a filesystem-safe timestamp (replace ':' with '-')."""
    return now_iso.replace(":", "-")


# ---------------------------------------------------------------------------
# Core reconcile_file
# ---------------------------------------------------------------------------

def reconcile_file(
    path: Path,
    *,
    release_installed_sha256: str,
    prior_current_sha256: str | None,
    repo_root: Path,
    quarantine_dir: Path,
    now_iso: str,
    classify_only: bool = False,
) -> ReconcileResult:
    """3-way decision per §6.

    Steps:
      1. If path does not exist on disk → fresh install; UNCHANGED_SAFE_REPLACE.
      2. Recompute disk sha256.
      3. disk == release_installed_sha256 → UNCHANGED_SAFE_REPLACE.
      4. prior_current_sha256 is not None and disk == prior_current_sha256
         → UPGRADED_SAFE_REPLACE.
      5. else → USER_MODIFIED_QUARANTINE; move file to
         <quarantine_dir>/<relative_path_from_repo_root>.<sanitized_ts>
         (skipped if classify_only=True — caller handles quarantine).

    Parameters
    ----------
    classify_only:
        If True, skip the file move for USER_MODIFIED_QUARANTINE decisions.
        The decision is still returned; the caller is responsible for handling
        the quarantine. Used by the upgrade flow, which has its own conflict-
        file logic — reconcile_file is used only for v2 hash classification.
    """
    base_path = str(path)

    # Step 1: file not on disk → fresh install
    if not path.exists():
        return ReconcileResult(
            path=base_path,
            decision=ReconcileDecision.UNCHANGED_SAFE_REPLACE,
            quarantine_path=None,
            disk_sha256="",
            release_installed_sha256=release_installed_sha256,
            prior_current_sha256=prior_current_sha256,
        )

    # Step 2: compute disk hash
    disk_sha = _sha256_file(path)

    # Step 3: unchanged since install
    if disk_sha == release_installed_sha256:
        return ReconcileResult(
            path=base_path,
            decision=ReconcileDecision.UNCHANGED_SAFE_REPLACE,
            quarantine_path=None,
            disk_sha256=disk_sha,
            release_installed_sha256=release_installed_sha256,
            prior_current_sha256=prior_current_sha256,
        )

    # Step 4: harness upgraded it to prior_current
    if prior_current_sha256 is not None and disk_sha == prior_current_sha256:
        return ReconcileResult(
            path=base_path,
            decision=ReconcileDecision.UPGRADED_SAFE_REPLACE,
            quarantine_path=None,
            disk_sha256=disk_sha,
            release_installed_sha256=release_installed_sha256,
            prior_current_sha256=prior_current_sha256,
        )

    # Step 5: user-modified divergence → quarantine
    try:
        rel = path.relative_to(repo_root)
        rel_str = str(rel).replace("/", "_").replace("\\", "_")
    except ValueError:
        rel_str = path.name

    ts_safe = _sanitize_ts(now_iso)
    q_name = f"{rel_str}.{ts_safe}"
    q_path = quarantine_dir / q_name

    if not classify_only:
        q_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(q_path))

    return ReconcileResult(
        path=base_path,
        decision=ReconcileDecision.USER_MODIFIED_QUARANTINE,
        quarantine_path=str(q_path) if not classify_only else None,
        disk_sha256=disk_sha,
        release_installed_sha256=release_installed_sha256,
        prior_current_sha256=prior_current_sha256,
    )


# ---------------------------------------------------------------------------
# reconcile_install — iterate all paths
# ---------------------------------------------------------------------------

def reconcile_install(
    *,
    release_manifest: dict[str, Any],
    prior_manifest: dict[str, Any] | None,
    repo_root: Path,
    now_iso: str,
    classify_only: bool = False,
) -> list[ReconcileResult]:
    """Iterate all paths in release_manifest and reconcile each.

    Backward compat: if prior_manifest has schema_version < 2 (or absent),
    treat ALL entries as prior_current_sha256=None (no upgrade history).
    This means the path falls through to UNCHANGED_SAFE_REPLACE for files
    whose content matches the release hash, or QUARANTINE for diverged files.

    Parameters
    ----------
    release_manifest:
        Release-bundled manifest dict (trust root). Must contain a ``files``
        key mapping path → {``installed_sha256``, ``current_sha256``}.
    prior_manifest:
        The repo-local manifest from the last install (.harness/installed-manifest.json).
        May be None for a fresh install.
    repo_root:
        The target repo root (used for quarantine path calculation and
        resolving relative file paths).
    now_iso:
        ISO-8601 timestamp string for quarantine filename suffix.
    classify_only:
        If True, skip file moves for USER_MODIFIED_QUARANTINE decisions.
        Used by the upgrade flow which has its own conflict-handling logic —
        reconcile_install is used only for v2 hash classification in that case.
    """
    quarantine_dir = repo_root / ".harness" / "conflicts"

    # Determine whether prior manifest has v2 upgrade history
    prior_has_v2 = False
    prior_files: dict[str, Any] = {}
    if prior_manifest is not None:
        sv = prior_manifest.get("schema_version") or prior_manifest.get("state_schema_version")
        if sv == 2:
            prior_has_v2 = True
            prior_files = prior_manifest.get("files", {})

    results: list[ReconcileResult] = []
    release_files: dict[str, Any] = release_manifest.get("files", {})

    for rel_path_str, entry in release_files.items():
        release_sha = entry.get("installed_sha256", "")
        prior_current: str | None = None
        if prior_has_v2 and rel_path_str in prior_files:
            prior_current = prior_files[rel_path_str].get("current_sha256")

        disk_path = repo_root / rel_path_str

        result = reconcile_file(
            disk_path,
            release_installed_sha256=release_sha,
            prior_current_sha256=prior_current,
            repo_root=repo_root,
            quarantine_dir=quarantine_dir,
            now_iso=now_iso,
            classify_only=classify_only,
        )
        # Normalize the path key to the relative string (not absolute)
        results.append(ReconcileResult(
            path=rel_path_str,
            decision=result.decision,
            quarantine_path=result.quarantine_path,
            disk_sha256=result.disk_sha256,
            release_installed_sha256=result.release_installed_sha256,
            prior_current_sha256=result.prior_current_sha256,
        ))

    return results


# ---------------------------------------------------------------------------
# compute_manifest_hash_chain
# ---------------------------------------------------------------------------

def compute_manifest_hash_chain(manifest: dict[str, Any]) -> str:
    """Compute a deterministic chain hash for the manifest (§6 manifest hash chain).

    The chain covers:
    - schema_version (int)
    - harness_version (str)
    - sorted file entries by path: for each entry, path + sorted(entry items)
    - sorted removed_in_version entries by path

    Returns a 64-char lowercase sha256 hex string. Stored as top-level
    ``manifest_chain_hash`` and checked on read to detect tampering.

    Stability guarantee: independent of dict insertion order (sorts all keys).
    """
    schema_version = manifest.get("schema_version", 0)
    harness_version = manifest.get("harness_version", "")
    files: dict[str, Any] = manifest.get("files", {})
    removed: list[Any] = manifest.get("removed_in_version", [])

    # Canonical representation: stable across insertion order
    chain_parts: list[str] = [
        f"schema_version={schema_version}",
        f"harness_version={harness_version}",
    ]

    for file_path in sorted(files.keys()):
        entry = files[file_path]
        entry_repr = json.dumps({k: entry[k] for k in sorted(entry.keys())}, sort_keys=True)
        chain_parts.append(f"file:{file_path}:{entry_repr}")

    for removed_entry in sorted(removed, key=lambda e: e.get("path", "")):
        removed_repr = json.dumps({k: removed_entry[k] for k in sorted(removed_entry.keys())}, sort_keys=True)
        chain_parts.append(f"removed:{removed_repr}")

    canonical = "\n".join(chain_parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# verify_install_record_integrity (stub — anchor integration deferred to S14)
# ---------------------------------------------------------------------------

def verify_install_record_integrity(
    repo_root: Path,
    anchor: object,
) -> None:
    """Verify that the install-record has not been mutated post-install.

    TODO (S14 sweep): Wire to the §12.1 anchor's ``install_record_sha256``
    field (written by anchor_cli.py). The anchor is already writing this
    field as of S00.7; this stub gates the full integrity check until the
    anchor-integration test suite is in place.

    When implemented, this function should:
    1. Read .harness/install-record.json.
    2. Reject BOM (exit 5) per §2.4.
    3. Compute sha256 of the canonical bytes.
    4. Compare against anchor.install_record_sha256.
    5. Raise SystemExit(6) on mismatch (install_record_mutated_post_install).

    For now: raises NotImplementedError to signal caller to skip anchor check.
    """
    raise NotImplementedError(
        "verify_install_record_integrity: anchor integration deferred to S14. "
        "See TODO above and §12.1 anchor spec."
    )


__all__ = [
    "ReconcileDecision",
    "ReconcileResult",
    "reconcile_file",
    "reconcile_install",
    "compute_manifest_hash_chain",
    "verify_install_record_integrity",
]
