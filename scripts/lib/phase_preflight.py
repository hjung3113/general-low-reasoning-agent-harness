"""Shared preflight helpers for TTY-only phase verbs (design §3.1, §3.2, §12.1, §2.6).

Extracted from `phase_approve.py` + `phase_reopen.py` during the S04+S05
review-fix (P2-3) so the upcoming `phase set` rewrite (S07-prep) does not
copy-paste a third near-identical preflight chain.

Public surface
--------------
* `now_iso_z()`                              — UTC ISO-Z timestamp (sec res)
* `default_gitconfig_email_lookup()`         — read `git config user.email`
* `load_install_record(path)`                — JSON-parse install record
* `approvers_emails(install_record)`         — extract lower-cased emails
* `FIX_GITCONFIG / FIX_APPROVER_MEMBERSHIP / FIX_STATE_TRUST /
   FIX_ANCHOR_MISSING / FIX_ANCHOR_MISMATCH / FIX_ANCHOR_UNVERIFIABLE`
   — fix-line constants (§3.9)
* `AnchorPreflightError`                     — raised by `run_anchor_preflight`
* `run_anchor_preflight(...)`                — fail-closed anchor check
* `StateTrustPreflightError`                 — raised by `run_state_trust_preflight`
* `run_state_trust_preflight(...)`           — §2.6 state-audit-tip cross-check

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

from . import audit_anchor as _audit_anchor
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
FIX_ANCHOR_MISSING = (
    "Fix: run `harness anchor repair` from a TTY to mint the "
    "out-of-repo audit-tip anchor (design §12.1)"
)
FIX_ANCHOR_MISMATCH = (
    "Fix: investigate audit/install-record tampering, then "
    "`harness anchor repair` from a TTY (design §12.1)"
)
FIX_ANCHOR_UNVERIFIABLE = (
    "Fix: caller must pass `repo_root=` so the §12.1 trust chain can "
    "verify the out-of-repo audit-tip anchor before reading state; "
    "or pass `skip_anchor_preflight=True` ONLY from controlled test paths"
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
# Anchor preflight (§12.1)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AnchorPreflightError(Exception):
    """Raised when anchor preflight fails. Callers map `sub_reason` to a
    verb-specific result type. `fix_line` is the user-facing remediation
    string from `FIX_ANCHOR_*`."""

    sub_reason: str
    fix_line: str
    message: str

    def __str__(self) -> str:  # pragma: no cover — trivial
        return f"{self.sub_reason}: {self.message}"


def run_anchor_preflight(
    *,
    skip_anchor_preflight: bool,
    repo_root: Optional[Path],
) -> bool:
    """Run the §12.1 anchor preflight. Returns `anchor_verified` (always
    True on success). Raises `AnchorPreflightError` on failure.

    Fail-closed default: `repo_root=None` + `skip_anchor_preflight=False`
    raises with `sub_reason="anchor_preflight_unwired"` (design §12.1 +
    S02-approve P1-1 review-fix).
    """
    if skip_anchor_preflight:
        return True
    if repo_root is None:
        raise AnchorPreflightError(
            sub_reason="anchor_preflight_unwired",
            fix_line=FIX_ANCHOR_UNVERIFIABLE,
            message="anchor preflight cannot run without repo_root",
        )
    try:
        _audit_anchor.verify_existing_anchor_for_repo(repo_root)
        return True
    except _audit_anchor.AnchorMissingError as exc:
        raise AnchorPreflightError(
            sub_reason="anchor_missing",
            fix_line=FIX_ANCHOR_MISSING,
            message=f"audit-tip anchor not found ({exc})",
        ) from exc
    except _audit_anchor.AnchorMismatchError as exc:
        sub = exc.sub_reason or "anchor_verification_failed"
        raise AnchorPreflightError(
            sub_reason=sub,
            fix_line=FIX_ANCHOR_MISMATCH,
            message=f"audit-tip anchor verification failed ({sub}: {exc})",
        ) from exc
    except _audit_anchor.AnchorError as exc:
        sub = exc.sub_reason or "anchor_error"
        raise AnchorPreflightError(
            sub_reason=sub,
            fix_line=FIX_ANCHOR_MISMATCH,
            message=f"audit-tip anchor unreadable ({sub}: {exc})",
        ) from exc


# ---------------------------------------------------------------------------
# State-trust preflight (§2.6)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StateTrustPreflightError(Exception):
    """Raised when state-trust preflight fails.

    `exit_code` maps to design §3.4:
      * 10 -> `state_audit_tip_mismatch`
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
            sub_reason="state_audit_tip_mismatch",
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
    "FIX_ANCHOR_MISSING",
    "FIX_ANCHOR_MISMATCH",
    "FIX_ANCHOR_UNVERIFIABLE",
    "now_iso_z",
    "default_gitconfig_email_lookup",
    "load_install_record",
    "approvers_emails",
    "AnchorPreflightError",
    "run_anchor_preflight",
    "StateTrustPreflightError",
    "run_state_trust_preflight",
]
