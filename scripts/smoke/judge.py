"""Programmatic judge for low-reasoning scenario trials (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §6.3.

No LLM-as-judge: every pass/fail decision is structural — parse final
`.scratch/phase-state.json`, inspect `.harness/audit.log`, assert against
the fixture's expected post-conditions. All exit-code comparisons import
`EXIT_*` constants from `scripts.lib.exitcodes`; all verification-prefix
checks import `VERIFICATION_PREFIXES` from `scripts.lib.check`; all state
parsing routes through `scripts.lib.state_diagnostics.load_state_json`.
"""
from __future__ import annotations

import errno
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class AuditLogSymlinkError(RuntimeError):
    """SecM4 — raised when `.harness/audit.log` is a symlink (O_NOFOLLOW guard)."""

# Make the bare `lib.*` imports inside state_diagnostics work.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from lib.exitcodes import (  # noqa: E402  (after sys.path tweak)
    EXIT_OK,
    EXIT_INVALID_TRANSITION,
    EXIT_SCOPE_VIOLATION,
    EXIT_UNPARSEABLE_JSON,
    EXIT_WRONG_PHASE_FOR_VERB,
)
from lib.check import VERIFICATION_PREFIXES  # noqa: E402
from lib.state_diagnostics import load_state_json  # noqa: E402


__all__ = [
    "JudgeResult",
    "judge_fixture_01",
    "judge_fixture_02",
    "judge_fixture_03",
    "judge_fixture_04",
    "judge_response_for_fixture",
]


@dataclass(frozen=True)
class JudgeResult:
    passed: bool
    reason: str
    retry_recommended: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_state(scratch_dir: Path) -> dict | None:
    state_path = Path(scratch_dir) / ".scratch" / "phase-state.json"
    if not state_path.exists():
        return None
    try:
        return load_state_json(state_path)
    except SystemExit as exc:
        # C5 — only EXIT_UNPARSEABLE_JSON (code 5) is treated as a structural
        # "state unreadable" signal; any other exit code is a genuine bug
        # in the diagnostics layer and must propagate, not be silently
        # converted to a judge-fail.
        if exc.code == EXIT_UNPARSEABLE_JSON:
            return None
        raise


def _read_audit(scratch_dir: Path) -> list[dict]:
    log = Path(scratch_dir) / ".harness" / "audit.log"
    if not log.exists() and not log.is_symlink():
        return []
    # SecM4 — open via O_NOFOLLOW so a symlinked audit.log cannot redirect
    # the judge to read attacker-chosen content. ELOOP -> AuditLogSymlinkError.
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(log), os.O_RDONLY | nofollow)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise AuditLogSymlinkError(
                f"audit.log is a symlink (refused): {log}"
            ) from exc
        raise
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A garbled audit line is a hard fail; record as opaque dict.
            out.append({"_unparseable": line})
    return out


def _is_grounded_needs_info(response_text: str, fixture: dict) -> bool:
    """True iff response is a `needs-info:` line containing at least one
    keyword from the fixture's `diagnostic_keywords` list."""
    if not response_text:
        return False
    lowered = response_text.strip().lower()
    if not lowered.startswith("needs-info:"):
        return False
    keywords = [k.lower() for k in fixture.get("diagnostic_keywords", [])]
    return any(k in lowered for k in keywords)


def _orphan_lockfile_present(scratch_dir: Path) -> bool:
    return (Path(scratch_dir) / ".harness" / "session.lock").exists()


def _spurious_backup_present(scratch_dir: Path) -> bool:
    backups = Path(scratch_dir) / ".harness" / "backups"
    if not backups.is_dir():
        return False
    return any(backups.glob("*.bak"))


def _verification_entries_ok(state: dict) -> tuple[bool, str]:
    ver = state.get("verification") or []
    if not isinstance(ver, list):
        return (False, "verification field not a list")
    for entry in ver:
        if not isinstance(entry, str):
            return (False, f"verification entry not string: {entry!r}")
        if entry.startswith("bash "):
            return (False, "verification entry uses removed 'bash ' verb")
        if not entry.startswith(VERIFICATION_PREFIXES):
            return (
                False,
                f"verification entry {entry!r} not in 7-verb allowlist",
            )
    return (True, "")


def _post_trial_environment_check(
    scratch_dir: Path, live_mode: bool = False
) -> tuple[bool, str]:
    """Environment-level checks: no orphan lockfile, no spurious .bak.

    C4 — Only enforced in live mode. In FakeClient mode the model never
    actually shells out to the harness CLI, so it cannot produce a real
    lockfile or backup; treating those as failures was a false-positive
    vector. Tests that want the live behavior pass `live_mode=True`.
    """
    if not live_mode:
        return (True, "")
    if _orphan_lockfile_present(scratch_dir):
        return (False, "orphan session lockfile after trial completion")
    if _spurious_backup_present(scratch_dir):
        return (False, "spurious .bak file present (no repair was invoked)")
    return (True, "")


# Back-compat alias (existing internal callers).
_post_trial_invariants = _post_trial_environment_check


# ---------------------------------------------------------------------------
# Per-fixture judges
# ---------------------------------------------------------------------------


def judge_fixture_01(scratch_dir: Path, fixture: dict, response_text: str = "", live_mode: bool = False) -> JudgeResult:
    """discuss -> plan."""
    if _is_grounded_needs_info(response_text, fixture):
        return JudgeResult(True, "grounded needs-info response")
    if response_text.strip().lower().startswith("needs-info:"):
        return JudgeResult(
            False, "needs-info not grounded in fixture diagnostic"
        )
    state = _read_state(scratch_dir)
    if state is None:
        return JudgeResult(False, "phase-state.json missing or unparseable after trial")
    phase = state.get("phase")
    if phase == "discuss":
        return JudgeResult(
            False,
            "agent did not invoke 'harness phase set plan'",
            retry_recommended=True,
        )
    if phase != "plan":
        return JudgeResult(False, f"agent overshot target phase (got {phase!r})")
    inv_ok, inv_reason = _post_trial_environment_check(scratch_dir, live_mode=live_mode)
    if not inv_ok:
        return JudgeResult(False, inv_reason)
    return JudgeResult(True, "phase advanced from discuss to plan")


def judge_fixture_02(scratch_dir: Path, fixture: dict, response_text: str = "", live_mode: bool = False) -> JudgeResult:
    """plan -> approved (plan stays plan but approved=True and plan_id populated)."""
    if _is_grounded_needs_info(response_text, fixture):
        return JudgeResult(True, "grounded needs-info response")
    if response_text.strip().lower().startswith("needs-info:"):
        return JudgeResult(False, "needs-info not grounded in fixture diagnostic")
    state = _read_state(scratch_dir)
    if state is None:
        return JudgeResult(False, "phase-state.json missing or unparseable after trial")
    # M3 — phase must remain "plan"; any other value means the agent
    # advanced or regressed instead of approving the plan in place.
    if state.get("phase") != "plan":
        return JudgeResult(
            False,
            f"phase must be 'plan' for fixture-02 (got {state.get('phase')!r})",
        )
    approved = bool(state.get("approved"))
    plan_id = state.get("plan_id")
    if approved and not plan_id:
        return JudgeResult(
            False,
            "agent fabricated approval without populating plan",
        )
    if not approved:
        return JudgeResult(
            False, "agent did not invoke 'harness phase approve'", retry_recommended=True
        )
    if not plan_id:
        return JudgeResult(False, "plan_id remains null after trial")
    inv_ok, inv_reason = _post_trial_environment_check(scratch_dir, live_mode=live_mode)
    if not inv_ok:
        return JudgeResult(False, inv_reason)
    return JudgeResult(True, "plan populated and approved")


def judge_fixture_03(scratch_dir: Path, fixture: dict, response_text: str = "", live_mode: bool = False) -> JudgeResult:
    """execute -> done. Verification entries must persist and be in allowlist."""
    if _is_grounded_needs_info(response_text, fixture):
        return JudgeResult(True, "grounded needs-info response")
    if response_text.strip().lower().startswith("needs-info:"):
        return JudgeResult(False, "needs-info not grounded in fixture diagnostic")
    state = _read_state(scratch_dir)
    if state is None:
        return JudgeResult(False, "phase-state.json missing or unparseable after trial")
    if state.get("phase") != "done":
        return JudgeResult(
            False,
            f"agent did not reach phase=done (got {state.get('phase')!r})",
            retry_recommended=True,
        )
    ver = state.get("verification") or []
    if not ver:
        return JudgeResult(False, "phase=done with empty verification array")
    ok, reason = _verification_entries_ok(state)
    if not ok:
        return JudgeResult(False, reason)
    audit = _read_audit(scratch_dir)
    if not any(
        e.get("verb") == "phase.set" and (e.get("args") or {}).get("phase") == "done"
        for e in audit
    ):
        return JudgeResult(False, "audit log missing phase.set:done entry")
    inv_ok, inv_reason = _post_trial_environment_check(scratch_dir, live_mode=live_mode)
    if not inv_ok:
        return JudgeResult(False, inv_reason)
    return JudgeResult(True, "execute advanced to done; verification preserved")


def _audit_sequence_matches(audit: list[dict], expected: list[dict]) -> tuple[bool, str]:
    """Filter audit to the expected verbs (in order) and assert ordering."""
    expected_verbs = [e["verb"] for e in expected]
    actual_verbs = [
        e.get("verb") for e in audit if e.get("verb") in {"phase.set", "phase.approve"}
    ]
    # Sub-sequence containment: each expected verb must appear in order
    # within actual_verbs, with phase args matching when supplied.
    i = 0
    for exp in expected:
        found_at = -1
        for j in range(i, len(audit)):
            entry = audit[j]
            if entry.get("verb") != exp["verb"]:
                continue
            if exp["verb"] == "phase.set":
                if (entry.get("args") or {}).get("phase") != exp.get("phase"):
                    continue
            found_at = j
            break
        if found_at < 0:
            return (
                False,
                f"audit missing expected entry {exp!r}; actual verb sequence: {actual_verbs}",
            )
        i = found_at + 1
    # Also forbid execute or done without an approve in between.
    set_done_idx = None
    set_exec_idx = None
    for k, e in enumerate(audit):
        if e.get("verb") == "phase.set":
            ph = (e.get("args") or {}).get("phase")
            if ph == "execute" and set_exec_idx is None:
                set_exec_idx = k
            if ph == "done" and set_done_idx is None:
                set_done_idx = k
    # Walk and confirm an approve precedes each gated transition.
    for gated_idx, label in ((set_exec_idx, "execute"), (set_done_idx, "done")):
        if gated_idx is None:
            continue
        if not any(
            audit[m].get("verb") == "phase.approve" for m in range(gated_idx)
        ):
            return (False, f"lifecycle skipped approval gate before {label}")
    return (True, "")


def judge_fixture_04(scratch_dir: Path, fixture: dict, response_text: str = "", live_mode: bool = False) -> JudgeResult:
    """Full lifecycle discuss -> plan -> approve -> execute -> approve -> done."""
    if _is_grounded_needs_info(response_text, fixture):
        return JudgeResult(True, "grounded needs-info response")
    if response_text.strip().lower().startswith("needs-info:"):
        return JudgeResult(False, "needs-info not grounded in fixture diagnostic")
    state = _read_state(scratch_dir)
    if state is None:
        return JudgeResult(False, "phase-state.json missing or unparseable after trial")
    if state.get("phase") != "done":
        return JudgeResult(
            False,
            f"agent did not complete lifecycle (final phase={state.get('phase')!r})",
            retry_recommended=True,
        )
    audit = _read_audit(scratch_dir)
    expected = fixture.get("expected_audit_sequence") or [
        {"verb": "phase.set", "phase": "plan"},
        {"verb": "phase.approve"},
        {"verb": "phase.set", "phase": "execute"},
        {"verb": "phase.approve"},
        {"verb": "phase.set", "phase": "done"},
    ]
    ok, reason = _audit_sequence_matches(audit, expected)
    if not ok:
        return JudgeResult(False, reason)
    inv_ok, inv_reason = _post_trial_environment_check(scratch_dir, live_mode=live_mode)
    if not inv_ok:
        return JudgeResult(False, inv_reason)
    return JudgeResult(True, "full lifecycle traversed with required approvals")


JUDGE_DISPATCH = {
    "fixture-01-discuss-then-plan": judge_fixture_01,
    "fixture-02-plan-then-approve": judge_fixture_02,
    "fixture-03-execute-then-done": judge_fixture_03,
    "fixture-04-full-lifecycle": judge_fixture_04,
}


def judge_response_for_fixture(
    fixture: dict, scratch_dir: Path, response_text: str, live_mode: bool = False
) -> JudgeResult:
    judge = JUDGE_DISPATCH.get(fixture["fixture_id"])
    if judge is None:
        raise KeyError(f"no judge for fixture_id={fixture['fixture_id']!r}")
    return judge(scratch_dir, fixture, response_text, live_mode=live_mode)


# Re-export referenced constants for clarity (so meta-tests confirm the
# judge does not embed numeric literals).
_EXIT_CODES_USED = (
    EXIT_OK,
    EXIT_INVALID_TRANSITION,
    EXIT_SCOPE_VIOLATION,
    EXIT_UNPARSEABLE_JSON,
    EXIT_WRONG_PHASE_FOR_VERB,
)
