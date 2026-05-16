"""T1-1: install/uninstall the harness pre-commit scope-check hook.

Plan: .planning/phases/02b-hardening/plans/02b-07-T1-1-PLAN.md Task 2.
Contract: CONTRACT-PIN §4 (exit code 4 = EXIT_SCOPE_VIOLATION).

The hook calls `python3 scripts/harness.py check --worktree` from the
repo root and exits non-zero (4 on scope violation) to block the commit.

Marker envelope: `# HARNESS:scope-check-begin` / `# HARNESS:scope-check-end`.
This is the shell-comment analogue of the HTML-comment managed-block
discipline in `scripts/lib/managed_block.py` — the same "begin/end label
with idempotent replace" pattern, adapted for POSIX `sh` hooks where HTML
comments are not valid syntax.

The installer does NOT touch `git config core.hooksPath`; it writes
`.git/hooks/pre-commit` directly so uninstall is a single `rm` (or a
markered-block surgical removal when the user has authored other hook
content).
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

# Public skeleton location — single source of truth for the hook body.
_SKELETON_HOOK = (
    Path(__file__).resolve().parents[2]
    / "harness"
    / "skeleton"
    / "clean"
    / ".githooks"
    / "pre-commit-scope"
)

BEGIN_MARKER = "# HARNESS:scope-check-begin"
END_MARKER = "# HARNESS:scope-check-end"


def _hook_path(target: Path) -> Path:
    return target / ".git" / "hooks" / "pre-commit"


def _assert_is_git_worktree(target: Path) -> None:
    """T1-1-C1: refuse to install if ``target`` is not a git worktree.

    The hook lives at ``<target>/.git/hooks/pre-commit`` — git only invokes
    it when commits happen INSIDE that worktree. Plain directories silently
    accept the file but never run it, producing a false sense of safety.

    A ``.git`` directory check alone misses the case where ``target`` is a
    subdirectory of an outer repo (here ``.git`` doesn't exist locally but
    ``git rev-parse --show-toplevel`` resolves UP to the outer root, which
    the caller almost certainly did not mean). Combining both checks yields
    a tight "this exact path is a worktree root" predicate.
    """
    git_dir = target / ".git"
    if not git_dir.is_dir():
        raise SystemExit(
            f"target {target} is not a git worktree; "
            f"--pre-commit requires a git repo"
        )
    try:
        subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--git-dir"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise SystemExit(
            f"target {target} is not a git worktree; "
            f"--pre-commit requires a git repo"
        )


def _read_skeleton() -> str:
    return _SKELETON_HOOK.read_text(encoding="utf-8")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def hook_is_installed(target: Path) -> bool:
    hook = _hook_path(target)
    if not hook.exists():
        return False
    body = hook.read_text(encoding="utf-8")
    return BEGIN_MARKER in body and END_MARKER in body


def _extract_managed_block(skeleton_text: str) -> str:
    """Return the begin..end block (inclusive) from the skeleton body."""
    lines = skeleton_text.splitlines(keepends=True)
    start = None
    end = None
    for index, line in enumerate(lines):
        if BEGIN_MARKER in line and start is None:
            start = index
        if END_MARKER in line:
            end = index
            break
    if start is None or end is None:
        raise RuntimeError(
            f"skeleton {_SKELETON_HOOK} is missing scope-check markers"
        )
    return "".join(lines[start : end + 1])


def install_pre_commit_hook(target: Path) -> None:
    """Install the scope-check pre-commit hook into `target`.

    Behavior:
      - If `.git/hooks/pre-commit` does not exist: write the full skeleton
        (shebang + managed block) and `chmod +x`.
      - If it exists and already contains our marker envelope: re-render
        the envelope in place (idempotent — bit-identical re-runs).
      - If it exists without our marker envelope: append the marker
        envelope after the existing content, preserving the user's hook
        body.
    """
    target = target.resolve()
    _assert_is_git_worktree(target)
    hook = _hook_path(target)
    hook.parent.mkdir(parents=True, exist_ok=True)
    skeleton = _read_skeleton()
    managed_block = _extract_managed_block(skeleton)

    if not hook.exists():
        hook.write_text(skeleton, encoding="utf-8")
        _make_executable(hook)
        return

    existing = hook.read_text(encoding="utf-8")
    if BEGIN_MARKER in existing and END_MARKER in existing:
        # Replace existing managed block in place (idempotent).
        before, _, rest = existing.partition(BEGIN_MARKER)
        if END_MARKER + "\n" in rest:
            _, _, after = rest.partition(END_MARKER + "\n")
        else:
            # Trailing newline absent on END_MARKER line; partition without it.
            _, _, after = rest.partition(END_MARKER)
        new_body = before + managed_block + after
        if new_body != existing:
            hook.write_text(new_body, encoding="utf-8")
        _make_executable(hook)
        return

    # Append the managed block to the existing user-authored hook.
    suffix = "" if existing.endswith("\n") else "\n"
    new_body = existing + suffix + managed_block
    # Normalize to a single trailing newline so a second install is a no-op.
    new_body = new_body.rstrip("\n") + "\n"
    hook.write_text(new_body, encoding="utf-8")
    _make_executable(hook)


def uninstall_pre_commit_hook(target: Path) -> None:
    """Remove the scope-check marker envelope from the pre-commit hook.

    - If the hook does not exist: no-op.
    - If the hook contains ONLY the marker envelope (i.e., we wrote the
      whole file at install time): remove the file entirely.
    - Otherwise: surgically excise the marker envelope, preserving any
      user-authored content before/after it.
    """
    target = target.resolve()
    hook = _hook_path(target)
    if not hook.exists():
        return
    existing = hook.read_text(encoding="utf-8")
    if BEGIN_MARKER not in existing or END_MARKER not in existing:
        return

    before, _, rest = existing.partition(BEGIN_MARKER)
    if END_MARKER + "\n" in rest:
        _, _, after = rest.partition(END_MARKER + "\n")
    else:
        _, _, after = rest.partition(END_MARKER)

    # Strip a trailing blank line that the install path may have added
    # between the user content and our managed block.
    cleaned = (before.rstrip("\n") + ("\n" + after.lstrip("\n") if after.strip() else "")).strip("\n")

    # Treat "only the original shebang + skeleton header" as "we created
    # this file" — remove it entirely so a future install path is clean.
    stripped_before = before.strip()
    if (
        not after.strip()
        and (
            stripped_before == ""
            or stripped_before == "#!/bin/sh"
        )
    ):
        try:
            hook.unlink()
        except FileNotFoundError:  # pragma: no cover
            pass
        return

    if cleaned and not cleaned.endswith("\n"):
        cleaned = cleaned + "\n"
    hook.write_text(cleaned, encoding="utf-8")
    _make_executable(hook)


__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "hook_is_installed",
    "install_pre_commit_hook",
    "uninstall_pre_commit_hook",
]
