"""Worktree scope checks: gate by allowed/blocked paths."""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path
from typing import Iterable

from lib.roadmap_state import normalize_path


def check_changed_paths(target: Path, base: str) -> None:
    import json

    state_path = target / ".scratch/phase-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not changed_path_gate_allows_state(state):
        raise SystemExit("Changed-path check requires phase=execute with approved=true or phase=done with approved=false")
    changed = git_changed_paths(target, base)
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Changed paths outside allowed_paths: " + ", ".join(denied))


def check_worktree_paths(target: Path) -> None:
    import json

    state = json.loads((target / ".scratch/phase-state.json").read_text(encoding="utf-8"))
    if not changed_path_gate_allows_state(state):
        raise SystemExit("Worktree changed-path check requires phase=execute with approved=true or phase=done with approved=false")
    changed = sorted(set(git_worktree_paths(target)))
    denied = [
        path
        for path in changed
        if not path_allowed(path, state.get("allowed_paths", []), state.get("blocked_paths", []))
    ]
    if denied:
        raise SystemExit("Worktree paths outside allowed_paths: " + ", ".join(denied))


def changed_path_gate_allows_state(state: dict[str, object]) -> bool:
    return (state.get("phase") == "execute" and state.get("approved") is True) or (
        state.get("phase") == "done" and state.get("approved") is False
    )


def git_changed_paths(target: Path, base: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=target,
        text=True,
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def git_worktree_paths(target: Path) -> list[str]:
    outputs = [
        subprocess.check_output(["git", "diff", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=target, text=True),
        subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=target, text=True),
    ]
    return [line.strip() for output in outputs for line in output.splitlines() if line.strip()]


def path_allowed(path: str, allowed: Iterable[str], blocked: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    if matches_any(normalized, blocked):
        return False
    return matches_any(normalized, allowed)


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        normalized = normalize_path(pattern)
        if normalized.endswith("/"):
            if path.startswith(normalized):
                return True
        elif path == normalized:
            return True
    return False


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def is_text_file(path: Path) -> bool:
    return path.suffix in {".md", ".json", ".txt", ".yml", ".yaml", ".toml", ".sh", ".py"} or path.name in {
        "AGENTS.md",
        ".roomodes",
        ".gitignore",
    }
