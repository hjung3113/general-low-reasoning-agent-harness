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

    def test_install_is_idempotent_with_existing_user_hook(self):
        """T1-1-M1: appending the managed block to a pre-existing user
        hook MUST be byte-identical on a second install."""
        tmp = _make_target([".scratch/"])
        hook = tmp / ".git/hooks/pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho user-hook\n")
        hook.chmod(0o755)
        hooks.install_pre_commit_hook(tmp)
        first = hook.read_bytes()
        hooks.install_pre_commit_hook(tmp)
        second = hook.read_bytes()
        self.assertEqual(first, second,
                         "second install must produce a byte-identical hook")

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


class InstallTargetValidationTests(unittest.TestCase):
    """T1-1-C1: --target MUST be a git worktree before any mutation.

    Without this guard the installer happily writes `.git/hooks/pre-commit`
    inside a plain directory, producing a hook that git will never invoke.
    """

    def test_install_pre_commit_refuses_non_git_target(self):
        tmp = Path(tempfile.mkdtemp(prefix="t1-1-nongit-"))
        # Deliberately do NOT `git init` -- tmp is a plain directory.
        with self.assertRaises(SystemExit) as ctx:
            hooks.install_pre_commit_hook(tmp)
        msg = str(ctx.exception)
        self.assertIn("not a git worktree", msg)
        self.assertIn(str(tmp), msg)
        # No `.git/hooks/` directory should have been created either.
        self.assertFalse((tmp / ".git").exists())

    def test_install_rejects_nested_git_repo_pointing_to_outer(self):
        # A bare subdirectory inside a git repo is NOT itself a worktree --
        # `git rev-parse` from within it resolves to the OUTER repo, so the
        # caller almost certainly meant the outer root. Refuse it.
        outer = Path(tempfile.mkdtemp(prefix="t1-1-outer-"))
        _git_init(outer)
        nested = outer / "subdir"
        nested.mkdir()
        with self.assertRaises(SystemExit) as ctx:
            hooks.install_pre_commit_hook(nested)
        self.assertIn("not a git worktree", str(ctx.exception))
        # Nothing written under nested/.git.
        self.assertFalse((nested / ".git").exists())


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


class HookHarnessMissingTests(unittest.TestCase):
    """T1-1-C2: hook hard-fails when harness CLI cannot be located.

    Silent skip masks the gate: a target installed without the harness
    accepts every commit even though scope enforcement is "on". The hook
    must instead exit non-zero with a clear error, or be explicitly opted
    into legacy skip behavior via ``HARNESS_HOOK_ALLOW_SKIP=1``.
    """

    def _run_hook(self, tmp: Path, env_extra: dict | None = None):
        hook = tmp / ".git/hooks/pre-commit"
        env = {"PATH": "/usr/bin:/bin"}  # No `harness` on PATH.
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["sh", str(hook)],
            cwd=tmp, capture_output=True, text=True, env=env,
        )

    def test_hook_hard_fails_when_harness_missing(self):
        tmp = _make_target([".scratch/"])  # NO harness shim installed.
        hooks.install_pre_commit_hook(tmp)
        proc = self._run_hook(tmp)
        self.assertNotEqual(proc.returncode, 0,
                            f"expected non-zero, got 0; stderr={proc.stderr!r}")
        self.assertIn("harness CLI not found", proc.stderr)

    def test_hook_skips_when_env_set(self):
        tmp = _make_target([".scratch/"])
        hooks.install_pre_commit_hook(tmp)
        proc = self._run_hook(tmp, env_extra={"HARNESS_HOOK_ALLOW_SKIP": "1"})
        self.assertEqual(proc.returncode, 0,
                         f"expected 0, got {proc.returncode}; stderr={proc.stderr!r}")


class AdapterCommandFileMirrorTests(unittest.TestCase):
    """T1-1 Task 5: both lifecycle `execute` adapter command files MUST
    promote `harness.py check --worktree` to a numbered pre-commit step
    and MUST NOT suggest `git commit --no-verify` as a workaround."""

    EXECUTE_FILES = (
        REPO_ROOT / ".opencode/commands/execute.md",
        REPO_ROOT / ".roo/commands/phase-execute.md",
    )

    def test_each_execute_file_invokes_check_worktree(self):
        for path in self.EXECUTE_FILES:
            with self.subTest(path=str(path)):
                body = path.read_text()
                self.assertIn(
                    "harness.py check --worktree", body,
                    f"{path} must invoke `harness.py check --worktree`",
                )

    def test_no_execute_file_recommends_no_verify(self):
        # Mentions of `git commit --no-verify` are permitted only inside
        # a "Do NOT ... --no-verify" sentence (multi-line tolerated).
        for path in self.EXECUTE_FILES:
            with self.subTest(path=str(path)):
                body = path.read_text()
                lines = body.splitlines()
                for index, line in enumerate(lines):
                    if "git commit --no-verify" in line:
                        # Look at line and the previous line (markdown wraps).
                        window = " ".join(lines[max(0, index - 1):index + 1]).lower()
                        self.assertTrue(
                            "do not" in window,
                            f"{path}: line {index+1} mentions --no-verify "
                            f"outside of a 'Do NOT' instruction: {line!r}",
                        )


if __name__ == "__main__":
    unittest.main()
