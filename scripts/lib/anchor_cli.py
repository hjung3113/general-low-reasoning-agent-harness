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


class AuditTailParseError(RuntimeError):
    """Live audit tail's last record failed JSON parse — exit 14
    `audit_partial_write` (§3.8 row 12). Caller MUST NOT fall back to an
    earlier entry; that would silently anchor a stale tail."""


class InstallRecordUnreadable(RuntimeError):
    """install-record.json is present but cannot be parsed; refuses to mint
    an install_id from thin air."""


def _is_tty() -> bool:
    try:
        return bool(os.isatty(sys.stdin.fileno()))
    except (AttributeError, OSError, ValueError):
        return False


def _read_install_record(repo_root: Path) -> dict[str, Any] | None:
    """Return the parsed install-record.json, or None if absent.

    Raises:
        InstallRecordUnreadable: file exists but is not valid UTF-8 / JSON.
    """
    path = repo_root / ".harness" / "install-record.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallRecordUnreadable(
            f"{path}: not valid UTF-8/JSON ({exc})"
        ) from exc


def _install_record_sha256(repo_root: Path) -> str:
    path = repo_root / ".harness" / "install-record.json"
    if not path.exists():
        return ZERO_HASH
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_install_id(
    repo_root: Path,
    *,
    accept_no_install_record: bool,
) -> str:
    """Resolve install_id.

    Order:
      1. ``install-record.json`` exists and parses → use its ``install_id``.
      2. File absent or ``install_id`` missing AND
         ``accept_no_install_record`` is True → mint a fresh UUID (boot path
         only).
      3. Otherwise raise.

    The "mint fresh UUID" path is intentionally gated. Allowing repair to
    invent an ``install_id`` on every run would let an attacker who deleted
    install-record.json reset the anchor's install_id field and silently
    re-bind it. The bootstrap flag makes the trade-off explicit.
    """
    try:
        record = _read_install_record(repo_root)
    except InstallRecordUnreadable:
        raise

    if record is not None:
        install_id = record.get("install_id")
        if isinstance(install_id, str) and install_id:
            return install_id
        if not accept_no_install_record:
            raise InstallRecordUnreadable(
                ".harness/install-record.json is present but its install_id "
                "field is missing or not a string."
            )
        return str(uuid.uuid4())

    if not accept_no_install_record:
        raise InstallRecordUnreadable(
            ".harness/install-record.json is absent. Pass "
            "--accept-no-install-record to mint a boot anchor without it "
            "(S00.7 first-install path)."
        )
    return str(uuid.uuid4())


def _read_audit_tail(repo_root: Path) -> tuple[str, int]:
    """Return (entry_hash, seq_global) of live audit tail.

    Returns (ZERO_HASH, 0) when no audit file exists OR the file is empty
    (truly no audit). The caller decides whether that is acceptable via
    ``--accept-no-audit``.

    Raises:
        AuditTailParseError: the file exists, has content, but its LAST
            non-empty line fails JSON parse. Per §3.8 row 12 this is
            ``audit_partial_write`` — exit 14 — and must NOT silently fall
            back to a prior entry. Anchoring a stale "previous" tail after
            the current tip has been torn would erase the rolled-back
            entry from the chain.
    """
    path = repo_root / ".scratch" / "audit.log"
    if not path.exists():
        return ZERO_HASH, 0
    raw_lines: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line:
                raw_lines.append(line)
    if not raw_lines:
        return ZERO_HASH, 0
    last_line = raw_lines[-1]
    try:
        last_entry = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise AuditTailParseError(
            f"last audit entry in {path} failed JSON parse: {exc}"
        ) from exc
    entry_hash = last_entry.get("entry_hash") or ZERO_HASH
    seq_global = int(last_entry.get("seq_global") or 0)
    return entry_hash, seq_global


def cmd_anchor_repair(args, repo_root: Path) -> int:
    """Rebuild the audit-tip anchor from current live state.

    Exit codes:
      0   anchor written
      6   non-TTY (admin verb refused)
      9   audit tail missing AND --accept-no-audit not passed, OR
          install-record absent / install_id missing AND
          --accept-no-install-record not passed
      10  anchor write failed (e.g., rollback refused) OR secret key error
      14  audit_partial_write (last audit entry failed JSON parse —
          §3.8 row 12). Caller must run `harness verify --audit
          --repair-tail` (S06) before retrying anchor repair.
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

    try:
        entry_hash, seq_global = _read_audit_tail(repo_root)
    except AuditTailParseError as exc:
        sys.stderr.write(
            f"audit_partial_write: {exc}\n"
            "Fix: run `harness verify --audit --repair-tail` (lands S06) to "
            "truncate to the last verifiable entry, then retry anchor repair.\n"
        )
        return 14

    accept_no_audit = bool(getattr(args, "accept_no_audit", False))
    if entry_hash == ZERO_HASH and seq_global == 0 and not accept_no_audit:
        sys.stderr.write(
            "harness anchor repair: no audit tail found under .scratch/audit.log.\n"
            "Fix: pass --accept-no-audit to mint a boot anchor (S00.7 first-install path),\n"
            "or wait until at least one audit entry has been written.\n"
        )
        return 9

    accept_no_install_record = bool(getattr(args, "accept_no_install_record", False))
    install_record_sha = _install_record_sha256(repo_root)
    try:
        install_id = _resolve_install_id(
            repo_root, accept_no_install_record=accept_no_install_record
        )
    except InstallRecordUnreadable as exc:
        sys.stderr.write(
            f"install-record: {exc}\n"
            "Fix: pass --accept-no-install-record to mint a boot anchor without it,\n"
            "or re-run `harness install` to regenerate .harness/install-record.json.\n"
        )
        return 9

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
