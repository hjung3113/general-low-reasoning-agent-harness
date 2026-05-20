"""Shared preflight helpers for TTY-only phase verbs (design §3.1, §3.2, §2.6).

Extracted from `phase_approve.py` + `phase_reopen.py` during the S04+S05
review-fix (P2-3) so the upcoming `phase set` rewrite (S07-prep) does not
copy-paste a third near-identical preflight chain.

Public surface
--------------
* `now_iso_z()`                              — UTC ISO-Z timestamp (sec res)
* `default_gitconfig_email_lookup()`         — read `git config user.email`
* `load_install_record(path)`                — JSON-parse install record
* `approvers_emails(install_record)`         — extract lower-cased emails
* `FIX_GITCONFIG / FIX_APPROVER_MEMBERSHIP / FIX_STATE_TRUST`
   — fix-line constants (§3.9)
* `StateTrustPreflightError`                 — raised by `run_state_trust_preflight`
* `run_state_trust_preflight(...)`           — §2.6 state-audit cross-check

The helpers do NOT print/log; callers map the raised errors to their own
verb-specific result types. This keeps the module test-friendly and lets
each verb compose its own `Fix:` message.

Spec: `docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md`
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from . import state_trust as _state_trust


# ---------------------------------------------------------------------------
# Fix-line constants (§3.9 — every error MUST carry a remediation)
# ---------------------------------------------------------------------------


FIX_GITCONFIG = (
    "Fix: run `git config user.email <your-email>` or pass `--by <your-email>`"
)
FIX_APPROVER_MEMBERSHIP = (
    "Fix: only emails listed in `.harness/install-record.json approvers[]` "
    "may run this verb; re-run `harness install`"
)
FIX_STATE_TRUST = (
    "Fix: run `harness verify --audit`; "
    "if intentional, restore via `git checkout -- .scratch/phase-state.json` "
    "or re-run `harness install`"
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def now_iso_z() -> str:
    """UTC ISO-Z timestamp with second resolution (microseconds dropped)."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def default_gitconfig_email_lookup() -> str:
    """Run `git config user.email`. Empty string on any failure."""
    try:
        r = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def load_install_record(path: Path) -> dict:
    """Parse the install-record file. Raises FileNotFoundError if absent."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def approvers_emails(install_record: Mapping) -> list:
    """Return lower-cased approver emails from an install-record dict."""
    out = []
    for entry in install_record.get("approvers", []) or []:
        if isinstance(entry, dict) and entry.get("email"):
            out.append(str(entry["email"]).strip().lower())
    return out


# ---------------------------------------------------------------------------
# State-trust preflight (§2.6)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StateTrustPreflightError(Exception):
    """Raised when state-trust preflight fails.

    `exit_code` maps to design §3.4:
      * 10 -> `state_audit_mismatch`
      * 14 -> `state_empty_crash_artefact`
      *  5 -> `state_unparseable` (BOM/CRLF/malformed JSON)
    """

    exit_code: int
    sub_reason: str
    message: str
    fix_line: str = FIX_STATE_TRUST

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"{self.sub_reason}: {self.message}"


def run_state_trust_preflight(
    *,
    scratch: Path,
    audit_path: Path,
    lock: Any,
    anchor_verified: bool,
) -> None:
    """Invoke `state_trust.preflight`; map its exceptions to the
    `StateTrustPreflightError` taxonomy used by both approve and reopen.
    Raises on failure; returns None on success."""
    try:
        _state_trust.preflight(
            scratch,
            audit_path=audit_path,
            lock=lock,
            anchor_verified=anchor_verified,
        )
    except _state_trust.StateAuditMismatchError as exc:
        raise StateTrustPreflightError(
            exit_code=10,
            sub_reason="state_audit_mismatch",
            message=f"state trust preflight failed: {exc}",
        ) from exc
    except _state_trust.StateEmptyError as exc:
        raise StateTrustPreflightError(
            exit_code=14,
            sub_reason="state_empty_crash_artefact",
            message=str(exc),
            fix_line=FIX_STATE_TRUST,
        ) from exc
    except (
        _state_trust.StateBomError,
        _state_trust.StateCrlfError,
        _state_trust.StateMalformedJsonError,
    ) as exc:
        raise StateTrustPreflightError(
            exit_code=5,
            sub_reason="state_unparseable",
            message=str(exc),
            fix_line=FIX_STATE_TRUST,
        ) from exc


__all__ = [
    "FIX_GITCONFIG",
    "FIX_APPROVER_MEMBERSHIP",
    "FIX_STATE_TRUST",
    "now_iso_z",
    "default_gitconfig_email_lookup",
    "load_install_record",
    "approvers_emails",
    "StateTrustPreflightError",
    "run_state_trust_preflight",
]
