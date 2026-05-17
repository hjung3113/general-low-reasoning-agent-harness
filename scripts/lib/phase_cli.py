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
from lib.state_diagnostics import load_state_json
from lib.session import (
    acquire_lock,
    LockfileExists,
    is_pid_alive,
    read_boot_id,
    read_lock_payload,
)
from lib.timestamps import now_iso_nanos, parse_iso_nanos
from lib import transition as _transition
from lib import phase_state as _phase_state
from lib.transition import InvalidTransition
from lib import phase_approve as _phase_approve
from lib import phase_reopen as _phase_reopen

STATE_PATH = Path(".scratch/phase-state.json")
LOCK_PATH = Path(".harness/session.lock")
AUDIT_PATH = Path(".harness/audit.log")
HARNESS_DIR = Path(".harness")
WRITE_PROBE = HARNESS_DIR / ".write_probe"
SCRATCH_DIR = Path(".scratch")

LOCKFILE_TEMPLATE = (
    "error: active session detected at .harness/session.lock; "
    "finish the session ('harness phase set done' or 'harness phase approve'), "
    "or run 'harness session unlock' after confirming no other harness process is running. "
    "Fix: run 'harness session unlock' (or 'harness session unlock --force' if the lock is stale)"
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
    # T1-M-C2: route through the sanctioned reader. load_state_json emits
    # the structured single-line "error: <path> is unparseable at line
    # N:col M: <msg>; <hint>" diagnostic and exits 5 on failure.
    data = load_state_json(STATE_PATH)
    if not isinstance(data, dict):
        print(
            "error: .scratch/phase-state.json must be a JSON object.",
            file=sys.stderr,
        )
        sys.exit(EXIT_UNPARSEABLE_JSON)
    return (data, data.get("phase"))


_EXPECTED_STATE_SCHEMA_VERSION = 2


def _ensure_state_schema_version(data: dict) -> None:
    """Stamp ``state_schema_version=2`` on the state, or refuse with exit 5.

    Contract: CONTRACT-PIN §7 L2 + ADR-001 Decision L2 require every v2 state
    write to carry ``state_schema_version=2``. The canonical producer is
    ``scripts/lib/state_migrate.py:forward`` (see MIGRATOR doc). Prior to
    this stamp, ``phase set`` / ``phase approve`` silently omitted the field,
    forcing the smoke comparator to use an ``<ANY>`` sentinel for the field
    (see 02b-11 commit bab5c5d). Mutates ``data`` in-place.

    Semantics:
    - field absent  -> stamp to 2.
    - field == 2    -> no-op.
    - field == N!=2 -> exit 5 with a remediation line naming the migrator.
    """
    current = data.get("state_schema_version")
    if current is None:
        data["state_schema_version"] = _EXPECTED_STATE_SCHEMA_VERSION
        return
    if current == _EXPECTED_STATE_SCHEMA_VERSION:
        return
    print(
        f"error: state_schema_version={current!r} expected {_EXPECTED_STATE_SCHEMA_VERSION}; "
        f"run 'harness migrate state --forward' first",
        file=sys.stderr,
    )
    sys.exit(EXIT_UNPARSEABLE_JSON)


def _write_state_atomic(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ensure_state_schema_version(data)
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
    """Print the ADR-003a Artifact 1 invalid-transition template to stderr.

    When ``exc`` is an ``InvalidTransition`` (the C3 typed exception), its
    ``format_message()`` returns the byte-exact template. For any other
    SystemExit (defensive fallback for older raise sites), fall back to
    ``str(exc)`` with a table-reference append.
    """
    if isinstance(exc, InvalidTransition):
        print(exc.format_message(), file=sys.stderr)
        return EXIT_INVALID_TRANSITION
    msg = str(exc) or "invalid phase transition"
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

    # §3.5.1 / §7 line 1020 env-as-state elimination guard (S13 step 2).
    # If HARNESS_AUTOMATION is set to an autopilot mode but state.execution_mode
    # is still "manual", the env cannot substitute for a legitimate `phase autopilot
    # start` call. Reject with exit 2 (no_autopilot_context_in_state) to make
    # env-only spoofing impossible — this is the mandatory invariant tested by
    # release_smoke_test.py --case env-only-spoof-rejected.
    _harness_automation = os.environ.get("HARNESS_AUTOMATION", "")
    if _harness_automation in ("phase", "chain") and state.get("execution_mode", "manual") == "manual":
        print(
            "error: phase set refused: HARNESS_AUTOMATION is set to "
            f"{_harness_automation!r} but state.execution_mode is 'manual' "
            "(no_autopilot_context_in_state). "
            "Fix: run 'harness phase autopilot start' first to establish "
            "autopilot context in state; env vars alone cannot grant "
            "autopilot privileges (design §3.5.1 / §7 line 1020).",
            file=sys.stderr,
        )
        return EXIT_INVALID_TRANSITION

    # P1-2: wall-seconds budget check AFTER state load, BEFORE any mutation.
    # Acquires primary lock briefly for the halt-commit if needed; released immediately.
    if state.get("execution_mode", "manual") != "manual":
        from scripts.lib import cli_budgets as _cli_budgets_mod
        from scripts.lib import phase_lock as _phase_lock_mod
        _primary_lock = _phase_lock_mod.acquire_primary(SCRATCH_DIR, timeout_s=5.0)
        try:
            _halt_exit = _cli_budgets_mod.wall_seconds_check_and_maybe_halt(
                before_state=state,
                scratch_root=SCRATCH_DIR,
                audit_path=AUDIT_PATH,
                lock_handle=_primary_lock,
            )
        finally:
            _phase_lock_mod.release_primary(_primary_lock)
        if _halt_exit is not None:
            return _halt_exit
    approved = bool(state.get("approved"))
    reset_approval = bool(getattr(args, "reset_approval", False))

    # No-op restamp short-circuit: phase=X → phase=X without flags is OK.
    if current == target and not reset_approval:
        # We still write an audit entry recording the no-op and update timestamps.
        new_state = dict(state)
        new_state["phase"] = target
        new_state["updated_at"] = now_iso_nanos()
        new_state["updated_by"] = _identify()
        noop_plan_id = getattr(args, "plan_id", None)
        noop_summary = getattr(args, "summary", None)
        if noop_plan_id is not None:
            new_state["plan_id"] = noop_plan_id
        if noop_summary is not None:
            new_state["summary"] = noop_summary
        if getattr(args, "stdin_json", False):
            extra = _read_stdin_json()
            for k, v in extra.items():
                if k in ALLOWED_STDIN_FIELDS:
                    new_state[k] = v
        _write_state_atomic(new_state)
        after_hash = compute_state_hash(STATE_PATH)
        noop_args: dict = {"phase": target}
        if noop_plan_id:
            noop_args["plan_id"] = noop_plan_id
        if noop_summary:
            noop_args["summary"] = noop_summary
        idx = audit_append(
            {
                "verb": "phase.set.noop",
                "args": noop_args,
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

    # §3.6 state-aware superset validator — raises StaleApprovalError (exit 2)
    # when approval is stale relative to plan_finalized_at / execute_attempt_started_at,
    # or when verification / allowed_paths are missing on (plan→execute).
    # Only called for forward transitions where the state dict is meaningful;
    # the legacy validator above already handled undefined pairs and the
    # basic approved=False reject.  We pass `state` (before_state) so the
    # full §3.6 stale-approval matrix is available.
    try:
        _transition.validate_transition_with_state(
            state,
            target,
            reset_approval=reset_approval,
        )
    except SystemExit as exc:
        if getattr(exc, "code", None) == 2:
            # StaleApprovalError carries a format_message() just like
            # InvalidTransition; re-use _emit_invalid_transition which
            # handles both typed subclasses.
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

    # Review-fix P1-2: stamp §1.1 / §3.6 transition timestamps so the
    # producer side matches the validator's expectations. Without this
    # `validate_transition_with_state` rejects every real-world state
    # with `plan_finalized_at_missing` / `execute_attempt_started_at_missing`.
    new_state = _phase_state.stamp_transition_timestamps(
        new_state, to_phase=target, now_iso=new_state["updated_at"]
    )

    # P1-1: apply file_mutation_ops decrement (caller-contract per §3.5).
    if new_state.get("execution_mode", "manual") != "manual":
        from scripts.lib.phase_txn import with_budget_decrement as _with_budget_decrement
        new_state = _with_budget_decrement(new_state)

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
    """Handle ``harness phase approve`` (ADR-003a verb 2).

    Delegates to ``phase_approve.run_approve`` (S02+S05 spec-compliant path)
    which enforces the §3.1 TTY gate, identity resolution, install-record
    membership, anchor + state-trust preflight, human-presence nonce, and
    §3.1.1 audit provenance. The legacy ``_do_phase_approve`` shim is kept
    for reference but is no longer called from this handler.
    """
    _probe_harness_writable()

    cwd = Path.cwd()
    scratch = cwd / ".scratch"
    harness_dir = cwd / ".harness"
    audit_path = harness_dir / "audit.log"
    install_record_path = harness_dir / "install-record.json"

    # Nonce dir: honour explicit --nonce-dir arg, else fall back to the
    # canonical out-of-project default (~/.harness/approval-nonces/).
    from lib import approval_nonce as _approval_nonce

    nonce_dir_raw: Optional[str] = getattr(args, "nonce_dir", None)
    nonce_dir: Path = (
        Path(nonce_dir_raw) if nonce_dir_raw else _approval_nonce.default_nonce_dir()
    )

    stdin_isatty: bool = sys.stdin.isatty()
    # P2-P2-2: os.ttyname is POSIX-only (raises AttributeError on Windows).
    # Guard with os.name == "posix" so Windows callers get an empty string
    # instead of a traceback.
    # TODO(v0.8 P2-A2): On Windows, consumer_tty="" is passed here. The mint
    # side (approval_nonce.mint) now stamps a unique "win:<pid>:<token>" into
    # the nonce file so that "" != stored_minter_tty, preserving cross-TTY
    # distinctness.  Real per-session enforcement on Windows requires the mint
    # CLI to STORE its session identifier and the consume side to read its OWN
    # session id (approve-nonce mint CLI carryover — v0.8 follow-up).
    consumer_tty: str = (
        os.ttyname(sys.stdin.fileno())
        if (stdin_isatty and os.name == "posix")
        else ""
    )

    result = _phase_approve.run_approve(
        args,
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record_path,
        nonce_dir=nonce_dir,
        stdin_isatty=stdin_isatty,
        consumer_tty=consumer_tty,
        repo_root=cwd,
        skip_anchor_preflight=False,
    )
    return result.exit_code


def _do_phase_approve(args) -> int:  # type: ignore[no-untyped-def]
    """Legacy shim — retained for backward compatibility with any direct
    callers (e.g. test-harness unittest baseline). Production traffic
    now routes through ``cmd_phase_approve → phase_approve.run_approve``."""
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


def _audit_session_unlock(payload: dict, *, force: bool) -> None:
    """Append a session.unlock audit entry recording the stolen payload.

    Per T0-3 C2 amendment: every removal path of the lockfile (normal
    dead-pid, --force, boot_id mismatch) writes an audit row capturing the
    pre-removal payload so post-hoc forensic reconstruction is possible.
    Failures to write the audit entry are swallowed (unlock is best-effort
    and must not block on .harness/audit.log being unavailable — the
    operational write_probe in entry points covers the steady-state path).
    """
    try:
        audit_append(
            {
                "verb": "session.unlock",
                "args": {"force": bool(force), "stolen_payload": payload},
                "before_sha256": "",
                "after_sha256": "",
                "at": now_iso_nanos(),
                "by": _identify(),
            },
            audit_path=AUDIT_PATH,
        )
    except OSError:
        pass


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
        _audit_session_unlock(payload, force=True)
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
        return EXIT_OK

    pid = payload.get("pid")
    if pid is None:
        print(
            "error: lockfile has no pid; staleness cannot be determined. "
            "Pass --force to remove. "
            "Fix: run 'harness session unlock --force' to forcibly remove the stale lock.",
            file=sys.stderr,
        )
        return EXIT_STALE_UNCERTAIN

    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        print(
            f"error: lockfile pid={pid!r} is not an integer; pass --force to remove. "
            "Fix: run 'harness session unlock --force' to forcibly remove the stale lock.",
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
        _audit_session_unlock(payload, force=False)
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

    _audit_session_unlock(payload, force=False)
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    return EXIT_OK


# --------------------------------------------------------------------------
# phase reopen
# --------------------------------------------------------------------------


def cmd_phase_reopen(args) -> int:  # type: ignore[no-untyped-def]
    """Handle ``harness phase reopen`` (design §3.2).

    Delegates to ``phase_reopen.run_reopen`` which enforces the §3.2
    TTY gate, identity resolution, install-record membership, anchor +
    state-trust preflight, and the halt-diary / reset-matrix mutation.
    """
    _probe_harness_writable()

    cwd = Path.cwd()
    scratch = cwd / ".scratch"
    harness_dir = cwd / ".harness"
    audit_path = harness_dir / "audit.log"
    install_record_path = harness_dir / "install-record.json"

    stdin_isatty: bool = sys.stdin.isatty()

    result = _phase_reopen.run_reopen(
        args,
        scratch=scratch,
        harness_dir=harness_dir,
        audit_path=audit_path,
        install_record_path=install_record_path,
        stdin_isatty=stdin_isatty,
        repo_root=cwd,
        skip_anchor_preflight=False,
    )
    return result.exit_code


__all__ = ["cmd_phase_set", "cmd_phase_approve", "cmd_phase_reopen", "cmd_session_unlock"]
