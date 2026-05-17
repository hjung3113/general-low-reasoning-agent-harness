"""Out-of-repo audit-tip anchor.

Design baseline: ``docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md``
§12.1 + §2.6 + §3.8 + ADR 2026-05-17-audit-canonicalization-locking-and-state-trust D-7.

The anchor closes the audit-replay forgery hole: per-entry hash chain only
detects accidental tampering, but a repo-local attacker can rewrite every
entry of ``audit.log`` and recompute every ``entry_hash``. An audit tip
recorded outside the repo (in the user's home dir) is the defense.

Storage:

  - POSIX: ``~/.harness/audit-tip/<repo-id>.json`` (mode 0o600)
  - Windows: ``%LOCALAPPDATA%/Harness/audit-tip/<repo-id>.json``

``<repo-id> = sha256(canonical_absolute_path_of_repo_root)[:16]``. The full
canonical path is recorded inside the anchor body so cross-repo replay is
detectable.

Schema (anchor_schema_version=1):

    {
      "anchor_schema_version": 1,
      "repo_root_canonical": "...",
      "harness_version": "v0.7.0",
      "install_id": "<uuid4>",
      "install_record_sha256": "<sha256 of canonical install-record.json bytes>",
      "audit_tip_entry_hash": "<latest entry_hash of audit.log tail>",
      "audit_tip_seq_global": 1234,
      "updated_at_iso": "2026-05-17T03:14:15Z",
      "anchor_signature": "<HMAC-SHA256 over all-above-fields, keyed by ~/.harness/secret.key>"
    }

Monotonic guard: ``~/.harness/audit-tip/.seen.json`` caches the largest
``audit_tip_seq_global`` ever observed per ``<repo-id>``. An anchor whose
``audit_tip_seq_global`` is less than the cached value is rejected as a
rollback attempt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import secret_key as _secret_key
from .secret_key import _fsync_parent_dir  # shared cross-module helper

ANCHOR_SCHEMA_VERSION = 1

SIGNED_FIELDS = (
    "anchor_schema_version",
    "repo_root_canonical",
    "harness_version",
    "install_id",
    "install_record_sha256",
    "audit_tip_entry_hash",
    "audit_tip_seq_global",
    "updated_at_iso",
)


class AnchorError(RuntimeError):
    """Raised when an anchor cannot be loaded, verified, or written."""

    def __init__(self, message: str, *, sub_reason: str | None = None) -> None:
        super().__init__(message)
        self.sub_reason = sub_reason


class AnchorMissingError(AnchorError):
    """Subclass — the anchor file does not exist on disk. Surfaced by
    `verify_existing_anchor_for_repo` so callers can route to the
    `harness anchor repair` remediation path. Distinct from
    `AnchorMismatchError` so per-error exit-code mapping is clean."""


class AnchorMismatchError(AnchorError):
    """Subclass — anchor present but does not verify against live state
    (signature invalid, audit-tail diverged, install-record mutated, or
    rollback refused). Surfaced by `verify_existing_anchor_for_repo`."""


@dataclass(frozen=True)
class Anchor:
    anchor_schema_version: int
    repo_root_canonical: str
    harness_version: str
    install_id: str
    install_record_sha256: str
    audit_tip_entry_hash: str
    audit_tip_seq_global: int
    updated_at_iso: str
    anchor_signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_schema_version": self.anchor_schema_version,
            "repo_root_canonical": self.repo_root_canonical,
            "harness_version": self.harness_version,
            "install_id": self.install_id,
            "install_record_sha256": self.install_record_sha256,
            "audit_tip_entry_hash": self.audit_tip_entry_hash,
            "audit_tip_seq_global": self.audit_tip_seq_global,
            "updated_at_iso": self.updated_at_iso,
            "anchor_signature": self.anchor_signature,
        }


def anchor_dir() -> Path:
    return _secret_key.home_dir() / "audit-tip"


def seen_path() -> Path:
    return anchor_dir() / ".seen.json"


def repo_id(repo_root: Path) -> str:
    canonical = str(repo_root.resolve())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def anchor_path(repo_root: Path) -> Path:
    return anchor_dir() / f"{repo_id(repo_root)}.json"


def _canonical_signed_payload(fields: dict[str, Any]) -> bytes:
    """Return the canonical bytes that the HMAC signs.

    NOTE: This is intentionally a minimal stable JSON encoding (sorted keys,
    no whitespace) limited to the SIGNED_FIELDS set. The repo-wide RFC 8785
    canonicalizer landed at S01 will replace this; the anchor schema bumps
    to version 2 at that point. For S00.7 the goal is a stable signature
    that round-trips identically across platforms.
    """
    payload = {k: fields[k] for k in SIGNED_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(fields: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_signed_payload(fields), hashlib.sha256).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_anchor(
    repo_root: Path,
    *,
    harness_version: str,
    install_id: str,
    install_record_sha256: str,
    audit_tip_entry_hash: str,
    audit_tip_seq_global: int,
    key: bytes | None = None,
) -> Anchor:
    """Write a fresh anchor for *repo_root*.

    Caller MUST ensure *audit_tip_seq_global* is strictly greater than any
    previously written anchor's seq_global. ``write_anchor`` enforces this
    against ``.seen.json`` and refuses rollbacks.
    """
    if key is None:
        key = _secret_key.load_secret_key()

    path = anchor_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass

    last_seen = _read_seen().get(repo_id(repo_root), 0)
    if audit_tip_seq_global < last_seen:
        raise AnchorError(
            f"audit_tip_seq_global={audit_tip_seq_global} < last seen "
            f"{last_seen}; refusing to write rollback anchor.",
            sub_reason="anchor_rollback_refused",
        )

    fields = {
        "anchor_schema_version": ANCHOR_SCHEMA_VERSION,
        "repo_root_canonical": str(repo_root.resolve()),
        "harness_version": harness_version,
        "install_id": install_id,
        "install_record_sha256": install_record_sha256,
        "audit_tip_entry_hash": audit_tip_entry_hash,
        "audit_tip_seq_global": audit_tip_seq_global,
        "updated_at_iso": _now_iso(),
    }
    signature = _sign(fields, key)
    fields["anchor_signature"] = signature

    body = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    # Unique tmp filename guards against two simultaneous anchor writers
    # racing on the same path.
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        if os.name == "nt":  # pragma: no cover - Windows row tested at S13
            tmp.write_text(body, encoding="utf-8", newline="\n")
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = os.open(str(tmp), flags, 0o600)
            try:
                os.write(fd, body.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        os.replace(tmp, path)
        _fsync_parent_dir(path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

    if os.name != "nt":
        os.chmod(path, 0o600)

    _bump_seen(repo_root, audit_tip_seq_global)

    return Anchor(**fields)


def read_anchor(repo_root: Path) -> Anchor:
    """Load the anchor for *repo_root*. Does NOT verify signature."""
    path = anchor_path(repo_root)
    if not path.exists():
        raise AnchorError(
            f"anchor not found at {path}",
            sub_reason="anchor_missing",
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnchorError(
            f"anchor at {path} is unreadable: {exc}",
            sub_reason="anchor_unreadable",
        ) from exc
    try:
        return Anchor(**raw)
    except TypeError as exc:
        raise AnchorError(
            f"anchor at {path} schema mismatch: {exc}",
            sub_reason="anchor_schema_mismatch",
        ) from exc


def verify_anchor(
    anchor: Anchor,
    *,
    audit_tip_entry_hash: str,
    audit_tip_seq_global: int,
    install_record_sha256: str,
    repo_root: Path,
    key: bytes | None = None,
) -> None:
    """Verify *anchor* against live state.

    Raises:
        AnchorError with a sub_reason matching the §2.6 / §3.8 exit-code
        sub-reason taxonomy:

          * ``anchor_signature_invalid``
          * ``audit_tail_diverged_from_anchor``
          * ``install_record_mutated_post_install``
          * ``anchor_rollback_refused``
          * ``anchor_repo_root_mismatch``
          * ``anchor_schema_version_unsupported``
    """
    if anchor.anchor_schema_version != ANCHOR_SCHEMA_VERSION:
        raise AnchorError(
            f"anchor_schema_version={anchor.anchor_schema_version}; "
            f"expected {ANCHOR_SCHEMA_VERSION}.",
            sub_reason="anchor_schema_version_unsupported",
        )

    expected_repo_canonical = str(repo_root.resolve())
    if anchor.repo_root_canonical != expected_repo_canonical:
        raise AnchorError(
            f"anchor.repo_root_canonical={anchor.repo_root_canonical!r} != "
            f"{expected_repo_canonical!r}; cross-repo replay refused.",
            sub_reason="anchor_repo_root_mismatch",
        )

    if key is None:
        key = _secret_key.load_secret_key()

    expected_sig = _sign(anchor.to_dict(), key)
    if not hmac.compare_digest(expected_sig, anchor.anchor_signature):
        raise AnchorError(
            "anchor signature does not verify against ~/.harness/secret.key.",
            sub_reason="anchor_signature_invalid",
        )

    if anchor.audit_tip_entry_hash != audit_tip_entry_hash:
        raise AnchorError(
            f"audit_tail diverged from anchor: "
            f"anchor.audit_tip_entry_hash={anchor.audit_tip_entry_hash}, "
            f"live={audit_tip_entry_hash}.",
            sub_reason="audit_tail_diverged_from_anchor",
        )

    if anchor.audit_tip_seq_global != audit_tip_seq_global:
        raise AnchorError(
            f"audit_tip_seq_global mismatch: anchor={anchor.audit_tip_seq_global}, "
            f"live={audit_tip_seq_global}.",
            sub_reason="audit_tail_diverged_from_anchor",
        )

    if anchor.install_record_sha256 != install_record_sha256:
        raise AnchorError(
            "install-record.json hash changed post-install: "
            f"anchor={anchor.install_record_sha256}, live={install_record_sha256}.",
            sub_reason="install_record_mutated_post_install",
        )

    last_seen = _read_seen().get(repo_id(repo_root), 0)
    if anchor.audit_tip_seq_global < last_seen:
        raise AnchorError(
            f"anchor.audit_tip_seq_global={anchor.audit_tip_seq_global} < "
            f"largest previously observed {last_seen}; rollback refused.",
            sub_reason="anchor_rollback_refused",
        )


def _read_seen() -> dict[str, int]:
    path = seen_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _bump_seen(repo_root: Path, seq_global: int) -> None:
    path = seen_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = _read_seen()
    rid = repo_id(repo_root)
    if seen.get(rid, 0) < seq_global:
        seen[rid] = seq_global
        body = json.dumps(seen, sort_keys=True, separators=(",", ":"))
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
        try:
            if os.name == "nt":  # pragma: no cover
                tmp.write_text(body, encoding="utf-8", newline="\n")
            else:
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.write(fd, body.encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.replace(tmp, path)
            _fsync_parent_dir(path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def reset_seen_for_testing() -> None:
    """Test-only hook: clears ``.seen.json`` rollback cache."""
    path = seen_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


_ZERO_HASH = "0" * 64


def _live_audit_tail(repo_root: Path) -> tuple[str, int]:
    """Return `(entry_hash, seq_global)` of the last well-formed audit
    entry under `<repo_root>/.scratch/audit.log`. Returns
    `(_ZERO_HASH, 0)` if the file is absent or empty.

    NOTE: audit entries do not yet carry `entry_hash` / `seq_global`
    fields in v0.7 (the hash chain lands at S06). Until then this helper
    returns whatever the tail entry exposes (or zero defaults), and
    anchor verification still chains via `install_record_sha256` +
    `repo_root_canonical` + HMAC signature. The strict
    audit_tail_entry_hash equality check will start biting once S06
    writes those fields.
    """
    path = repo_root / ".scratch" / "audit.log"
    if not path.exists():
        return _ZERO_HASH, 0
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _ZERO_HASH, 0
    last = None
    for line in reversed(raw.splitlines()):
        if not line.strip():
            continue
        try:
            last = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not last:
        return _ZERO_HASH, 0
    entry_hash = last.get("entry_hash") or _ZERO_HASH
    try:
        seq_global = int(last.get("seq_global") or 0)
    except (TypeError, ValueError):
        seq_global = 0
    return entry_hash, seq_global


def _live_install_record_sha256(repo_root: Path) -> str:
    path = repo_root / ".harness" / "install-record.json"
    if not path.exists():
        return _ZERO_HASH
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_existing_anchor_for_repo(repo_root: Path) -> Anchor:
    """High-level §12.1 trust-chain entry point used by callers (e.g.
    `phase_approve.run_approve`) that need to chain through the
    out-of-repo anchor BEFORE trusting `.scratch/audit.log`.

    Steps:
      1. Locate the anchor file via `anchor_path(repo_root)`.
         Missing → raise `AnchorMissingError` (sub_reason="anchor_missing").
      2. Load + parse it via `read_anchor` (re-raises `AnchorError`
         subclasses on schema mismatch / unreadable).
      3. Compute live `install_record_sha256` from
         `<repo>/.harness/install-record.json`.
      4. Compute live `audit_tip_entry_hash` / `audit_tip_seq_global`
         from the tail of `<repo>/.scratch/audit.log` (see
         `_live_audit_tail` note about S06 hash-chain wiring).
      5. Call `verify_anchor(...)`. On any verification failure,
         re-raise as `AnchorMismatchError` preserving `sub_reason` so
         the caller's exit-code mapping is straightforward.

    Returns the verified `Anchor` on success.

    Raises:
        AnchorMissingError      -- anchor file absent
        AnchorMismatchError     -- anchor present but verification failed
        AnchorError             -- other unrecoverable anchor faults (e.g.
                                   unreadable, schema mismatch — surfaced
                                   directly by `read_anchor`).
    """
    repo_root = Path(repo_root)
    path = anchor_path(repo_root)
    if not path.exists():
        raise AnchorMissingError(
            f"anchor not found at {path}. "
            f"Fix: run `harness anchor repair` from a TTY to mint the "
            f"out-of-repo audit-tip anchor (see design §12.1).",
            sub_reason="anchor_missing",
        )
    anchor = read_anchor(repo_root)

    install_record_sha = _live_install_record_sha256(repo_root)
    audit_tip_hash, audit_tip_seq = _live_audit_tail(repo_root)
    try:
        verify_anchor(
            anchor,
            audit_tip_entry_hash=audit_tip_hash,
            audit_tip_seq_global=audit_tip_seq,
            install_record_sha256=install_record_sha,
            repo_root=repo_root,
        )
    except AnchorError as exc:
        # Re-raise as the typed mismatch subclass so callers can route
        # mismatch failures to a distinct exit code from "missing".
        # Preserve the original sub_reason for forensic taxonomy.
        raise AnchorMismatchError(str(exc), sub_reason=exc.sub_reason) from exc
    return anchor


def repair_anchor(
    repo_root: Path,
    *,
    harness_version: str,
    install_id: str,
    install_record_sha256: str,
    audit_tip_entry_hash: str,
    audit_tip_seq_global: int,
    by_user: str,
) -> Anchor:
    """Rebuild the anchor from current live state.

    Implements the ``harness anchor repair`` admin verb (TTY-only at the
    CLI layer; library function itself does not enforce TTY). Idempotent:
    a fresh repair with the same live state writes a new anchor whose
    signature differs only in ``updated_at_iso``.

    *by_user* is recorded in the (future) audit entry that wraps this call.
    """
    return write_anchor(
        repo_root,
        harness_version=harness_version,
        install_id=install_id,
        install_record_sha256=install_record_sha256,
        audit_tip_entry_hash=audit_tip_entry_hash,
        audit_tip_seq_global=audit_tip_seq_global,
    )
