"""CLI implementation for `harness approve-nonce mint` (design §3.1.1).

This module exposes a single entry point:

    run_mint(args, *, nonce_dir, stdout, stderr) -> int

Wired from ``scripts/harness.py`` argparse dispatch. The verb is TTY-only
(admin security contract — self-approval spoofing defense §3.1.1).

Public surface
--------------
    run_mint(args, *, nonce_dir, stdout, stderr) -> int
"""

from __future__ import annotations

import os
import secrets
import sys
from io import IOBase
from pathlib import Path
from typing import IO, Optional

from . import approval_nonce as _approval_nonce
from . import audit as _audit


# ---------------------------------------------------------------------------
# TTY resolution helpers
# ---------------------------------------------------------------------------

def _resolve_minter_tty() -> tuple[str, str]:
    """Resolve the minter TTY path and its kind label.

    Returns
    -------
    (minter_tty, minter_tty_kind)
        minter_tty_kind ∈ {"posix-real", "posix-fallback", "win-synthetic"}
    """
    if os.name == "nt":
        # Windows: os.ttyname is not available; mirror _ensure_windows_tty_path
        # from approval_nonce.py:85-104 exactly so the cross-TTY guard works.
        tty_path = f"win:{os.getpid()}:{secrets.token_hex(4)}"
        return tty_path, "win-synthetic"

    # POSIX path
    try:
        tty_path = os.ttyname(sys.stdin.fileno())
        return tty_path, "posix-real"
    except OSError:
        tty_path = f"posix:{os.getpid()}:{secrets.token_hex(4)}"
        return tty_path, "posix-fallback"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_mint(
    args,  # argparse.Namespace with .audience (str) and .ttl (int)
    *,
    nonce_dir: Optional[Path] = None,
    stdout: IO[str] = sys.stdout,
    stderr: IO[str] = sys.stderr,
) -> int:
    """Mint a new approval nonce.

    Exit codes
    ----------
    0   success; nonce minted and written
    1   unexpected error
    2   non-TTY refusal OR argparse-level validation failure (TTL range)

    Security contract: this verb is TTY-only.  Non-TTY invocations are refused
    so that automated agents cannot self-mint a human-presence proof.
    HARNESS_TEST_FORCE_TTY=1 bypasses the check for unit tests only.
    """
    # ------------------------------------------------------------------
    # 1. TTY guard
    # ------------------------------------------------------------------
    force_tty = os.environ.get("HARNESS_TEST_FORCE_TTY") == "1"
    is_tty = force_tty or (sys.stdin is not None and sys.stdin.isatty())
    if not is_tty:
        stderr.write("error: approve-nonce mint requires an interactive TTY\n")
        return 2

    # ------------------------------------------------------------------
    # 2. Resolve nonce directory
    # ------------------------------------------------------------------
    if nonce_dir is None:
        env_dir = os.environ.get("HARNESS_NONCE_DIR")
        if env_dir:
            nonce_dir = Path(env_dir)
        else:
            nonce_dir = _approval_nonce.default_nonce_dir()

    # ------------------------------------------------------------------
    # 3. Resolve TTY identity
    # ------------------------------------------------------------------
    minter_tty, minter_tty_kind = _resolve_minter_tty()

    # ------------------------------------------------------------------
    # 4. Mint nonce
    # ------------------------------------------------------------------
    try:
        nonce = _approval_nonce.mint(
            nonce_dir,
            audience=args.audience,
            minter_tty=minter_tty,
            ttl_seconds=args.ttl,
        )
    except Exception as exc:
        stderr.write(f"error: approve-nonce mint failed: {exc}\n")
        return 1

    # ------------------------------------------------------------------
    # 5. Emit audit row (do NOT log raw minter_tty — only the kind label)
    # ------------------------------------------------------------------
    try:
        # Resolve audit path relative to CWD (same convention as other verbs).
        audit_path = Path(".harness") / "audit.log"
        _audit.audit_append(
            {
                "verb": "approve_nonce.mint",
                "nonce_id": nonce.nonce_id,
                "audience": nonce.audience,
                "ttl_seconds": args.ttl,
                "minter_tty_kind": minter_tty_kind,
            },
            audit_path=audit_path,
        )
    except Exception:
        # Audit failure is non-fatal for this admin verb (no lock held).
        pass

    # ------------------------------------------------------------------
    # 6. Print machine-parseable result
    # ------------------------------------------------------------------
    ttl_remaining = int(nonce.expires_at - nonce.minted_at)
    stdout.write(
        f"nonce_id={nonce.nonce_id} audience={nonce.audience} expires_in_s={ttl_remaining}\n"
    )
    return 0


__all__ = ["run_mint"]
