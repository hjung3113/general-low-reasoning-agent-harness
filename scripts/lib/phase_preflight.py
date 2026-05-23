"""Shared preflight helpers for TTY-only phase verbs (design §3.1, §3.2).

Extracted from `phase_approve.py` + `phase_reopen.py` during the S04+S05
review-fix (P2-3) so the upcoming `phase set` rewrite (S07-prep) does not
copy-paste a third near-identical preflight chain.

Public surface
--------------
* `now_iso_z()`                              — UTC ISO-Z timestamp (sec res)
* `default_gitconfig_email_lookup()`         — read `git config user.email`
* `load_install_record(path)`                — JSON-parse install record
* `FIX_GITCONFIG`                            — fix-line constant (§3.9)

Note: `run_state_trust_preflight` / `StateTrustPreflightError` / `FIX_STATE_TRUST`
were removed in M4-3 (#10) per ADR-0002 (no external attacker) and ADR-0005
(plain JSONL audit log — no tamper oracle needed).

Note: `approvers_emails` / `FIX_APPROVER_MEMBERSHIP` removed in M5 #13
per ADR-0002 (no attacker model — no allowlist enforcement needed for an
internal single-user dev tool).

The helpers do NOT print/log; callers map the raised errors to their own
verb-specific result types. This keeps the module test-friendly and lets
each verb compose its own `Fix:` message.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Fix-line constants (§3.9 — every error MUST carry a remediation)
# ---------------------------------------------------------------------------


FIX_GITCONFIG = (
    "Fix: run `git config user.email <your-email>` or pass `--by <your-email>`"
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
    """Parse the install-record file. Raises FileNotFoundError if absent.

    Forward-compat: legacy records with approvers[] are loaded as-is without
    failing — callers ignore the field (ADR-0002, M5 #13).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = [
    "FIX_GITCONFIG",
    "now_iso_z",
    "default_gitconfig_email_lookup",
    "load_install_record",
]
