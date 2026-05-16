"""T1-1 Task 2/3/4: pre-commit scope-check hook installer + E2E commit gate.

Plan: .planning/phases/02b-hardening/plans/02b-07-T1-1-PLAN.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "scripts" / "harness.py"
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import hooks  # noqa: E402


def _git_init(tmp: Path) -> None:
    subprocess.check_call(["git", "init", "-q"], cwd=tmp)
    subprocess.check_call(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "--allow-empty", "-q", "-m", "x"],
        cwd=tmp,
    )


def _make_target(allowed, *, with_harness_shim: bool = False):
    tmp = Path(tempfile.mkdtemp(prefix="t1-1-hooks-"))
    _git_init(tmp)
    (tmp / ".scratch").mkdir()
    (tmp / ".scratch/phase-state.json").write_text(json.dumps({
        "state_schema_version": 2,
        "phase": "execute",
        "approved": True,
        "plan_id": "T1-1-hooks",
        "allowed_paths": allowed,
        "blocked_paths": [],
        "verification": ["python3 -c 'pass'"],
    }))
    if with_harness_shim:
        # The pre-commit hook runs `python3 scripts/harness.py check
        # --worktree` from the tmp repo's root. Simulate an installed
        # target by writing a thin shim that invokes the source tree's
        # `worktree.check_worktree_paths(cwd)` directly, so the SystemExit
        # exit code propagates through the hook to git.
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts/harness.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r})\n"
            "from lib import worktree\n"
            "# Mimic `harness check --worktree` -- only that one verb.\n"
            "if 'check' in sys.argv and '--worktree' in sys.argv:\n"
            "    worktree.check_worktree_paths(Path.cwd())\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(0)\n"
        )
    return tmp


class InstallTests(unittest.TestCase):
    def test_install_creates_hook_when_absent(self):
        tmp = _make_target([".scratch/"])
        hooks.install_pre_commit_hook(tmp)
        hook = tmp / ".git/hooks/pre-commit"
        self.assertTrue(hook.exists())
        self.assertTrue(hook.stat().st_mode & 0o111)
        body = hook.read_text()
        self.assertIn(hooks.BEGIN_MARKER, body)
        self.assertIn(hooks.END_MARKER, body)
        self.assertIn("harness.py check --worktree", body)

    def test_install_is_idempotent(self):
        tmp = _make_target([".scratch/"])
        hooks.install_pre_commit_hook(tmp)
        first = (tmp / ".git/hooks/pre-commit").read_text()
        hooks.install_pre_commit_hook(tmp)
        second = (tmp / ".git/hooks/pre-commit").read_text()
        self.assertEqual(first, second)

    def test_install_appends_to_existing_hook(self):
        tmp = _make_target([".scratch/"])
        hook = tmp / ".git/hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho user-hook\n")
        hook.chmod(0o755)
        hooks.install_pre_commit_hook(tmp)
        body = hook.read_text()
        self.assertIn("echo user-hook", body)
        self.assertIn(hooks.BEGIN_MARKER, body)


class UninstallTests(unittest.TestCase):
    def test_uninstall_removes_block_keeps_user_content(self):
        tmp = _make_target([".scratch/"])
        hook = tmp / ".git/hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho user-hook\n")
        hook.chmod(0o755)
        hooks.install_pre_commit_hook(tmp)
        hooks.uninstall_pre_commit_hook(tmp)
        body = hook.read_text()
        self.assertIn("echo user-hook", body)
        self.assertNotIn("HARNESS:scope-check", body)

    def test_uninstall_removes_hook_if_we_created_it(self):
        tmp = _make_target([".scratch/"])
        hooks.install_pre_commit_hook(tmp)
        hooks.uninstall_pre_commit_hook(tmp)
        self.assertFalse((tmp / ".git/hooks/pre-commit").exists())

    def test_uninstall_when_absent_is_noop(self):
        tmp = _make_target([".scratch/"])
        # No raise.
        hooks.uninstall_pre_commit_hook(tmp)


class CLITests(unittest.TestCase):
    def test_cli_install_pre_commit(self):
        tmp = _make_target([".scratch/"])
        proc = subprocess.run(
            [sys.executable, str(HARNESS), "install", "--pre-commit",
             "--target", str(tmp)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertTrue((tmp / ".git/hooks/pre-commit").exists())

    def test_cli_uninstall_pre_commit(self):
        tmp = _make_target([".scratch/"])
        hooks.install_pre_commit_hook(tmp)
        proc = subprocess.run(
            [sys.executable, str(HARNESS), "uninstall", "--pre-commit",
             "--target", str(tmp)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertFalse((tmp / ".git/hooks/pre-commit").exists())


class E2ECommitTests(unittest.TestCase):
    def test_commit_outside_allowed_paths_is_blocked(self):
        tmp = _make_target([".scratch/", "docs/", "scripts/"], with_harness_shim=True)
        hooks.install_pre_commit_hook(tmp)
        (tmp / "scripts.py").write_text("x")
        subprocess.check_call(["git", "add", "scripts.py"], cwd=tmp)
        proc = subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "blocked"],
            cwd=tmp, capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("scripts.py", combined)
        self.assertIn("scope violation", combined)
        self.assertIn("docs/protocol-spec.md#scope-enforcement", combined)

    def test_commit_inside_allowed_paths_succeeds(self):
        tmp = _make_target([".scratch/", "docs/", "scripts/"], with_harness_shim=True)
        hooks.install_pre_commit_hook(tmp)
        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs/x.md").write_text("x")
        subprocess.check_call(["git", "add", "docs/x.md"], cwd=tmp)
        subprocess.check_call(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-m", "ok"],
            cwd=tmp,
        )


if __name__ == "__main__":
    unittest.main()
