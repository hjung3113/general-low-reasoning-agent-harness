"""CLI bindings for `harness anchor <verb>`.

Currently exposes the admin verb ``harness anchor repair`` (design doc
§12.1, slice S00.7). Repair is TTY-only at the CLI surface (other anchor
admin verbs added later inherit the same gate).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from . import audit_anchor
from . import secret_key

ZERO_HASH = "0" * 64


def _is_tty() -> bool:
    try:
        return bool(os.isatty(sys.stdin.fileno()))
    except (AttributeError, OSError, ValueError):
        return False


def _read_install_record(repo_root: Path) -> dict[str, Any]:
    path = repo_root / ".harness" / "install-record.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _install_record_sha256(repo_root: Path) -> str:
    path = repo_root / ".harness" / "install-record.json"
    if not path.exists():
        return ZERO_HASH
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_install_id(repo_root: Path) -> str:
    record = _read_install_record(repo_root)
    install_id = record.get("install_id")
    if isinstance(install_id, str) and install_id:
        return install_id
    return str(uuid.uuid4())


def _read_audit_tail(repo_root: Path) -> tuple[str, int]:
    """Return (entry_hash, seq_global) of live audit tail.

    For S00.7 the audit chain implementation lands at S06; here we only
    read whatever JSONL entries exist under .scratch/audit.log if any.
    Returns the §22.1 boot values (zero hash, seq 0) when no audit exists
    AND ``--accept-no-audit`` is in play. The caller is responsible for
    enforcing that flag.
    """
    path = repo_root / ".scratch" / "audit.log"
    if not path.exists():
        return ZERO_HASH, 0
    last_entry: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                last_entry = json.loads(line)
            except json.JSONDecodeError:
                continue
    if not last_entry:
        return ZERO_HASH, 0
    entry_hash = last_entry.get("entry_hash") or ZERO_HASH
    seq_global = int(last_entry.get("seq_global") or 0)
    return entry_hash, seq_global


def cmd_anchor_repair(args, repo_root: Path) -> int:
    """Rebuild the audit-tip anchor from current live state.

    Exit codes:
      0  anchor written
      6  non-TTY (admin verb refused)
      9  audit tail missing and --accept-no-audit not passed
      10 anchor write failed (e.g., rollback refused)
    """
    if not _is_tty():
        sys.stderr.write(
            "harness anchor repair: non-TTY caller refused.\n"
            "Fix: run `harness anchor repair` from an interactive terminal.\n"
        )
        return 6

    try:
        secret_key.ensure_secret_key()
    except secret_key.SecretKeyError as exc:
        sys.stderr.write(f"secret key minting failed: {exc}\n")
        return 10

    entry_hash, seq_global = _read_audit_tail(repo_root)
    accept_no_audit = bool(getattr(args, "accept_no_audit", False))
    if entry_hash == ZERO_HASH and seq_global == 0 and not accept_no_audit:
        sys.stderr.write(
            "harness anchor repair: no audit tail found under .scratch/audit.log.\n"
            "Fix: pass --accept-no-audit to mint a boot anchor (S00.7 first-install path),\n"
            "or wait until at least one audit entry has been written.\n"
        )
        return 9

    install_record_sha = _install_record_sha256(repo_root)
    install_id = _resolve_install_id(repo_root)
    harness_version = os.environ.get("HARNESS_VERSION_OVERRIDE")
    if not harness_version:
        # Avoid importing the heavy version resolver from scripts.harness here;
        # ``HARNESS_VERSION`` is filled in by the caller in scripts/harness.py
        # via ``resolve_harness_version``. For test paths we accept an env var.
        harness_version = "v0.7.0.dev0"

    by_user = getattr(args, "anchor_by", None) or "unknown@local"

    try:
        anchor = audit_anchor.repair_anchor(
            repo_root,
            harness_version=harness_version,
            install_id=install_id,
            install_record_sha256=install_record_sha,
            audit_tip_entry_hash=entry_hash,
            audit_tip_seq_global=seq_global,
            by_user=by_user,
        )
    except audit_anchor.AnchorError as exc:
        sys.stderr.write(f"anchor repair failed: {exc}\n")
        return 10

    sys.stdout.write(
        f"anchor rebuilt at {audit_anchor.anchor_path(repo_root)}\n"
        f"  install_id={anchor.install_id}\n"
        f"  audit_tip_seq_global={anchor.audit_tip_seq_global}\n"
        f"  updated_at={anchor.updated_at_iso}\n"
    )
    return 0
