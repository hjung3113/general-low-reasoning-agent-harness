"""POSIX network-deny shim for autopilot mode (design §5.2).

In autopilot mode, the harness CLI sets ``HARNESS_AUTOPILOT_NETWORK=deny``
so that this shim can intercept deny-listed network commands and refuse them
before they execute.

Deny-list (§5.2):
  - Simple commands: curl, wget, nc, ssh, scp, rsync, gh, glab
  - git subcommands that touch the network:
      git push, git pull, git fetch, git clone,
      git remote update, git submodule update --remote

Atomicity contract: shim refusal exits non-zero (exit 4) AND emits
``verb=autopilot.network.deny`` audit row BEFORE the subprocess call.
Cannot be bypassed by piping (``curl ... | bash``) because the shim wraps argv[0].

Allowlist override: set ``HARNESS_ALLOW_NETWORK=1`` to permit all commands
regardless of deny-list (used by the allow_network=True autopilot path).

Hard isolation limitation
--------------------------
Hard isolation requires PATH-prepend install so that ``curl`` etc. route
through this shim. This slice ships the shim logic + audit verb only.
Install scaffolding (PATH-prepend, Windows PowerShell shim) is deferred to
S10d / ``harness install --autopilot-guards``.

Exit codes (§3.4):
  - 4: scope_violation (sub_reason: autopilot_network_deny)

TODO (S10d): ship PATH-prepend installer ``harness install --autopilot-guards``.
TODO (S10d): Windows PowerShell shim.
TODO (S10d): network_guard_posture audit field on phase.autopilot.start.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md §5.2
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
# Deny lists (§5.2)
# ---------------------------------------------------------------------------


DENY_LIST_SIMPLE: frozenset[str] = frozenset([
    "curl", "wget", "nc", "ssh", "scp", "rsync", "gh", "glab",
])

# git subcommands that touch the network — stored as tuples for prefix-match
# Each tuple is a complete token sequence to match (exact prefix of argv[1:]).
DENY_LIST_GIT: frozenset[tuple[str, ...]] = frozenset([
    ("push",),
    ("pull",),
    ("fetch",),
    ("clone",),
    ("remote", "update"),
    ("submodule", "update", "--remote"),
])


# ---------------------------------------------------------------------------
# Fault class
# ---------------------------------------------------------------------------


class NetworkDenyError(OSError):
    """Shim refused a deny-listed network command. exit_code=4."""

    exit_code = 4
    sub_reason = "autopilot_network_deny"


# ---------------------------------------------------------------------------
# Pure deny check
# ---------------------------------------------------------------------------


def _normalize_basename(cmd: str) -> str:
    """Return lowercase basename of cmd, stripping path and known extensions.

    Examples:
      /usr/bin/curl → curl
      curl.exe      → curl
      GIT           → git
    """
    name = os.path.basename(cmd).lower()
    # Strip common Windows executable extension for cross-platform compat.
    for ext in (".exe", ".cmd", ".bat"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    return name


def is_denied(argv: Sequence[str]) -> tuple[bool, Optional[str]]:
    """Pure check: returns (True, command_label) if argv matches the deny-list,
    else (False, None). Inspects argv[0] (basename, strip path/extension) and
    sub-tokens for git family. Allowlist override: if env HARNESS_ALLOW_NETWORK=1
    is set, returns (False, None) regardless.

    Examples::

      is_denied(['curl', '-X', 'GET', 'http://x']) → (True, 'curl')
      is_denied(['/usr/bin/curl', ...]) → (True, 'curl')  # basename matched
      is_denied(['git', 'push', 'origin']) → (True, 'git push')
      is_denied(['git', 'status']) → (False, None)
      is_denied(['git', 'submodule', 'update']) → (False, None)  # not --remote
      is_denied(['git', 'submodule', 'update', '--remote']) → (True, 'git submodule update --remote')
    """
    if not argv:
        return (False, None)

    # Allowlist override.
    if os.environ.get("HARNESS_ALLOW_NETWORK", "") == "1":
        return (False, None)

    cmd0 = _normalize_basename(argv[0])

    # Simple deny list.
    if cmd0 in DENY_LIST_SIMPLE:
        return (True, cmd0)

    # git family: check subcommand prefix.
    if cmd0 == "git" and len(argv) >= 2:
        rest = tuple(argv[1:])
        # Check each deny-listed git subcommand prefix in order of length
        # (longest first to avoid partial match shadowing).
        ordered = sorted(DENY_LIST_GIT, key=lambda t: len(t), reverse=True)
        for pattern in ordered:
            if rest[: len(pattern)] == pattern:
                # Reconstruct label: "git " + space-joined pattern tokens
                label = "git " + " ".join(pattern)
                return (True, label)

    return (False, None)


# ---------------------------------------------------------------------------
# Audit emission (best-effort)
# ---------------------------------------------------------------------------


def _resolve_audit_path() -> Optional[Path]:
    """Walk from cwd upward to find the repo root, then return .harness/audit.log.

    Returns None if no .harness/ directory is found.

    This mirrors the ``operational_paths`` / phase_preflight repo-root walk
    pattern used elsewhere in the harness.
    """
    cwd = Path.cwd()
    candidate = cwd
    for _ in range(20):  # sentinel limit to avoid infinite loop
        harness_dir = candidate / ".harness"
        if harness_dir.is_dir():
            return harness_dir / "audit.log"
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None


def emit_deny_audit(
    *,
    argv: Sequence[str],
    command_label: str,
    audit_path: "str | os.PathLike",
) -> None:
    """Append verb=autopilot.network.deny BEFORE refusing. Fields:

      verb:          'autopilot.network.deny'
      command:       <sanitized argv joined with space, truncated to 512 chars>
      command_label: <matched label, e.g., 'curl' or 'git push'>
      cwd:           os.getcwd()
      at:            ISO-Z

    Best-effort: if audit_path can't be resolved or write fails, print warning
    to stderr but do NOT block the refusal (the refusal is the primary safety;
    audit is forensic).
    """
    from . import audit as _audit

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_command = " ".join(str(a) for a in argv)
    command = raw_command[:512]

    entry: dict = {
        "verb": "autopilot.network.deny",
        "command_label": command_label,
        "command": command,
        "cwd": os.getcwd(),
        "at": now,
    }

    try:
        _audit.audit_append(entry, audit_path=Path(audit_path))
    except Exception as exc:  # noqa: BLE001
        print(
            f"[autopilot_guard] warning: audit emit failed ({exc}); "
            "refusal will proceed regardless.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Shim main entry point
# ---------------------------------------------------------------------------


def shim_main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point invoked by the PATH-prepend shim wrapper.

    Flow:
      1. argv = argv or sys.argv[1:]
         (shim invocation: ``python -m scripts.lib.autopilot_guard <wrapped-argv>``)
      2. If env HARNESS_AUTOPILOT_NETWORK != "deny" → exec the real command
         pass-through (allow).
      3. Resolve audit_path via standard repo-root walk (reuse
         phase_preflight pattern or operational_paths).
      4. is_denied(argv) → if denied: emit_deny_audit + print "refused:
         <label>" to stderr + return 4.
      5. Else: exec the real command via os.execvp(argv[0], argv) —
         process-replace, no double-fork.

    Returns int (exit code). Never returns when allowing (execvp replaces
    process), unless execvp is monkeypatched in tests.
    """
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)

    # Step 2: check if we are in deny mode.
    if os.environ.get("HARNESS_AUTOPILOT_NETWORK") != "deny":
        # Pass-through: exec the real command.
        if argv:
            os.execvp(argv[0], argv)
        return 0

    # Step 3: resolve audit path.
    audit_path = _resolve_audit_path()

    # Step 4: check if denied.
    denied, command_label = is_denied(argv)

    if denied:
        # Emit audit BEFORE refusing (atomicity contract §5.2).
        if audit_path is not None:
            emit_deny_audit(argv=argv, command_label=command_label, audit_path=audit_path)
        else:
            print(
                f"[autopilot_guard] warning: could not locate .harness/audit.log; "
                "refusal will proceed without audit.",
                file=sys.stderr,
            )

        print(
            f"[autopilot_guard] refused: {command_label!r} is denied in autopilot mode "
            f"(HARNESS_AUTOPILOT_NETWORK=deny). "
            f"Command: {' '.join(argv)!r}",
            file=sys.stderr,
        )
        return 4

    # Step 5: allow — exec the real command (process-replace).
    if argv:
        os.execvp(argv[0], argv)
    return 0


# ---------------------------------------------------------------------------
# Module entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    sys.exit(shim_main(sys.argv[1:]))


__all__ = [
    "DENY_LIST_SIMPLE",
    "DENY_LIST_GIT",
    "NetworkDenyError",
    "is_denied",
    "emit_deny_audit",
    "shim_main",
    "_resolve_audit_path",
]
