"""Per-trial runner with budget caps, flake retry, and evidence writer (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §6.4.

The runner is the measurement instrument: it drives a single fixture trial
through the model, dispatches the resulting shell commands to the harness
CLI in an isolated scratch dir, hands the post-state to the judge, applies
budget caps + flake-retry policy, and writes per-trial evidence JSON.

Budget caps (per spec §9.1, NOT prompt's narrower caps; see plan §2 rationale):
  - wall-clock ≤ 60 s
  - input_tokens ≤ 20_000
  - output_tokens ≤ 4_000

A trial that breaches ANY cap is recorded `passed=False`, `budget_caps_hit=[...]`
and is NOT retried (budget breach = real fitness signal, not flake).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .prepare_scratch import prepare_scratch_dir
from .judge import judge_response_for_fixture, JudgeResult

WALL_CLOCK_CAP_SECONDS = 60.0
INPUT_TOKEN_CAP = 20_000
OUTPUT_TOKEN_CAP = 4_000
MAX_RETRIES = 2

PINNED_MODEL = "claude-haiku-4-5-20251001"
PINNED_TEMPERATURE = 0.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS_CLI = _REPO_ROOT / "scripts" / "harness.py"


@dataclass
class TrialRecord:
    fixture_id: str
    trial_index: int
    model: str
    prompt: str
    response: str
    judgment: dict
    retry_count: int
    wall_clock_seconds: float
    input_tokens: int
    output_tokens: int
    budget_caps_hit: list = field(default_factory=list)
    noisy: bool = False
    commands_executed: list = field(default_factory=list)
    passed: bool = False
    # C2 honesty: monotonic wall clock above is what the budget enforces;
    # api_wall_seconds preserves the client-reported value (informational).
    api_wall_seconds: float = 0.0
    # C3 — transport-level trial failures (after HaikuClient retry budget).
    transport_error: bool = False
    # M1 — preserve lines that didn't parse as harness commands (don't drop).
    rejected_lines: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2) + "\n"


def _render_prompt(fixture: dict) -> str:
    state_json = json.dumps(fixture["initial_state"], sort_keys=True, indent=2)
    return fixture["prompt_template"].format(state=state_json)


def _parse_commands(response_text: str) -> tuple[list[list[str]], list[str]]:
    """Extract argv lists from `harness ...` lines.

    M1 — Returns `(commands, rejected_lines)` so the runner can preserve
    silently-dropped output in evidence. Empty lines are not rejected.
    Returns argv lists (without the leading `harness`).
    """
    cmds: list[list[str]] = []
    rejected: list[str] = []
    for raw in (response_text or "").splitlines():
        original = raw
        line = raw.strip().strip("`")
        if not line:
            continue
        # Strip `$ ` or `> ` shell prompts.
        for prefix in ("$ ", "> ", "% "):
            if line.startswith(prefix):
                line = line[len(prefix):]
        if line.startswith("python3 scripts/harness.py "):
            line = line[len("python3 scripts/harness.py "):]
        elif line.startswith("harness "):
            line = line[len("harness "):]
        else:
            rejected.append(original.strip())
            continue
        try:
            argv = shlex.split(line)
        except ValueError:
            rejected.append(original.strip())
            continue
        if argv:
            cmds.append(argv)
        else:
            rejected.append(original.strip())
    return cmds, rejected


def _pinned_env(cwd: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "HARNESS_USER": "smoke-e",
        "GIT_AUTHOR_NAME": "smoke-e",
        "GIT_AUTHOR_EMAIL": "smoke-e@local",
        "GIT_COMMITTER_NAME": "smoke-e",
        "GIT_COMMITTER_EMAIL": "smoke-e@local",
    }


def _run_command(argv: list[str], cwd: Path) -> dict:
    cp = subprocess.run(
        [sys.executable, str(_HARNESS_CLI), *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
        env=_pinned_env(cwd),
        check=False,
    )
    return {
        "cmd": argv,
        "exit": cp.returncode,
        "stdout_tail": (cp.stdout or "")[-2000:],
        "stderr_tail": (cp.stderr or "")[-2000:],
    }


def _budget_caps_hit(wall: float, input_tokens: int, output_tokens: int) -> list[str]:
    hits = []
    if wall > WALL_CLOCK_CAP_SECONDS:
        hits.append("wall_clock")
    if input_tokens > INPUT_TOKEN_CAP:
        hits.append("input_tokens")
    if output_tokens > OUTPUT_TOKEN_CAP:
        hits.append("output_tokens")
    return hits


def _is_live_client(client) -> bool:
    """C4 — detect HaikuClient (live API) vs FakeClient (unit-test double).

    Judge invariants are only enforced under live mode, since FakeClient
    cannot actually mutate filesystem state via subprocess calls.
    """
    return type(client).__name__ == "HaikuClient"


def _evidence_path(evidence_root: Path, fixture: dict, trial_index: int) -> Path:
    flow_dir = Path(evidence_root) / fixture["flow"]
    flow_dir.mkdir(parents=True, exist_ok=True)
    return flow_dir / f"trial-{trial_index:03d}.json"


def _attempts_dir(evidence_root: Path, fixture: dict, trial_index: int) -> Path:
    flow_dir = Path(evidence_root) / fixture["flow"]
    attempts = flow_dir / f"trial-{trial_index:03d}-attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    return attempts


def _single_attempt(
    fixture: dict,
    trial_index: int,
    model_client,
    scratch_root: Path,
    attempt_label: str,
) -> tuple[JudgeResult, TrialRecord, Path]:
    dest = Path(scratch_root) / f"trial-{fixture['fixture_id']}-{trial_index:03d}-{attempt_label}"
    if dest.exists():
        # Wipe stale dir for reproducibility (deterministic fixture rewrite).
        import shutil

        shutil.rmtree(dest)
    prepare_scratch_dir(fixture, dest)
    prompt = _render_prompt(fixture)
    t0 = time.monotonic()
    try:
        response = model_client.respond(prompt)
    except Exception as exc:
        # C3 — HaikuClient raises HttpTransportError after exhausting the
        # 429/5xx retry budget. Record as trial-level fail; do not abort suite.
        try:
            from .model_client import HttpTransportError
        except Exception:  # pragma: no cover
            HttpTransportError = ()
        if HttpTransportError and isinstance(exc, HttpTransportError):
            wall = time.monotonic() - t0
            record = TrialRecord(
                fixture_id=fixture["fixture_id"],
                trial_index=trial_index,
                model=PINNED_MODEL,
                prompt=prompt,
                response="",
                judgment={
                    "passed": False,
                    "reason": f"transport error: {exc}",
                    "retry_recommended": False,
                },
                retry_count=0,
                wall_clock_seconds=wall,
                input_tokens=0,
                output_tokens=0,
                budget_caps_hit=[],
                commands_executed=[],
                passed=False,
                api_wall_seconds=0.0,
                transport_error=True,
            )
            return (
                JudgeResult(False, f"transport error: {exc}", retry_recommended=False),
                record,
                dest,
            )
        raise
    # C2 — honest wall clock: budget uses ONLY the real monotonic delta.
    # The client-reported time is preserved as informational `api_wall_seconds`.
    wall = time.monotonic() - t0
    api_wall = float(getattr(response, "wall_clock_seconds", 0.0) or 0.0)

    # Defensive: pin model + temperature on every call.
    last = getattr(model_client, "last_call", {}) or {}
    if last:
        assert last.get("model") == PINNED_MODEL, (
            f"runner: model not pinned (got {last.get('model')!r}, "
            f"expected {PINNED_MODEL!r})"
        )
        assert last.get("temperature") == PINNED_TEMPERATURE, (
            f"runner: temperature not pinned (got {last.get('temperature')!r})"
        )

    caps_hit = _budget_caps_hit(wall, response.input_tokens, response.output_tokens)
    commands_log: list[dict] = []
    parsed_cmds: list[list[str]] = []
    rejected: list[str] = []
    if not caps_hit:
        parsed_cmds, rejected = _parse_commands(response.text)
        for argv in parsed_cmds:
            commands_log.append(_run_command(argv, dest))

    if caps_hit:
        judgment = JudgeResult(False, f"budget caps hit: {caps_hit}", retry_recommended=False)
    else:
        judgment = judge_response_for_fixture(
            fixture, dest, response.text, live_mode=_is_live_client(model_client)
        )

    record = TrialRecord(
        fixture_id=fixture["fixture_id"],
        trial_index=trial_index,
        model=PINNED_MODEL,
        prompt=prompt,
        response=response.text,
        judgment={
            "passed": judgment.passed,
            "reason": judgment.reason,
            "retry_recommended": judgment.retry_recommended,
        },
        retry_count=0,  # filled in by caller
        wall_clock_seconds=wall,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        budget_caps_hit=caps_hit,
        commands_executed=commands_log,
        passed=judgment.passed and not caps_hit,
        api_wall_seconds=api_wall,
        rejected_lines=rejected,
    )
    return judgment, record, dest


def run_trial(
    fixture: dict,
    trial_index: int,
    model_client,
    scratch_root: Path,
    evidence_root: Path,
) -> TrialRecord:
    """Run one trial with up to MAX_RETRIES re-attempts on judge-recommended flake."""
    scratch_root = Path(scratch_root)
    scratch_root.mkdir(parents=True, exist_ok=True)

    attempts_dir = _attempts_dir(evidence_root, fixture, trial_index)

    def _persist_attempt(attempt_no: int, rec: TrialRecord) -> None:
        # Preserve full per-attempt record (including failure signal).
        path = attempts_dir / f"attempt-{attempt_no}.json"
        path.write_text(rec.to_json(), encoding="utf-8")

    judgment, record, _ = _single_attempt(
        fixture, trial_index, model_client, scratch_root, attempt_label="orig"
    )
    _persist_attempt(1, record)
    retry_count = 0
    while (
        not record.passed
        and not record.budget_caps_hit
        and retry_count < MAX_RETRIES
    ):
        retry_count += 1
        judgment, record, _ = _single_attempt(
            fixture, trial_index, model_client, scratch_root, attempt_label=f"retry-{retry_count}"
        )
        _persist_attempt(retry_count + 1, record)

    record.retry_count = retry_count
    record.noisy = retry_count > 0
    out = _evidence_path(evidence_root, fixture, trial_index)
    out.write_text(record.to_json(), encoding="utf-8")
    # Also write the canonical final-result file inside the attempts dir.
    (attempts_dir / "result.json").write_text(record.to_json(), encoding="utf-8")
    return record
