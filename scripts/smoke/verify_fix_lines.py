#!/usr/bin/env python3
"""S16 — verify every non-zero §3.4 exit emits a `Fix:` line to stderr.

Design spec: §3.9 Fix: error standard + §3.4 exit codes table.

Usage:
    python scripts/smoke/verify_fix_lines.py [--verbose]

Exit 0 if every non-zero exit code has a triggerable path that emits "Fix: ".
Exit 1 with a listing of which paths fail.

Exit codes covered (§3.4):
  0  — OK (skipped, no Fix: needed)
  2  — invalid_transition / multi_token_argument
  3  — session_locked (active session or stale lock)
  4  — scope_violation (worktree scope check)
  5  — unparseable_state (BOM or malformed JSON)
  6  — provenance_mismatch / non_tty_approval_blocked
  7  — stale_uncertain (session lock with bad pid)
  8  — approve_during_autopilot
  9  — budget_exhausted (wall_seconds)
 10  — audit_chain_mismatch
 11  — windows_containment_degraded (SKIP — Windows-only)
 12  — git_repo_required (chain mode, no .git)
 13  — deprecated_flag (--chain / --auto)
 14  — crash_recovery_undecidable (audit_partial_write)
 16  — chain_start_dirty_tree (chain mode, dirty working tree)
 17  — human_action_required (harness next --shell)
 18  — no_action_during_autopilot (harness next --shell, autopilot active)
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HARNESS_BIN = sys.executable
HARNESS_MOD = str(SCRIPTS_DIR / "harness.py")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _run(
    *args: str,
    cwd: Optional[Path] = None,
    env_extra: Optional[dict] = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess:
    """Run harness CLI and return CompletedProcess. Captures stdout+stderr."""
    env = dict(os.environ, **(env_extra or {}))
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    # Ensure the repo root is in PYTHONPATH so `from scripts.lib import ...`
    # lazy imports inside phase_cli.py work when cwd is not the repo root.
    old_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (":" + old_pp if old_pp else "")
    cmd = [HARNESS_BIN, HARNESS_MOD, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=timeout,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_harness_dir(tmp: Path) -> Path:
    h = tmp / ".harness"
    h.mkdir(parents=True, exist_ok=True)
    return h


def _make_install_record(harness_dir: Path, approver: str = "tester@example.com") -> None:
    record = {
        "version": "0.7.0",
        "approvers": [{"email": approver}],
        "installed_at": "2026-05-18T00:00:00Z",
        "git_user_email_at_install_sha256": None,
    }
    (harness_dir / "install-record.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )


def _write_state(scratch: Path, state: dict) -> bytes:
    """Write phase-state.json and return its canonical bytes."""
    scratch.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state, indent=2, sort_keys=True) + "\n"
    raw = data.encode("utf-8")
    (scratch / "phase-state.json").write_bytes(raw)
    return raw


def _write_audit_with_state_hash(harness_dir: Path, state_bytes: bytes) -> None:
    """Write an audit.log whose last entry after_sha256 matches state_bytes.

    This satisfies the state_trust preflight (§2.6) which requires that the
    audit log tail's after_sha256 equals sha256(state_bytes).
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from lib.audit import audit_append
    finally:
        if str(SCRIPTS_DIR) in sys.path:
            sys.path.remove(str(SCRIPTS_DIR))

    state_hash = _sha256_bytes(state_bytes)
    audit_path = harness_dir / "audit.log"
    audit_append(
        {
            "verb": "test.fixture.bootstrap",
            "at": "2026-05-18T00:00:00Z",
            "before_sha256": "",
            "after_sha256": state_hash,
        },
        audit_path=audit_path,
    )


def _setup_valid_fixture(
    tmp: Path,
    state: dict,
    *,
    approver: str = "tester@example.com",
) -> tuple[Path, Path]:
    """Create .scratch/ + .harness/ with state+audit hash chain valid.

    Returns (scratch, harness_dir).
    """
    scratch = tmp / ".scratch"
    harness_dir = _make_harness_dir(tmp)
    _make_install_record(harness_dir, approver)
    state_bytes = _write_state(scratch, state)
    _write_audit_with_state_hash(harness_dir, state_bytes)
    return scratch, harness_dir


# ---------------------------------------------------------------------------
# ExitCase registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ExitCase:
    code: int
    name: str
    trigger: Callable[[], subprocess.CompletedProcess]
    fix_must_contain: str
    skip_reason: Optional[str] = None

    def verify(self, verbose: bool = False) -> tuple[bool, str]:
        if self.skip_reason:
            return True, f"SKIP [{self.code}] {self.name}: {self.skip_reason}"

        try:
            result = self.trigger()
        except subprocess.TimeoutExpired:
            return False, f"FAIL [{self.code}] {self.name}: trigger timed out"
        except Exception as exc:
            return False, f"FAIL [{self.code}] {self.name}: trigger raised {type(exc).__name__}: {exc}"

        combined = result.stderr

        if verbose:
            print(
                f"  [{self.code}] {self.name}: returncode={result.returncode}",
                file=sys.stderr,
            )
            for line in combined.splitlines()[:6]:
                print(f"    stderr: {line}", file=sys.stderr)

        if result.returncode != self.code:
            return False, (
                f"FAIL [{self.code}] {self.name}: "
                f"expected returncode {self.code} but got {result.returncode}. "
                f"stderr={combined[:300]!r}"
            )

        if "Fix:" not in combined:
            return False, (
                f"FAIL [{self.code}] {self.name}: "
                f"'Fix:' not found in stderr. stderr={combined[:300]!r}"
            )

        if self.fix_must_contain and self.fix_must_contain not in combined:
            return False, (
                f"FAIL [{self.code}] {self.name}: "
                f"Fix: line present but does not contain {self.fix_must_contain!r}. "
                f"stderr={combined[:300]!r}"
            )

        return True, f"PASS [{self.code}] {self.name}"


# ---------------------------------------------------------------------------
# Trigger factories
# ---------------------------------------------------------------------------


def _trigger_exit2_invalid_transition() -> subprocess.CompletedProcess:
    """Exit 2: invalid transition — execute→discuss directly."""
    with tempfile.TemporaryDirectory(prefix="harn-e2-") as d:
        tmp = Path(d)
        state = {
            "phase": "execute",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": [],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        return _run("phase", "set", "discuss", cwd=tmp)


def _trigger_exit3_session_locked() -> subprocess.CompletedProcess:
    """Exit 3: session_locked — lock file with live PID."""
    with tempfile.TemporaryDirectory(prefix="harn-e3-") as d:
        tmp = Path(d)
        state = {
            "phase": "discuss",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": [],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        # Write a lock with the current process's live PID
        lock_payload = {"pid": os.getpid(), "boot_id": "test-boot-id"}
        (harness_dir / "session.lock").write_text(
            json.dumps(lock_payload), encoding="utf-8"
        )
        return _run("phase", "set", "plan", cwd=tmp)


def _trigger_exit4_scope_violation() -> subprocess.CompletedProcess:
    """Exit 4: scope_violation — worktree check with denied file via check_worktree_paths."""
    with tempfile.TemporaryDirectory(prefix="harn-e4-") as d:
        tmp = Path(d)
        state = {
            "phase": "execute",
            "approved": True,
            "approved_by": "tester@example.com",
            "approved_at": "2026-05-18T00:00:00Z",
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": ["true"],
            "allowed_paths": ["src/"],
            "plan_finalized_at": "2026-05-18T00:00:00Z",
            "execute_attempt_started_at": "2026-05-18T00:00:00Z",
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)

        # Init git repo with initial commit then add a denied file
        git_env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
        subprocess.run(["git", "init", str(tmp)], capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], capture_output=True, cwd=str(tmp))
        subprocess.run(["git", "config", "user.name", "T"], capture_output=True, cwd=str(tmp))
        (tmp / "README").write_text("init", encoding="utf-8")
        subprocess.run(["git", "add", "README"], capture_output=True, cwd=str(tmp))
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp), env=git_env)
        # Create an untracked file outside allowed_paths (appears in git ls-files --others)
        (tmp / "outside_scope.txt").write_text("violation", encoding="utf-8")

        # Use a script to call check_worktree_paths directly (no harness CLI needed)
        script = tmp / "trigger_e4.py"
        script.write_text(
            f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
from pathlib import Path
from lib.worktree import check_worktree_paths
try:
    check_worktree_paths(Path({str(tmp)!r}))
except SystemExit as e:
    sys.exit(e.code)
sys.exit(0)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=10.0,
        )


def _trigger_exit5_unparseable_state() -> subprocess.CompletedProcess:
    """Exit 5: unparseable_state — BOM in phase-state.json."""
    with tempfile.TemporaryDirectory(prefix="harn-e5-") as d:
        tmp = Path(d)
        scratch = tmp / ".scratch"
        harness_dir = _make_harness_dir(tmp)
        _make_install_record(harness_dir)
        (harness_dir / "audit.log").write_text("", encoding="utf-8")
        scratch.mkdir(parents=True, exist_ok=True)
        # Write BOM + invalid JSON to trigger exit 5
        (scratch / "phase-state.json").write_bytes(b"\xef\xbb\xbf{invalid json")
        return _run("phase", "set", "plan", cwd=tmp)


def _trigger_exit6_non_tty_approval() -> subprocess.CompletedProcess:
    """Exit 6: non_tty_approval_blocked — phase approve from non-TTY subprocess."""
    with tempfile.TemporaryDirectory(prefix="harn-e6-") as d:
        tmp = Path(d)
        state = {
            "phase": "plan",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": ["pytest tests/ -q"],
            "allowed_paths": ["src/"],
            "plan_finalized_at": "2026-05-18T00:00:00Z",
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        # Running from subprocess = non-TTY stdin → exit 6
        return _run("phase", "approve", "--by", "tester@example.com", cwd=tmp)


def _trigger_exit7_stale_uncertain() -> subprocess.CompletedProcess:
    """Exit 7: stale_uncertain — session lock with no pid field."""
    with tempfile.TemporaryDirectory(prefix="harn-e7-") as d:
        tmp = Path(d)
        harness_dir = _make_harness_dir(tmp)
        # Lock with missing pid field
        (harness_dir / "session.lock").write_text(
            json.dumps({"owner": "unknown", "boot_id": "abc"}),
            encoding="utf-8",
        )
        return _run("session", "unlock", cwd=tmp)


def _trigger_exit8_approve_during_autopilot() -> subprocess.CompletedProcess:
    """Exit 8: approve_during_autopilot — phase approve while autopilot active."""
    with tempfile.TemporaryDirectory(prefix="harn-e8-") as d:
        tmp = Path(d)
        state = {
            "phase": "plan",
            "approved": False,
            "execution_mode": "phase_autopilot",  # autopilot active
            "autopilot_run_id": "abc123def456",
            "autopilot_mode": "phase",
            "autopilot_phase_slug": "01-test",
            "autopilot_allow_network": False,
            "autopilot_started_at_iso": "2026-05-18T00:00:00Z",
            "state_schema_version": 2,
            "verification": ["pytest tests/ -q"],
            "allowed_paths": ["src/"],
            "plan_finalized_at": "2026-05-18T00:00:00Z",
            "cli_budgets_remaining": {
                "shell_invocations": 50,
                "file_mutation_ops": 100,
                "wall_seconds": 300,
            },
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        # Trigger via internal Python API to bypass TTY check
        script = tmp / "trigger_e8.py"
        script.write_text(
            f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import argparse
from pathlib import Path
from lib import phase_approve as _pa

args = argparse.Namespace(
    by="tester@example.com",
    at=None,
    override_identity=None,
    override_reason=None,
)
result = _pa.run_approve(
    args,
    scratch=Path({str(scratch)!r}),
    harness_dir=Path({str(harness_dir)!r}),
    audit_path=Path({str(harness_dir / "audit.log")!r}),
    install_record_path=Path({str(harness_dir / "install-record.json")!r}),
    nonce_dir=Path({str(tmp / "nonces")!r}),
    stdin_isatty=True,      # pretend TTY to bypass step 1
    consumer_tty="/dev/pts/0",
    repo_root=None,
    skip_anchor_preflight=True,  # bypass anchor for test
)
sys.exit(result.exit_code)
""",
            encoding="utf-8",
        )
        result = subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=10.0,
        )
        return result


def _trigger_exit9_budget_exhausted() -> subprocess.CompletedProcess:
    """Exit 9: budget_exhausted:wall_seconds — autopilot with expired wall budget."""
    with tempfile.TemporaryDirectory(prefix="harn-e9-") as d:
        tmp = Path(d)
        state = {
            "phase": "execute",
            "approved": True,
            "approved_by": "tester@example.com",
            "approved_at": "2026-05-18T00:00:00Z",
            "execution_mode": "phase_autopilot",
            "autopilot_run_id": "test-run-id",
            "autopilot_mode": "phase",
            "autopilot_phase_slug": "01-test",
            "state_schema_version": 2,
            "verification": ["true"],
            "allowed_paths": ["src/"],
            "plan_finalized_at": "2026-05-18T00:00:00Z",
            "execute_attempt_started_at": "2026-05-18T00:00:00Z",
            "autopilot_started_at_iso": "2000-01-01T00:00:00Z",  # expired long ago
            "cli_budgets_remaining": {
                "shell_invocations": 50,
                "file_mutation_ops": 100,
                "wall_seconds": 300,
            },
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        return _run("phase", "set", "done", cwd=tmp)


def _trigger_exit10_audit_chain_mismatch() -> subprocess.CompletedProcess:
    """Exit 10: audit chain mismatch — tampered audit.log (verify --audit --fixture)."""
    with tempfile.TemporaryDirectory(prefix="harn-e10-") as d:
        tmp = Path(d)
        # verify --fixture expects audit.log at <fixture_dir>/audit.log directly
        audit_path = tmp / "audit.log"
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.audit import audit_append
            audit_append(
                {"verb": "phase.set", "at": "2026-05-18T00:00:00Z", "phase": "discuss"},
                audit_path=audit_path,
            )
            # Tamper: modify verb but keep stale entry_hash → chain mismatch
            lines = audit_path.read_text().splitlines()
            entry = json.loads(lines[0])
            entry["verb"] = "tampered_verb"
            lines[0] = json.dumps(entry, separators=(",", ":"), sort_keys=True)
            audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        finally:
            if str(SCRIPTS_DIR) in sys.path:
                sys.path.remove(str(SCRIPTS_DIR))
        return _run("verify", "--audit", "--fixture", str(tmp), cwd=tmp)


def _ci_test_env() -> dict:
    """Return env vars for CI predicate test path (HARNESS_OIDC_TEST_MODE=1).

    Uses GitHub Actions provider with stub OIDC token+claims so the CI
    predicate passes without real HTTP. bot_identity uses a non-approver
    email so the HARNESS_BY_TRUST overlap-with-approver check passes.
    """
    claims = json.dumps({
        "iss": "https://token.actions.githubusercontent.com",
        "sub": "repo:test/test:ref:refs/heads/main",
        "repository": "test/test",
        "ref": "refs/heads/main",
        "sha": "abc123",
    })
    return {
        "HARNESS_OIDC_TEST_MODE": "1",
        "HARNESS_AUTOMATION": "chain",
        "HARNESS_BY_TRUST": "ci-bot@ci.example.com",  # not in approvers
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "1234",
        "GITHUB_REPOSITORY": "test/test",
        "GITHUB_SHA": "abc123",
        "GITHUB_WORKFLOW": "test-workflow",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.githubusercontent.com/stub",
        "HARNESS_TEST_OIDC_TOKEN_GITHUB_ACTIONS": "stub-oidc-token",
        "HARNESS_TEST_OIDC_CLAIMS_GITHUB_ACTIONS": claims,
    }


def _trigger_exit12_git_repo_required() -> subprocess.CompletedProcess:
    """Exit 12: git_repo_required — chain mode without .git directory."""
    with tempfile.TemporaryDirectory(prefix="harn-e12-") as d:
        tmp = Path(d)
        state = {
            "phase": "discuss",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": ["true"],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        # NO .git dir here — chain mode should exit 12.
        # Use full CI test env so the CI predicate passes.
        script = tmp / "trigger_e12.py"
        ci_env = _ci_test_env()
        script.write_text(
            f"""
import sys, os
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
from pathlib import Path
from lib import phase_autopilot as _pa
from lib import phase_lock as _pl

scratch = Path({str(scratch)!r})
harness_dir = Path({str(harness_dir)!r})
audit_path = harness_dir / "audit.log"
cwd = Path({str(tmp)!r})

# Full CI test env so ci_provenance passes
env = dict(os.environ)
env.update({ci_env!r})

lock = _pl.acquire_primary(scratch, timeout_s=5.0, audit_path=audit_path)
try:
    result = _pa.run_start(
        scratch_root=scratch,
        audit_path=audit_path,
        lock_handle=lock,
        phase_slug="test-phase",
        mode="chain",
        budgets=None,
        allow_network=False,
        anchor_verified=True,
        skip_anchor_preflight=True,
        accept_degraded_windows_containment=False,
        repo_root=cwd,  # no .git here → exit 12
        roadmap_root=None,
        env=env,
        stdin_is_tty=False,
        consumer_tty=None,
        nonce_audience=None,
        nonce_dir=None,
        by_email=None,
        install_record_root=cwd,
        oidc_fetcher=None,
        oidc_verifier=None,
    )
finally:
    _pl.release_primary(lock)
sys.exit(result.exit_code)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=15.0,
            env={**os.environ, **ci_env},
        )


def _trigger_exit13_deprecated_flag() -> subprocess.CompletedProcess:
    """Exit 13: deprecated_flag — --chain flag."""
    return _run("--chain", "phase", "set", "plan")


def _trigger_exit14_crash_recovery() -> subprocess.CompletedProcess:
    """Exit 14: crash_recovery_undecidable — state file is 0 bytes (crash artefact).

    Triggered via phase_approve internal API with a 0-byte state file.
    The state_trust preflight raises StateEmptyError → exit 14.
    """
    with tempfile.TemporaryDirectory(prefix="harn-e14-") as d:
        tmp = Path(d)
        harness_dir = _make_harness_dir(tmp)
        _make_install_record(harness_dir)
        scratch = tmp / ".scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        # Write an audit entry then write 0-byte state — crash artefact
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from lib.audit import audit_append
            audit_path = harness_dir / "audit.log"
            audit_append(
                {
                    "verb": "test.fixture.bootstrap",
                    "at": "2026-05-18T00:00:00Z",
                    "before_sha256": "",
                    "after_sha256": "0" * 64,  # mismatch is OK; state empty fires first
                },
                audit_path=audit_path,
            )
        finally:
            if str(SCRIPTS_DIR) in sys.path:
                sys.path.remove(str(SCRIPTS_DIR))
        # 0-byte state file → StateEmptyError → exit 14
        (scratch / "phase-state.json").write_bytes(b"")

        script = tmp / "trigger_e14.py"
        script.write_text(
            f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import argparse
from pathlib import Path
from lib import phase_approve as _pa

args = argparse.Namespace(
    by="tester@example.com",
    at=None,
    override_identity=None,
    override_reason=None,
)
result = _pa.run_approve(
    args,
    scratch=Path({str(scratch)!r}),
    harness_dir=Path({str(harness_dir)!r}),
    audit_path=Path({str(harness_dir / "audit.log")!r}),
    install_record_path=Path({str(harness_dir / "install-record.json")!r}),
    nonce_dir=Path({str(tmp / "nonces")!r}),
    stdin_isatty=True,      # pretend TTY to bypass step 1
    consumer_tty="/dev/pts/0",
    repo_root=None,
    skip_anchor_preflight=True,  # bypass anchor for test
)
sys.exit(result.exit_code)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=10.0,
        )


def _trigger_exit16_dirty_tree() -> subprocess.CompletedProcess:
    """Exit 16: chain_start_dirty_tree — chain mode with dirty git working tree."""
    with tempfile.TemporaryDirectory(prefix="harn-e16-") as d:
        tmp = Path(d)
        state = {
            "phase": "discuss",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": ["true"],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)

        # Init git repo with an initial commit then make it dirty
        git_env = {**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.com",
                   "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com"}
        subprocess.run(["git", "init", str(tmp)], capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], capture_output=True, cwd=str(tmp))
        subprocess.run(["git", "config", "user.name", "T"], capture_output=True, cwd=str(tmp))
        (tmp / "README").write_text("init", encoding="utf-8")
        subprocess.run(["git", "add", "README"], capture_output=True, cwd=str(tmp))
        subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=str(tmp), env=git_env)
        # Now make it dirty (untracked file appears in `git status --porcelain`)
        (tmp / "dirty_file.txt").write_text("uncommitted change", encoding="utf-8")

        # Use full CI test env so the CI predicate passes, then dirty tree check fires.
        ci_env = _ci_test_env()
        script = tmp / "trigger_e16.py"
        script.write_text(
            f"""
import sys, os
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
from pathlib import Path
from lib import phase_autopilot as _pa
from lib import phase_lock as _pl

scratch = Path({str(scratch)!r})
harness_dir = Path({str(harness_dir)!r})
audit_path = harness_dir / "audit.log"
cwd = Path({str(tmp)!r})

# Full CI test env so ci_provenance passes; dirty tree check fires after git-repo check
env = dict(os.environ)
env.update({ci_env!r})

lock = _pl.acquire_primary(scratch, timeout_s=5.0, audit_path=audit_path)
try:
    result = _pa.run_start(
        scratch_root=scratch,
        audit_path=audit_path,
        lock_handle=lock,
        phase_slug="01-test",
        mode="chain",
        budgets=None,
        allow_network=False,
        anchor_verified=True,
        skip_anchor_preflight=True,
        accept_degraded_windows_containment=False,
        repo_root=cwd,
        roadmap_root=None,
        env=env,
        stdin_is_tty=False,
        consumer_tty=None,
        nonce_audience=None,
        nonce_dir=None,
        by_email=None,
        install_record_root=cwd,
        oidc_fetcher=None,
        oidc_verifier=None,
    )
finally:
    _pl.release_primary(lock)
sys.exit(result.exit_code)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=15.0,
            env={**os.environ, **ci_env},
        )


def _trigger_exit17_human_action_required() -> subprocess.CompletedProcess:
    """Exit 17: human_action_required — next --shell in plan phase without approval."""
    with tempfile.TemporaryDirectory(prefix="harn-e17-") as d:
        tmp = Path(d)
        state = {
            "phase": "plan",
            "approved": False,
            "execution_mode": "manual",
            "state_schema_version": 2,
            "verification": [],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        # Bypass anchor check: remove state file so anchor check is skipped,
        # then use a fixture dir with no anchor.
        # Actually: next --shell reads state but goes through anchor preflight.
        # We need to make anchor pass OR remove state file to skip it.
        # Remove state — then next returns "no state" default (discuss, exit 0).
        # Better: set up state using the no-state bootstrap path in status_next_cli.
        # Actually, if no state file, status_next_cli returns defaults (discuss phase)
        # which gives exit 0 (discuss → suggest harness phase set plan, agent_safe).
        #
        # To trigger exit 17 we need a plan state without approval.
        # The anchor check fires when state exists. Let's skip anchor via env or
        # use a separate script that calls cmd_next directly.
        script = tmp / "trigger_e17.py"
        script.write_text(
            f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import argparse
from pathlib import Path
from lib import status_next_cli as _snc

args = argparse.Namespace(shell=True, json=False)
# Monkeypatch _read_state_with_preflight to bypass anchor check
import lib.status_next_cli as _mod
_orig = _mod._read_state_with_preflight
def _bypass(*, scratch, audit_path, cwd):
    import json
    sp = scratch / "phase-state.json"
    if sp.exists():
        return json.loads(sp.read_bytes().decode("utf-8")), 0
    return {{"phase": "discuss", "execution_mode": "manual"}}, 0
_mod._read_state_with_preflight = _bypass

import os
os.chdir({str(tmp)!r})
rc = _snc.cmd_next(args)
sys.exit(rc)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=10.0,
        )


def _trigger_exit18_no_action_during_autopilot() -> subprocess.CompletedProcess:
    """Exit 18: no_action_during_autopilot — next --shell while autopilot active."""
    with tempfile.TemporaryDirectory(prefix="harn-e18-") as d:
        tmp = Path(d)
        state = {
            "phase": "execute",
            "approved": True,
            "approved_by": "tester@example.com",
            "approved_at": "2026-05-18T00:00:00Z",
            "execution_mode": "phase_autopilot",
            "autopilot_run_id": "test-run-id",
            "state_schema_version": 2,
            "verification": [],
        }
        scratch, harness_dir = _setup_valid_fixture(tmp, state)
        script = tmp / "trigger_e18.py"
        script.write_text(
            f"""
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import argparse, os
from pathlib import Path
from lib import status_next_cli as _snc

args = argparse.Namespace(shell=True, json=False)
import lib.status_next_cli as _mod
_orig = _mod._read_state_with_preflight
def _bypass(*, scratch, audit_path, cwd):
    import json
    sp = scratch / "phase-state.json"
    if sp.exists():
        return json.loads(sp.read_bytes().decode("utf-8")), 0
    return {{"phase": "discuss", "execution_mode": "manual"}}, 0
_mod._read_state_with_preflight = _bypass

os.chdir({str(tmp)!r})
rc = _snc.cmd_next(args)
sys.exit(rc)
""",
            encoding="utf-8",
        )
        return subprocess.run(
            [HARNESS_BIN, str(script)],
            capture_output=True, text=True, cwd=str(tmp), timeout=10.0,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EXIT_CASES: list[ExitCase] = [
    ExitCase(
        code=2,
        name="invalid_transition",
        trigger=_trigger_exit2_invalid_transition,
        fix_must_contain="harness phase",
    ),
    ExitCase(
        code=3,
        name="session_locked",
        trigger=_trigger_exit3_session_locked,
        fix_must_contain="session unlock",
    ),
    ExitCase(
        code=4,
        name="scope_violation",
        trigger=_trigger_exit4_scope_violation,
        fix_must_contain="Fix:",
    ),
    ExitCase(
        code=5,
        name="unparseable_state",
        trigger=_trigger_exit5_unparseable_state,
        fix_must_contain="Fix:",
    ),
    ExitCase(
        code=6,
        name="non_tty_approval_blocked",
        trigger=_trigger_exit6_non_tty_approval,
        fix_must_contain="harness phase approve",
    ),
    ExitCase(
        code=7,
        name="stale_uncertain",
        trigger=_trigger_exit7_stale_uncertain,
        fix_must_contain="session unlock --force",
    ),
    ExitCase(
        code=8,
        name="approve_during_autopilot",
        trigger=_trigger_exit8_approve_during_autopilot,
        fix_must_contain="autopilot stop",
    ),
    ExitCase(
        code=9,
        name="budget_exhausted",
        trigger=_trigger_exit9_budget_exhausted,
        fix_must_contain="Fix:",
    ),
    ExitCase(
        code=10,
        name="audit_chain_mismatch",
        trigger=_trigger_exit10_audit_chain_mismatch,
        fix_must_contain="Fix:",
    ),
    ExitCase(
        code=11,
        name="windows_containment_degraded",
        trigger=lambda: subprocess.CompletedProcess([], 0),  # never called
        fix_must_contain="",
        skip_reason=(
            "Windows-only: exit 11 fires only when platform.system()=='Windows' "
            "and neither --accept-degraded-windows-containment nor --allow-network "
            "is passed. Not triggerable on POSIX. "
            "Fix line present in phase_autopilot.py _FIX_WINDOWS_CHAIN constant."
        ),
    ),
    ExitCase(
        code=12,
        name="git_repo_required",
        trigger=_trigger_exit12_git_repo_required,
        fix_must_contain="git",
    ),
    ExitCase(
        code=13,
        name="deprecated_flag",
        trigger=_trigger_exit13_deprecated_flag,
        fix_must_contain="autopilot",
    ),
    ExitCase(
        code=14,
        name="crash_recovery_undecidable",
        trigger=_trigger_exit14_crash_recovery,
        fix_must_contain="Fix:",
    ),
    ExitCase(
        code=16,
        name="chain_start_dirty_tree",
        trigger=_trigger_exit16_dirty_tree,
        fix_must_contain="stash",
    ),
    ExitCase(
        code=17,
        name="human_action_required",
        trigger=_trigger_exit17_human_action_required,
        fix_must_contain="harness phase approve",
    ),
    ExitCase(
        code=18,
        name="no_action_during_autopilot",
        trigger=_trigger_exit18_no_action_during_autopilot,
        fix_must_contain="autopilot stop",
    ),
]


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show per-case stderr snippets."
    )
    args = parser.parse_args(argv)

    print(
        f"verify_fix_lines.py — checking {len(EXIT_CASES)} exit cases (§3.4 + §3.9)",
        flush=True,
    )
    print(f"  HARNESS_BIN: {HARNESS_BIN}", flush=True)
    print(f"  HARNESS_MOD: {HARNESS_MOD}", flush=True)
    print(flush=True)

    passed = 0
    failed = 0
    skipped = 0
    results: list[tuple[bool, str]] = []

    for case in EXIT_CASES:
        ok, msg = case.verify(verbose=args.verbose)
        results.append((ok, msg))
        if case.skip_reason:
            skipped += 1
        elif ok:
            passed += 1
        else:
            failed += 1
        print(msg, flush=True)

    print(flush=True)
    print(
        f"Results: {passed} passed, {failed} failed, {skipped} skipped "
        f"(total {len(EXIT_CASES)} cases)",
        flush=True,
    )

    if failed:
        print(flush=True)
        print("FAILURES:", flush=True)
        for ok, msg in results:
            if not ok:
                print(f"  {msg}", flush=True)
        return 1

    print(
        "All non-zero exits verified — Fix: lines present. (§3.9 S16)", flush=True
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
