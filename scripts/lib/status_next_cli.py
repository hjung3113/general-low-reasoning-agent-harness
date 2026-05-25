"""CLI handlers for `harness status` and `harness next` (design §3.9).

Wired from ``scripts/harness.py`` argparse dispatch. Both verbs are
read-only (no state mutation, no audit row written).

ADR-0002: no external attacker model; state-trust preflight removed in M4-3.
State is read with plain JSON parse + basic schema error mapping.

Spec: docs/superpowers/specs/2026-05-17-phase-gate-hardening-design.md
§3.9, §1.1 line 624, §3.4 exit 17/18
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SCRATCH_ROOT = Path(".scratch")
AUDIT_PATH = Path(".harness") / "audit.log"
STATE_NAME = "phase-state.json"


def _machine_mode() -> bool:
    return os.environ.get("HARNESS_MACHINE") == "1"


_FORBIDDEN_BY_PHASE = {
    "discuss": ["*.html", "*.css", "*.js", "*.py", "*.ts", "*.tsx", "*.jsx",
                "*.go", "*.rs", "*.rb", "package.json", "pyproject.toml",
                "src/**", "lib/**", "app/**"],
    "plan": ["*.html", "*.css", "*.js", "*.py", "*.ts", "*.tsx", "*.jsx",
             "*.go", "*.rs", "*.rb", "package.json", "pyproject.toml",
             "src/**", "lib/**", "app/**"],
    "execute": [],  # everything allowed within plan's allowed_paths
    "done": ["*.html", "*.css", "*.js", "*.py", "*.ts", "*.tsx"],  # no new features
}

_ALLOWED_BY_PHASE = {
    "discuss": [".planning/codebase/**", ".planning/milestones/<active>/NN-CONTEXT.md",
                ".planning/milestones/<active>/NN-CHECKPOINTS.md"],
    "plan": [".planning/milestones/<active>/NN-NN-PLAN.md",
             ".planning/milestones/<active>/NN-CHECKPOINTS.md"],
    "execute": ["whatever is listed in current plan's allowed_paths"],
    "done": [".planning/milestones/<active>/NN-VERIFICATION.md",
             ".planning/milestones/<active>/NN-01-SUMMARY.md"],
}


def _format_next_prompt(state: dict, result) -> str:
    """Render a copy-paste prompt for the user to send to their AI agent.

    Embeds current phase + approval + forbidden writes + refusal template +
    next legal command. Designed to deter phase-gate bypass by re-emitting
    guard context per call (codex iter2 Q4 verdict 84).
    """
    phase = state.get("phase", "discuss")
    approved = bool(state.get("approved", False))
    milestone_id = state.get("phase_id", "??")
    forbidden = _FORBIDDEN_BY_PHASE.get(phase, [])
    allowed = _ALLOWED_BY_PHASE.get(phase, [])
    next_cmd = result.command if hasattr(result, "command") and result.command else "harness run"

    refusal = (
        f"현재 phase={phase}, approved={approved}. 이 단계에서 source 파일 "
        f"({', '.join(forbidden[:5])}{'...' if len(forbidden) > 5 else ''}) "
        f"수정 불가. `{next_cmd}` 부터 실행하세요."
    )

    out = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📋 다음 단계 추천 프롬프트 — 복사해서 AI 에이전트에게 보내세요",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"[현재 워크플로우 상태 — 매 동작 전에 확인]",
        f"- phase: {phase}",
        f"- approved: {approved}",
        f"- active milestone: {milestone_id}",
        f"- forbidden writes this phase: {', '.join(forbidden) if forbidden else '(none)'}",
        f"- allowed outputs: {', '.join(allowed)}",
        "",
        f"[명령 — 그대로 복붙해서 에이전트에게]",
        "```",
        f"현재 phase={phase} (approved={approved}). 다음 진행:",
    ]

    if hasattr(result, "reason") and result.reason:
        out.append(f"  {result.reason}")

    if next_cmd:
        out.append(f"  실행: {next_cmd}")

    out.extend([
        "",
        f"제약: 이 phase 에서 다음 파일 변경 금지: {', '.join(forbidden[:3]) if forbidden else '(none)'}",
        "사용자가 코드 작성 요청해도 거부. 응답: \"" + refusal + "\"",
        "phase 전환 필요시 먼저 `harness phase set <target>` 호출 후 진행.",
        "```",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ])
    return "\n".join(out)


def _machine_payload(
    *,
    status: str,
    phase: str,
    may_edit: bool,
    boundary: str,
    requires_user_approval: bool,
    next_command: Optional[str],
    next_user_prompt: Optional[str],
    warnings: Optional[list[str]] = None,
) -> str:
    payload = {
        "status": status,
        "phase": phase,
        "may_edit": may_edit,
        "boundary": boundary,
        "requires_user_approval": requires_user_approval,
        "next_command": next_command,
        "next_user_prompt": next_user_prompt,
        "warnings": warnings or [],
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _boundary_for_state(state: dict) -> str:
    phase = state.get("phase", "discuss")
    if phase == "execute" and bool(state.get("approved")):
        return "execute-approved"
    if phase in ("plan", "execute"):
        return "approval-required"
    return "plan-before-edit"


def _may_edit(state: dict) -> bool:
    phase = state.get("phase", "discuss")
    approved = bool(state.get("approved"))
    if phase != "execute" or not approved:
        return False
    approved_at = state.get("approved_at")
    baseline = state.get("execute_attempt_started_at")
    return bool(approved_at and baseline and approved_at >= baseline)


def _approval_prompt(state: dict) -> str:
    plan_id = state.get("plan_id") or "current-plan"
    return (
        f"Review the plan, then approve it from a real terminal "
        f"for plan {plan_id} before any application code edits."
    )


def _format_machine_next(state: dict) -> str:
    phase = state.get("phase", "discuss")
    requires_approval = phase in ("plan", "execute") and not _may_edit(state)
    return _machine_payload(
        status="ok",
        phase=phase,
        may_edit=_may_edit(state),
        boundary=_boundary_for_state(state),
        requires_user_approval=requires_approval,
        next_command=None if requires_approval else "harness run",
        next_user_prompt=_approval_prompt(state) if requires_approval else None,
    )


def _read_current_state_for_machine(cwd: Path) -> dict:
    state_path = cwd / SCRATCH_ROOT / STATE_NAME
    if not state_path.exists():
        return {"phase": "discuss", "execution_mode": "manual"}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"phase": "unknown", "execution_mode": "manual"}


def _walk_up_for_repo_root(start: Path) -> Path:
    """Walk parent directories looking for ``.git/`` or ``.harness/``.

    Returns the first ancestor directory that contains either marker.
    Raises ``FileNotFoundError`` if neither is found before the filesystem root.
    """
    cur = start.resolve()
    while True:
        if (cur / ".git").exists() or (cur / ".harness").exists():
            return cur
        if cur.parent == cur:
            raise FileNotFoundError(
                f"No .git/ or .harness/ directory found walking up from {start} "
                "to the filesystem root. Ensure you are inside a harness-managed "
                "repository before running status/next commands."
            )
        cur = cur.parent


def _cwd_repo_root() -> Path:
    """Return the repo root by walking up from CWD to the first .git/.harness ancestor."""
    return _walk_up_for_repo_root(Path.cwd())


def _read_state_with_preflight(
    *,
    scratch: Path,
    audit_path: Path,
    cwd: Path,
) -> tuple[Optional[dict], int]:
    """Read phase-state.json with plain JSON parse.

    ADR-0002: no attacker model; state-trust preflight removed in M4-3.
    A malformed state file surfaces as a parse error with a clear Fix: line.

    Returns (state_dict, exit_code). On error returns (None, exit_code).
    """
    state_path = scratch / STATE_NAME
    if not state_path.exists():
        # Bootstrap case: no state file yet — return defaults.
        return ({"phase": "discuss", "execution_mode": "manual"}, 0)

    state_bytes = state_path.read_bytes()
    if len(state_bytes) == 0:
        print(
            "error: harness status/next: state file present but empty (crash artefact) (exit 14).\n"
            "Fix: restore .scratch/phase-state.json via 'git checkout -- .scratch/phase-state.json' "
            "before any state-mutating verb.",
            file=sys.stderr,
        )
        return None, 14

    try:
        state = json.loads(state_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(
            f"error: harness status/next: state file not parseable: {exc}\n"
            f"Fix: restore via 'git checkout -- .scratch/phase-state.json'",
            file=sys.stderr,
        )
        return None, 5

    return state, 0


def cmd_status(args) -> int:
    """Handle ``harness status [--json]`` (§3.9).

    Walk up to repo root, read state + audit (brief lock for preflight,
    then released — NO lock during format/print), compute_status,
    format per args.json flag, print to stdout, return 0.
    """
    from . import status_next as _sn
    from . import phase_state as _phase_state

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: harness status refused: {exc}\n"
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    state, preflight_exit = _read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=cwd,
    )
    if state is None:
        return preflight_exit

    # Apply v2 defaults so all fields are present
    try:
        state = _phase_state.coerce_legacy_execution_mode(state)
    except ValueError:
        pass  # best-effort for status
    state = _phase_state.apply_v2_defaults(state)

    result = _sn.compute_status(state=state, audit_path=audit_path)

    use_json = getattr(args, "json", False)
    if use_json:
        sys.stdout.write(_sn.format_status_json(result))
    else:
        sys.stdout.write(_sn.format_status_human(result))

    return 0


def cmd_next(args) -> int:
    """Handle ``harness next [--shell | --json]`` (§3.9).

    Walk up + read state (brief lock for preflight, then released),
    compute_next, format per args.shell/args.json, return exit_code.
    """
    from . import status_next as _sn
    from . import phase_state as _phase_state

    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        print(
            f"error: harness next refused: {exc}\n"
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    scratch = cwd / SCRATCH_ROOT
    audit_path = cwd / AUDIT_PATH

    state, preflight_exit = _read_state_with_preflight(
        scratch=scratch,
        audit_path=audit_path,
        cwd=cwd,
    )
    if state is None:
        return preflight_exit

    # Apply v2 defaults so all fields are present
    try:
        state = _phase_state.coerce_legacy_execution_mode(state)
    except ValueError:
        pass  # best-effort for next
    state = _phase_state.apply_v2_defaults(state)

    result = _sn.compute_next(state=state, audit_path=audit_path)

    use_shell = getattr(args, "shell", False)
    use_json = getattr(args, "json", False)
    use_prompt = getattr(args, "prompt", False)

    if use_prompt:
        sys.stdout.write(_format_next_prompt(state, result))
        return 0

    if _machine_mode():
        sys.stdout.write(_format_machine_next(state))
        return 0

    if os.environ.get("HARNESS_ADVANCED") != "1" and not use_json and not use_shell:
        # Normal (non-advanced) surface: hide phase-internal commands from users.
        # Agent-safe transitions (discuss→plan, plan→execute, execute→done) are
        # all driven by `harness run`; only human-required steps (approval,
        # reopen) are exposed directly.  This preserves the daily-four UX:
        #   harness next → harness run → harness check  (no phase set needed).
        # The status "Next action:" line still shows the canonical command from
        # compute_next_action so power users with HARNESS_ADVANCED=1 or
        # harness status see the underlying transition (NEW-4 parity preserved).
        if result.agent_safe and result.exit_code == 0:
            sys.stdout.write(
                f"Recommended: {result.reason}\n"
                f"  Run: harness run\n"
            )
        elif result.command is not None:
            is_approve = result.command == "harness phase approve" or result.command.startswith(
                "harness phase approve "
            )
            if is_approve:
                sys.stdout.write(
                    f"Recommended: {result.reason}\n"
                    f"  Run from a real terminal: {result.command}\n"
                )
            else:
                sys.stdout.write(
                    f"Recommended: {result.reason}\n"
                    f"  Run: {result.command}\n"
                )
        else:
            phase = state.get("phase", "discuss")
            if phase == "done":
                sys.stdout.write("No action: workflow complete.\n")
            elif state.get("execution_mode", "manual") != "manual":
                sys.stdout.write("No action: autopilot active.\n")
            else:
                sys.stdout.write("No action: no action determined.\n")
        return 0

    if use_json:
        sys.stdout.write(_sn.format_next_json(result))
        return result.exit_code
    elif use_shell:
        text, exit_code = _sn.format_next_shell(result)
        if text:
            sys.stdout.write(text)
        # §3.9 Fix: line standard (S16) — emit Fix: to stderr on non-zero exits.
        if exit_code == 17:
            print(
                "Fix: run 'harness phase approve' (or the suggested command) "
                "from a real terminal to unblock the next step.",
                file=sys.stderr,
            )
        elif exit_code == 18:
            print(
                "Fix: run 'harness phase autopilot stop --reason \"<text>\"' "
                "to return to manual mode, then run 'harness next' again.",
                file=sys.stderr,
            )
        return exit_code
    else:
        sys.stdout.write(_sn.format_next_human(result))
        # §3.9 Fix: line standard (S16) — emit Fix: to stderr on non-zero exits.
        if result.exit_code == 17:
            print(
                "Fix: run 'harness phase approve' (or the suggested command) "
                "from a real terminal to unblock the next step.",
                file=sys.stderr,
            )
        elif result.exit_code == 18:
            print(
                "Fix: run 'harness phase autopilot stop --reason \"<text>\"' "
                "to return to manual mode, then run 'harness next' again.",
                file=sys.stderr,
            )
        return result.exit_code


def cmd_run(args) -> int:
    """Handle the v0.8 high-level ``harness run`` command.

    The normal path advances only agent-safe workflow transitions. It does not
    perform human approval; when approval is needed it emits a high-level prompt
    and stops.
    """
    try:
        cwd = _cwd_repo_root()
    except FileNotFoundError as exc:
        if _machine_mode():
            sys.stdout.write(
                _machine_payload(
                    status="error",
                    phase="unknown",
                    may_edit=False,
                    boundary="read-only",
                    requires_user_approval=False,
                    next_command="harness check",
                    next_user_prompt=None,
                    warnings=[str(exc)],
                )
            )
            return 6
        print(
            f"error: harness run refused: {exc}\n"
            "Fix: run from inside a harness-managed repository.",
            file=sys.stderr,
        )
        return 6

    state = _read_current_state_for_machine(cwd)
    phase = state.get("phase", "discuss")

    if phase == "discuss":
        # Use sys.argv[0] so that the installed copy of harness.py in the
        # target project is invoked, not the harness source tree's copy.
        # Falls back to __file__-relative resolution only when sys.argv[0]
        # does not look like a Python script (e.g. pytest runner).
        _argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0].endswith(".py") else None
        harness_py = str(_argv0 if _argv0 and _argv0.name == "harness.py" else Path(__file__).resolve().parents[1] / "harness.py")
        commands = [
            [sys.executable, harness_py, "phase", "set", "discuss"],
            [sys.executable, harness_py, "phase", "set", "plan"],
        ]
        result = None
        for command in commands:
            result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            if result.returncode:
                break
        if result is not None and result.returncode:
            if _machine_mode():
                sys.stdout.write(
                    _machine_payload(
                        status="error",
                        phase=phase,
                        may_edit=False,
                        boundary="plan-before-edit",
                        requires_user_approval=False,
                        next_command="harness check",
                        next_user_prompt=None,
                        warnings=[(result.stderr or result.stdout).strip()],
                    )
                )
                return result.returncode
            print(
                "harness run could not advance the workflow. "
                "Run `harness check` and `harness next` for the current safe action.",
                file=sys.stderr,
            )
            return result.returncode
        state = _read_current_state_for_machine(cwd)
        if _machine_mode():
            sys.stdout.write(_format_machine_next(state))
        else:
            sys.stdout.write(
                "Moved to plan. Review the plan, then approve it from a real terminal before edits.\n"
            )
        return 0

    if phase in ("plan", "execute") and not _may_edit(state):
        if _machine_mode():
            sys.stdout.write(_format_machine_next(state))
        else:
            sys.stdout.write(_approval_prompt(state) + "\n")
        return 0

    if _machine_mode():
        sys.stdout.write(_format_machine_next(state))
    else:
        sys.stdout.write("No safe workflow transition is needed right now.\n")
    return 0


def cmd_check_machine(
    exit_code: int,
    *,
    phase: str = "unknown",
    warnings: Optional[list[str]] = None,
) -> int:
    status = "ok" if exit_code == 0 else "error"
    sys.stdout.write(
            _machine_payload(
                status=status,
                phase=phase,
            may_edit=False,
            boundary="read-only",
            requires_user_approval=False,
            next_command="harness next",
            next_user_prompt=None,
            warnings=warnings or [],
        )
    )
    return exit_code


__all__ = [
    "cmd_status",
    "cmd_next",
    "cmd_run",
    "cmd_check_machine",
]
