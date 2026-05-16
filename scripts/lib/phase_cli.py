"""Phase lifecycle + session operational CLI verbs (ADR-003a Artifact 1).

Owning plan: .planning/phases/02b-hardening/plans/02b-04-T0-3-PLAN.md
Contract pin: .planning/phases/02b-hardening/CONTRACT-PIN.md §1, §4.

Three verb handlers delegated from ``scripts/harness.py``:

- ``cmd_phase_set(args)`` — ADR-003a verb 1.
- ``cmd_phase_approve(args)`` — ADR-003a verb 2.
- ``cmd_session_unlock(args)`` — ADR-003a verb 3 (operational, G1-B).

All state writes route through ``scripts/lib/atomic_io.atomic_write_text``.
All audit appends route through ``scripts/lib/audit.audit_append``. Exit
codes are the canonical constants from ``scripts/lib/exitcodes``.

Trust boundary (G4-B): these verbs never execute verification strings;
they only write metadata.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Optional

from lib.atomic_io import atomic_write_text
from lib.audit import audit_append, compute_state_hash
from lib.exitcodes import (
    EXIT_OK,
    EXIT_OPERATIONAL,
    EXIT_INVALID_TRANSITION,
    EXIT_SESSION_LOCKED,
    EXIT_UNPARSEABLE_JSON,
    EXIT_WRONG_PHASE_FOR_VERB,
    EXIT_STALE_UNCERTAIN,
    EXIT_TIMESTAMP_OUT_OF_RANGE,
)
from lib.session import (
    acquire_lock,
    LockfileExists,
    is_pid_alive,
    read_boot_id,
    read_lock_payload,
)
from lib.timestamps import now_iso_nanos, parse_iso_nanos
from lib import transition as _transition

STATE_PATH = Path(".scratch/phase-state.json")
LOCK_PATH = Path(".harness/session.lock")
AUDIT_PATH = Path(".harness/audit.log")
HARNESS_DIR = Path(".harness")
WRITE_PROBE = HARNESS_DIR / ".write_probe"

LOCKFILE_TEMPLATE = (
    "error: active session detected at .harness/session.lock; "
    "finish the session ('harness phase set done' or 'harness phase approve'), "
    "or run 'harness session unlock' after confirming no other harness process is running"
)

ALLOWED_STDIN_FIELDS = {
    "next_action",
    "current_checkpoint",
    "checkpoint_path",
    "state_path",
    "plan_path",
    "summary",
    "plan_id",
}


def _identify() -> str:
    """Return the actor identity, honouring HARNESS_USER override."""
    env = os.environ.get("HARNESS_USER")
    if env:
        return env
    try:
        import subprocess  # local import; verbs run rarely
        r = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USER", "unknown")


def _load_state() -> tuple[dict, Optional[str]]:
    if not STATE_PATH.exists():
        return ({}, None)
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(
            f"error: .scratch/phase-state.json is unparseable ({exc}); "
            f"fix the JSON or restore from a backup before retrying.",
            file=sys.stderr,
        )
        sys.exit(EXIT_UNPARSEABLE_JSON)
    if not isinstance(data, dict):
        print(
            "error: .scratch/phase-state.json must be a JSON object.",
            file=sys.stderr,
        )
        sys.exit(EXIT_UNPARSEABLE_JSON)
    return (data, data.get("phase"))


def _write_state_atomic(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(STATE_PATH, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _read_stdin_json() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"error: --stdin-json input is unparseable ({exc}); "
            f"pass valid JSON via stdin.",
            file=sys.stderr,
        )
        sys.exit(EXIT_UNPARSEABLE_JSON)


def _probe_harness_writable() -> None:
    """Fast-fail if ``.harness/`` is not writable (T0-3 amendment #8)."""
    try:
        HARNESS_DIR.mkdir(parents=True, exist_ok=True)
        WRITE_PROBE.write_text("")
        WRITE_PROBE.unlink()
    except OSError as exc:
        print(
            f"error: .harness/ is not writable ({exc}); cannot record session/audit.",
            file=sys.stderr,
        )
        sys.exit(EXIT_OPERATIONAL)


def _emit_invalid_transition(exc: SystemExit) -> int:
    msg = str(exc) or "invalid phase transition"
    # Append the ADR-001 transition table reference if not already present.
    if "ADR-001" not in msg and "transition table" not in msg:
        msg = f"{msg} (see ADR-001 transition table)"
    print(msg, file=sys.stderr)
    return EXIT_INVALID_TRANSITION


# --------------------------------------------------------------------------
# phase set
# --------------------------------------------------------------------------


def cmd_phase_set(args) -> int:  # type: ignore[no-untyped-def]
    _probe_harness_writable()
    try:
        with acquire_lock(lock_path=LOCK_PATH):
            return _do_phase_set(args)
    except LockfileExists:
        print(LOCKFILE_TEMPLATE, file=sys.stderr)
        return EXIT_SESSION_LOCKED


def _do_phase_set(args) -> int:  # type: ignore[no-untyped-def]
    state, current = _load_state()
    before_hash = compute_state_hash(STATE_PATH)
    target = args.phase
    approved = bool(state.get("approved"))
    reset_approval = bool(getattr(args, "reset_approval", False))

    # No-op restamp short-circuit: phase=X → phase=X without flags is OK.
    if current == target and not reset_approval:
        # We still write an audit entry recording the no-op and update timestamps.
        new_state = dict(state)
        new_state["phase"] = target
        new_state["updated_at"] = now_iso_nanos()
        new_state["updated_by"] = _identify()
        _write_state_atomic(new_state)
        after_hash = compute_state_hash(STATE_PATH)
        idx = audit_append(
            {
                "verb": "phase.set.noop",
                "args": {"phase": target},
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "at": new_state["updated_at"],
                "by": new_state["updated_by"],
            },
            audit_path=AUDIT_PATH,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "verb": "phase.set",
                    "previous_phase": current,
                    "phase": target,
                    "state_path": str(STATE_PATH),
                    "audit_entry_index": idx,
                    "updated_at": new_state["updated_at"],
                    "updated_by": new_state["updated_by"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_OK

    try:
        _transition.validate_transition(
            current,
            target,
            approved=approved,
            reset_approval=reset_approval,
        )
    except SystemExit as exc:
        if getattr(exc, "code", None) == 2:
            return _emit_invalid_transition(exc)
        raise

    new_state = dict(state)
    new_state["phase"] = target
    new_state["updated_at"] = now_iso_nanos()
    new_state["updated_by"] = _identify()
    if reset_approval:
        new_state["approved"] = False
        new_state["approved_by"] = None
        new_state["approved_at"] = None
    # If we just transitioned out of plan/execute toward execute/done, the
    # approval consumed must reset so subsequent execute->done requires a
    # fresh approve. ADR-001 wording: approval gates one transition.
    if current in ("plan", "execute") and target in ("execute", "done") and approved:
        new_state["approved"] = False
        new_state["approved_by"] = None
        new_state["approved_at"] = None

    plan_id = getattr(args, "plan_id", None)
    summary = getattr(args, "summary", None)
    if plan_id is not None:
        new_state["plan_id"] = plan_id
    if summary is not None:
        new_state["summary"] = summary
    if getattr(args, "stdin_json", False):
        extra = _read_stdin_json()
        for k, v in extra.items():
            if k in ALLOWED_STDIN_FIELDS:
                new_state[k] = v

    _write_state_atomic(new_state)
    after_hash = compute_state_hash(STATE_PATH)

    cli_args: dict = {"phase": target}
    if plan_id:
        cli_args["plan_id"] = plan_id
    if summary:
        cli_args["summary"] = summary
    if reset_approval:
        cli_args["reset_approval"] = True

    idx = audit_append(
        {
            "verb": "phase.set",
            "args": cli_args,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "at": new_state["updated_at"],
            "by": new_state["updated_by"],
        },
        audit_path=AUDIT_PATH,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "verb": "phase.set",
                "previous_phase": current,
                "phase": target,
                "state_path": str(STATE_PATH),
                "audit_entry_index": idx,
                "updated_at": new_state["updated_at"],
                "updated_by": new_state["updated_by"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# phase approve
# --------------------------------------------------------------------------


def _validate_at_within_24h(at_str: str) -> str:
    try:
        dt = parse_iso_nanos(at_str)
    except ValueError as exc:
        print(
            f"error: --at value {at_str!r} could not be parsed as ISO-8601 ({exc}).",
            file=sys.stderr,
        )
        sys.exit(EXIT_TIMESTAMP_OUT_OF_RANGE)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    if abs((now - dt).total_seconds()) > 86_400:
        print(
            f"error: --at value {at_str!r} is not within 24h of current UTC time "
            f"({now.isoformat()}); refusing to write a far-future or far-past timestamp.",
            file=sys.stderr,
        )
        sys.exit(EXIT_TIMESTAMP_OUT_OF_RANGE)
    return at_str


def cmd_phase_approve(args) -> int:  # type: ignore[no-untyped-def]
    _probe_harness_writable()
    try:
        with acquire_lock(lock_path=LOCK_PATH):
            return _do_phase_approve(args)
    except LockfileExists:
        print(LOCKFILE_TEMPLATE, file=sys.stderr)
        return EXIT_SESSION_LOCKED


def _do_phase_approve(args) -> int:  # type: ignore[no-untyped-def]
    state, current = _load_state()
    if current == "done":
        print(
            "error: cannot approve phase=done; the done phase carries no approval "
            "semantics. Use 'harness phase set discuss --reset-approval' to start a new cycle.",
            file=sys.stderr,
        )
        return EXIT_WRONG_PHASE_FOR_VERB
    if current not in ("plan", "execute"):
        print(
            f"error: cannot approve phase={current}; approval is only valid in "
            f"phase=plan (transitions to execute) or phase=execute (re-approval after change).",
            file=sys.stderr,
        )
        return EXIT_WRONG_PHASE_FOR_VERB

    if getattr(args, "at", None):
        at = _validate_at_within_24h(args.at)
    else:
        at = now_iso_nanos()
    by = getattr(args, "by", None) or _identify()

    before_hash = compute_state_hash(STATE_PATH)
    new_state = dict(state)
    new_state["approved"] = True
    new_state["approved_by"] = by
    new_state["approved_at"] = at
    new_state["updated_at"] = now_iso_nanos()
    new_state["updated_by"] = by

    _write_state_atomic(new_state)
    after_hash = compute_state_hash(STATE_PATH)
    audit_args: dict = {}
    if getattr(args, "by", None):
        audit_args["by"] = by
    if getattr(args, "at", None):
        audit_args["at"] = at
    idx = audit_append(
        {
            "verb": "phase.approve",
            "args": audit_args,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "at": new_state["updated_at"],
            "by": by,
        },
        audit_path=AUDIT_PATH,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "verb": "phase.approve",
                "phase": current,
                "approved": True,
                "approved_by": by,
                "approved_at": at,
                "state_path": str(STATE_PATH),
                "audit_entry_index": idx,
                "updated_at": new_state["updated_at"],
                "updated_by": by,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# session unlock
# --------------------------------------------------------------------------


def cmd_session_unlock(args) -> int:  # type: ignore[no-untyped-def]
    if not LOCK_PATH.exists():
        return EXIT_OK
    try:
        payload = read_lock_payload(LOCK_PATH)
    except json.JSONDecodeError as exc:
        print(
            f"error: .harness/session.lock is unparseable ({exc}); inspect and remove manually.",
            file=sys.stderr,
        )
        return EXIT_UNPARSEABLE_JSON
    except OSError as exc:
        print(f"error: cannot read .harness/session.lock ({exc}).", file=sys.stderr)
        return EXIT_OPERATIONAL

    if getattr(args, "print_only", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_OK

    if getattr(args, "force", False):
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
        return EXIT_OK

    pid = payload.get("pid")
    if pid is None:
        print(
            "error: lockfile has no pid; staleness cannot be determined. "
            "Pass --force to remove.",
            file=sys.stderr,
        )
        return EXIT_STALE_UNCERTAIN

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        print(
            f"error: lockfile pid={pid!r} is not an integer; pass --force to remove.",
            file=sys.stderr,
        )
        return EXIT_STALE_UNCERTAIN

    recorded_boot = payload.get("boot_id")
    current_boot = read_boot_id()
    if (
        recorded_boot is not None
        and current_boot is not None
        and recorded_boot != current_boot
    ):
        # Host rebooted — pid is definitely stale.
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
        return EXIT_OK

    if is_pid_alive(pid_int):
        print(
            f"error: lockfile pid={pid_int} is still alive. Refusing to unlock without --force.",
            file=sys.stderr,
        )
        return EXIT_SESSION_LOCKED

    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    return EXIT_OK


__all__ = ["cmd_phase_set", "cmd_phase_approve", "cmd_session_unlock"]
