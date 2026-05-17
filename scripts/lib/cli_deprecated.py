"""Deprecated CLI flag detection and halt (design §3.3, §3.4, S07).

Detects `--chain` and `--auto` flags anywhere in argv and halts with:
  - Exit 13 `deprecated_flag`
  - Structured error message with replacement hint
  - Audit entry `verb=cli.deprecated_flag` (with S06 chain fields)

The check runs at the top of `scripts/harness.py:run()` BEFORE argparse,
so the deprecated flags intercept before argparse rejects them.

Design refs: §3.3 (drop flags), §3.4 (exit 13), §12.7 (verb registry)
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Optional

EXIT_DEPRECATED_FLAG = 13

# §3.3 replacement hint — exact text from design
_HINT_TEMPLATE = (
    "Error: {flag} flag removed in v0.8.\n"
    "Fix: use 'harness phase autopilot start [--mode chain]' (chain mode) or\n"
    "     'harness phase autopilot start --mode phase' (single-phase mode) instead.\n"
    "     Or use 'harness fsd-run-phase' / 'harness fsd-run-all' (slash-command wrappers)."
)

DEPRECATED_FLAGS = frozenset(["--chain", "--auto"])


@dataclasses.dataclass
class DeprecatedFlagError:
    """Returned by check_deprecated_flags when a deprecated flag is found."""
    flag: str
    hint: str = dataclasses.field(default="")
    exit_code: int = EXIT_DEPRECATED_FLAG

    def __post_init__(self) -> None:
        if not self.hint:
            self.hint = _HINT_TEMPLATE.format(flag=self.flag)


def _is_deprecated_flag(arg: str) -> bool:
    """Return True if *arg* is or starts with a deprecated flag.

    Matches exact form (``--chain``) AND value-attached form
    (``--chain=foo``, ``--auto=bar``) so that ``--chain=value`` cannot
    bypass the deprecation gate (P1-4).
    """
    return arg in DEPRECATED_FLAGS or any(
        arg.startswith(f + "=") for f in DEPRECATED_FLAGS
    )


def check_deprecated_flags(
    argv: list[str],
    *,
    audit_path: Optional[Path] = None,
) -> Optional[DeprecatedFlagError]:
    """Check `argv` for `--chain` / `--auto`. Returns a DeprecatedFlagError or None.

    If a deprecated flag is found AND `audit_path` is provided, writes a
    `verb=cli.deprecated_flag` audit entry (with S06 chain fields). The caller
    must print the error and call sys.exit(13).

    Flags are detected anywhere in argv (not just position 0) to catch both:
      harness --chain phase set plan
      harness phase set execute --auto
    Also detects value-attached form: --chain=foo, --auto=bar (P1-4).
    """
    detected: Optional[str] = None
    for arg in argv:
        if _is_deprecated_flag(arg):
            # Normalise to the bare flag name for the hint template
            detected = arg if arg in DEPRECATED_FLAGS else arg.split("=", 1)[0]
            break

    if detected is None:
        return None

    hint = _HINT_TEMPLATE.format(flag=detected)
    error = DeprecatedFlagError(flag=detected, hint=hint)

    # Write audit entry if audit_path provided
    if audit_path is not None:
        _write_audit_entry(detected, hint, audit_path=Path(audit_path))

    return error


def _write_audit_entry(flag: str, hint: str, *, audit_path: Path) -> None:
    """Write a verb=cli.deprecated_flag audit entry (with S06 chain fields)."""
    import datetime

    try:
        from .audit import audit_append
    except ImportError:
        from lib.audit import audit_append

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "verb": "cli.deprecated_flag",
        "at": now,
        "args": {
            # §3.3 spec: args={"flag":"--chain"|"--auto"} (P2-2 schema alignment)
            "flag": flag,
            "replacement_command": (
                "harness phase autopilot start [--mode chain|phase]"
            ),
        },
        "hint": hint,
    }

    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        # audit_append is race-safe via fcntl.flock (LOCK_EX) held internally;
        # no additional lock is acquired here (P2-5).
        audit_append(entry, audit_path=audit_path)
    except (FileNotFoundError, PermissionError):
        # repo_root() resolution failure or read-only audit.log — silently skip
        # so the exit-13 deprecation path is never suppressed (P2-1).
        pass
    except OSError as exc:
        # Other OS-level failures (e.g. ENOSPC) — warn to stderr but still exit 13
        import sys as _sys
        print(
            f"Warning: audit write failed ({exc}); exit-13 deprecation path continues.",
            file=_sys.stderr,
        )


def print_and_exit(error: DeprecatedFlagError) -> None:
    """Print the deprecation error to stderr and exit with 13."""
    print(error.hint, file=sys.stderr)
    sys.exit(error.exit_code)


__all__ = [
    "DeprecatedFlagError",
    "check_deprecated_flags",
    "print_and_exit",
    "EXIT_DEPRECATED_FLAG",
    "DEPRECATED_FLAGS",
]
