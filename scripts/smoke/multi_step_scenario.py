"""Phase E Tier-2: multi-step env-aware scenario driver.

Drives a fresh `harness install`ed target through a discuss→done
lifecycle by feeding model responses one at a time. Designed for
orchestrator-driven dispatch: the caller provides each response via
`step()`, the driver applies commands and surfaces the next state.

Three env-context templates are exposed via `ENV_CONTEXTS` so the
orchestrator can vary prompt framing across claude-code / opencode-
emulated / roo-emulated runs while keeping workflow identical.

Live IDE behavior (real Roo/OpenCode prompt injection + tool wiring)
is NOT reproduced here. This is directional sanity for the workflow
itself across plausible env framings.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "scripts" / "harness.py"


ENV_CONTEXTS: dict[str, str] = {
    "claude-code": (
        "You operate inside Claude Code. Project memory lives in CLAUDE.md. "
        "You have the Bash tool and native subagent dispatch. Skills are "
        "loaded via the Skill tool. Slash commands are not adapter-specific."
    ),
    "opencode-emulated": (
        "You operate inside OpenCode. Project memory lives in AGENTS.md. "
        "Tool access is provided via MCP servers. Slash commands live under "
        ".opencode/commands/ (e.g. /discuss, /plan, /execute, /done) and "
        "shell verbs are also acceptable."
    ),
    "roo-emulated": (
        "You operate inside Roo Code (VSCode extension). You are in the "
        "orchestrator mode. Mode rules live under .roo/rules-orchestrator/, "
        "global rules under .roo/rules/global.md. Slash commands live under "
        ".roo/commands/. Shell verbs are also acceptable when no slash "
        "command applies."
    ),
}


@dataclass
class StepResult:
    iteration: int
    response_text: str
    executed_commands: list[list[str]] = field(default_factory=list)
    command_outputs: list[dict] = field(default_factory=list)
    state_before: dict | None = None
    state_after: dict | None = None
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "iteration": self.iteration,
                "response_text": self.response_text,
                "executed_commands": self.executed_commands,
                "command_outputs": self.command_outputs,
                "state_before": self.state_before,
                "state_after": self.state_after,
                "error": self.error,
            },
            indent=2,
            sort_keys=True,
        )


@dataclass
class Scenario:
    name: str
    env_label: str
    adapters: str  # one of: none, opencode, roo, both
    target_dir: Path
    goal: str
    expected_final_phase: str = "done"
    max_iterations: int = 10
    iteration: int = 0
    trace: list[StepResult] = field(default_factory=list)

    def state_path(self) -> Path:
        return self.target_dir / ".scratch" / "phase-state.json"

    def read_state(self) -> dict | None:
        p = self.state_path()
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def is_done(self) -> bool:
        s = self.read_state()
        return s is not None and s.get("phase") == self.expected_final_phase

    def build_prompt(self) -> str:
        state = self.read_state() or {}
        env_ctx = ENV_CONTEXTS[self.env_label]
        return (
            f"You are a low-reasoning agent operating the harness CLI inside "
            f"the following environment:\n\n{env_ctx}\n\n"
            f"Goal: {self.goal}\n\n"
            f"Current .scratch/phase-state.json:\n{json.dumps(state, indent=2)}\n\n"
            f"Issue the next CLI command(s) to make progress toward the goal. "
            f"Available verbs (POSIX shell): "
            f"'python3 scripts/harness.py phase set <discuss|plan|execute|done> "
            f"[--plan-id <id>] [--reset-approval]' and "
            f"'python3 scripts/harness.py phase approve --by <email>'. "
            f"Respond with shell-style commands only, one per line, OR a "
            f"single line beginning with 'needs-info:' if you cannot proceed."
        )


def init_target(scenario: Scenario) -> None:
    scenario.target_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HARNESS_USER"] = "tier2@example.com"
    subprocess.run(
        [sys.executable, str(HARNESS), "init",
         "--target", str(scenario.target_dir),
         "--adapters", scenario.adapters],
        check=True, capture_output=True, env=env,
    )


def _parse_commands(response_text: str) -> list[list[str]]:
    out: list[list[str]] = []
    for raw in response_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("needs-info:"):
            return []
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue
        if not tokens:
            continue
        out.append(tokens)
    return out


def _normalize_command(tokens: list[str]) -> list[str] | None:
    """Accept either `harness phase ...` or `python3 scripts/harness.py phase ...`.
    Returns the [sys.executable, HARNESS, ...] form, or None to reject."""
    if not tokens:
        return None
    if tokens[0] == "harness":
        return [sys.executable, str(HARNESS), *tokens[1:]]
    if (len(tokens) >= 2 and tokens[0] in ("python", "python3") and
            tokens[1].endswith("harness.py")):
        return [sys.executable, str(HARNESS), *tokens[2:]]
    return None


def step(scenario: Scenario, response_text: str) -> StepResult:
    scenario.iteration += 1
    result = StepResult(
        iteration=scenario.iteration,
        response_text=response_text,
        state_before=scenario.read_state(),
    )
    commands = _parse_commands(response_text)
    if not commands:
        result.error = "no commands parsed (or needs-info response)"
        result.state_after = scenario.read_state()
        scenario.trace.append(result)
        return result
    env = dict(os.environ)
    env["HARNESS_USER"] = "tier2@example.com"
    for tokens in commands:
        argv = _normalize_command(tokens)
        if argv is None:
            result.command_outputs.append({
                "raw": tokens,
                "rejected": "unknown command shape (not 'harness phase ...')",
            })
            continue
        proc = subprocess.run(
            argv, cwd=scenario.target_dir, capture_output=True, text=True, env=env,
        )
        result.executed_commands.append(argv)
        result.command_outputs.append({
            "argv": argv,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-400:],
            "stderr_tail": proc.stderr[-400:],
        })
    result.state_after = scenario.read_state()
    scenario.trace.append(result)
    return result


def write_evidence(scenario: Scenario, evidence_dir: Path) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / f"{scenario.name}.json"
    payload = {
        "scenario": scenario.name,
        "env_label": scenario.env_label,
        "adapters": scenario.adapters,
        "goal": scenario.goal,
        "expected_final_phase": scenario.expected_final_phase,
        "max_iterations": scenario.max_iterations,
        "iterations_used": scenario.iteration,
        "final_state": scenario.read_state(),
        "completed": scenario.is_done(),
        "trace": [json.loads(t.to_json()) for t in scenario.trace],
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out
