"""T1-1: regression for `check --worktree` exit code on scope violation.

CONTRACT-PIN §4: `EXIT_SCOPE_VIOLATION = 4`. The worktree scan must
exit with code 4 (not 1) when changed paths fall outside `allowed_paths`,
and code 0 on clean trees or when the gate is not applicable (e.g.,
phase=plan). Tests assert via `exitcodes.EXIT_SCOPE_VIOLATION` (no raw `4`
literal) per CONTRACT-PIN §1.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import worktree  # noqa: E402
from lib.exitcodes import EXIT_SCOPE_VIOLATION  # noqa: E402


def _git_init_with_state(allowed, blocked=None, phase="execute", approved=True):
    tmp = Path(tempfile.mkdtemp(prefix="t1-1-"))
    subprocess.check_call(["git", "init", "-q"], cwd=tmp)
    subprocess.check_call(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "x"],
        cwd=tmp,
    )
    (tmp / ".scratch").mkdir()
    (tmp / ".scratch/phase-state.json").write_text(json.dumps({
        "state_schema_version": 2,
        "phase": phase,
        "approved": approved,
        "plan_id": "T1-1-test",
        "allowed_paths": allowed,
        "blocked_paths": blocked or [],
        "verification": ["python3 -c 'pass'"],
    }))
    return tmp


class WorktreeExitCodeTests(unittest.TestCase):
    """Library-level assertions on the SystemExit code emitted by worktree."""

    def test_violation_exits_4(self):
        tmp = _git_init_with_state(["docs/"])
        (tmp / "scripts.py").write_text("x")
        buf = io.StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as cm:
            worktree.check_worktree_paths(tmp)
        self.assertEqual(cm.exception.code, EXIT_SCOPE_VIOLATION)
        stderr = buf.getvalue()
        self.assertIn("scripts.py", stderr)
        self.assertIn("scope violation", stderr)
        self.assertIn("allowed_paths", stderr)
        self.assertIn("docs/protocol-spec.md#scope-enforcement", stderr)

    def test_clean_exits_0(self):
        # Include `.scratch/` in allowed_paths because the fixture writes
        # phase-state.json as an untracked file under that directory.
        tmp = _git_init_with_state(["docs/", ".scratch/"])
        (tmp / "docs").mkdir()
        (tmp / "docs/x.md").write_text("x")
        # No raise → returns None (exit 0 at CLI boundary).
        worktree.check_worktree_paths(tmp)

    def test_phase_plan_does_not_enforce(self):
        # Gate refuses to enforce in phase=plan; still raises SystemExit
        # (the gate refusal message), but the hook treats this as
        # "scope-check not applicable" → exit 0 via the shell wrapper.
        # Library raises with a non-EXIT_SCOPE_VIOLATION code so the hook
        # can distinguish; we assert the code is NOT 4.
        tmp = _git_init_with_state(["docs/"], phase="plan", approved=False)
        (tmp / "scripts.py").write_text("x")
        with self.assertRaises(SystemExit) as cm:
            worktree.check_worktree_paths(tmp)
        self.assertNotEqual(cm.exception.code, EXIT_SCOPE_VIOLATION)


class WorktreeBlockedOverridesAllowedTests(unittest.TestCase):
    """ADR-002 (a): blocked_paths overrides allowed_paths → exit 4."""

    def test_blocked_glob_path_exits_4(self):
        tmp = _git_init_with_state(["src/"], blocked=["src/*.py"])
        (tmp / "src").mkdir()
        (tmp / "src/main.py").write_text("x")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            worktree.check_worktree_paths(tmp)
        self.assertEqual(cm.exception.code, EXIT_SCOPE_VIOLATION)


if __name__ == "__main__":
    unittest.main()
