"""Tests for scripts/lib/autopilot_guard.py — POSIX network deny shim (§5.2).

RED phase: written before implementation exists (TDD discipline).

Design refs:
  - §5.2 — POSIX network deny shim; deny-list; PATH-prepend install deferred to S10d.
  - §3.4 — exit 4 scope_violation (sub_reason: autopilot_network_deny).
  - scripts/lib/audit.py:audit_append — audit emission backend.

Fault classes asserted:
  - is_denied: deny-listed simple commands (curl, wget, nc, ssh, scp, rsync, gh, glab)
  - is_denied: deny-listed git subcommands (push, pull, fetch, clone, remote update, submodule update --remote)
  - is_denied: basename normalization (/usr/bin/curl → denied)
  - is_denied: ALLOWED — git subcommand update (no --remote), git status/log/diff
  - is_denied: ALLOWED — safe commands (ls, cat, etc.)
  - is_denied: case-insensitive basename (curl.exe → denied)
  - is_denied: empty argv → (False, None)
  - is_denied: HARNESS_ALLOW_NETWORK=1 env → NOT a bypass (input metadata only, §3.5/§5.2)
  - emit_deny_audit: writes audit row with required fields; truncates command at 512 chars
  - shim_main: env not set to deny → execvp called (allow pass-through)
  - shim_main: env=deny + curl → returns 4, audit emitted, stderr has "refused"
  - shim_main: env=deny + ls → execvp called (allow pass-through)
  - Audit row shape: verb, command_label, command, cwd, at fields present
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Sequence

import pytest

# ---------------------------------------------------------------------------
# Import target (will fail until module exists — RED phase)
# ---------------------------------------------------------------------------

from lib.autopilot_guard import (
    DENY_LIST_GIT,
    DENY_LIST_SIMPLE,
    NetworkDenyError,
    emit_deny_audit,
    is_denied,
    shim_main,
)


# ---------------------------------------------------------------------------
# is_denied — simple deny-list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv,expected_label", [
    # Simple deny-listed commands
    (["curl", "-X", "GET", "http://example.com"], "curl"),
    (["wget", "http://example.com"], "wget"),
    (["nc", "-z", "localhost", "80"], "nc"),
    (["ssh", "user@host"], "ssh"),
    (["scp", "file.txt", "user@host:/tmp/"], "scp"),
    (["rsync", "-av", "src/", "user@host:dst/"], "rsync"),
    (["gh", "pr", "list"], "gh"),
    (["glab", "issue", "list"], "glab"),
])
def test_is_denied_simple_commands(argv: list[str], expected_label: str) -> None:
    """Simple deny-listed commands are refused."""
    denied, label = is_denied(argv)
    assert denied is True
    assert label == expected_label


@pytest.mark.parametrize("argv,expected_label", [
    # git subcommands that touch the network
    (["git", "push", "origin", "main"], "git push"),
    (["git", "pull"], "git pull"),
    (["git", "fetch", "--all"], "git fetch"),
    (["git", "clone", "https://github.com/org/repo"], "git clone"),
    (["git", "remote", "update"], "git remote update"),
    (["git", "submodule", "update", "--remote"], "git submodule update --remote"),
])
def test_is_denied_git_network_subcommands(argv: list[str], expected_label: str) -> None:
    """git subcommands that touch the network are denied."""
    denied, label = is_denied(argv)
    assert denied is True
    assert label == expected_label


def test_is_denied_git_submodule_update_no_remote_is_allowed() -> None:
    """git submodule update (without --remote) is allowed — local operation."""
    denied, label = is_denied(["git", "submodule", "update"])
    assert denied is False
    assert label is None


@pytest.mark.parametrize("argv", [
    ["git", "status"],
    ["git", "log", "--oneline"],
    ["git", "diff", "HEAD"],
    ["git", "add", "."],
    ["git", "commit", "-m", "msg"],
])
def test_is_denied_git_local_subcommands_allowed(argv: list[str]) -> None:
    """git subcommands that are local (no network) are allowed."""
    denied, label = is_denied(argv)
    assert denied is False
    assert label is None


@pytest.mark.parametrize("argv", [
    ["ls", "-la"],
    ["cat", "file.txt"],
    ["python3", "script.py"],
    ["pytest", "tests/"],
    ["echo", "hello"],
])
def test_is_denied_safe_commands_allowed(argv: list[str]) -> None:
    """Safe local commands are allowed."""
    denied, label = is_denied(argv)
    assert denied is False
    assert label is None


def test_is_denied_basename_normalization_absolute_path() -> None:
    """Full path /usr/bin/curl resolves basename curl → denied."""
    denied, label = is_denied(["/usr/bin/curl", "-X", "GET", "http://x"])
    assert denied is True
    assert label == "curl"


def test_is_denied_basename_normalization_case_insensitive_exe() -> None:
    """curl.exe (Windows compat consideration) is denied via case-insensitive match."""
    denied, label = is_denied(["curl.exe", "--help"])
    assert denied is True
    assert label == "curl"  # matched after stripping .exe and lowercasing


def test_is_denied_empty_argv_is_allowed() -> None:
    """Empty argv → (False, None); nothing to deny."""
    denied, label = is_denied([])
    assert denied is False
    assert label is None


def test_is_denied_allow_network_env_is_not_a_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """HARNESS_ALLOW_NETWORK=1 is input metadata only (§3.5/§5.2); it does NOT
    bypass is_denied. The legitimate allow path is HARNESS_AUTOPILOT_NETWORK=allow
    (set by run_start after §3.5/§3.5.1 authorization).

    This test replaces the old 'env overrides all' test that documented the
    incorrect env-spoof bypass. See S10b+S10c review fixes (P1-1).
    """
    monkeypatch.setenv("HARNESS_ALLOW_NETWORK", "1")

    # Deny-listed commands must STILL be denied regardless of HARNESS_ALLOW_NETWORK.
    for argv in [
        ["curl", "http://example.com"],
        ["git", "push", "origin"],
        ["gh", "pr", "list"],
        ["ssh", "user@host"],
    ]:
        denied, label = is_denied(argv)
        assert denied is True, (
            f"P1-1: HARNESS_ALLOW_NETWORK=1 must NOT bypass is_denied for {argv!r}. "
            "This env var is input metadata only, not authorization (§3.5/§5.2)."
        )


def test_is_denied_allow_network_env_unset_still_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without HARNESS_ALLOW_NETWORK=1, deny-listed commands are denied."""
    monkeypatch.delenv("HARNESS_ALLOW_NETWORK", raising=False)

    denied, label = is_denied(["curl", "http://example.com"])
    assert denied is True
    assert label == "curl"


# ---------------------------------------------------------------------------
# NetworkDenyError — class contract
# ---------------------------------------------------------------------------


def test_network_deny_error_exit_code() -> None:
    """NetworkDenyError carries exit_code=4 and sub_reason=autopilot_network_deny."""
    exc = NetworkDenyError("test error")
    assert exc.exit_code == 4
    assert exc.sub_reason == "autopilot_network_deny"
    assert issubclass(NetworkDenyError, OSError)


# ---------------------------------------------------------------------------
# emit_deny_audit
# ---------------------------------------------------------------------------


def test_emit_deny_audit_writes_required_fields(tmp_path: Path) -> None:
    """emit_deny_audit appends a well-formed audit row with all required fields."""
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    argv = ["curl", "-X", "GET", "http://example.com/api"]
    emit_deny_audit(argv=argv, command_label="curl", audit_path=audit_path)

    assert audit_path.exists(), "audit file must be created"
    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, f"Expected 1 audit row, got {len(lines)}"

    row = json.loads(lines[0])
    assert row["verb"] == "autopilot.network.deny"
    assert row["command_label"] == "curl"
    assert "command" in row
    assert "cwd" in row
    assert "at" in row
    # command should contain the argv joined
    assert "curl" in row["command"]


def test_emit_deny_audit_truncates_long_command(tmp_path: Path) -> None:
    """emit_deny_audit truncates command field at 512 chars."""
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    long_arg = "A" * 600
    argv = ["curl", long_arg]
    emit_deny_audit(argv=argv, command_label="curl", audit_path=audit_path)

    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    row = json.loads(lines[0])
    assert len(row["command"]) <= 512, f"command field should be truncated to ≤512, got {len(row['command'])}"


def test_emit_deny_audit_best_effort_on_bad_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """emit_deny_audit prints warning to stderr but does NOT raise if path is unwritable."""
    # Use a path that can't be created (parent is a file, not a dir)
    bogus_file = tmp_path / "not-a-dir"
    bogus_file.write_text("I am a file")
    bogus_audit = bogus_file / "audit.log"

    # Should NOT raise — best-effort
    emit_deny_audit(argv=["curl", "http://x"], command_label="curl", audit_path=bogus_audit)

    captured = capsys.readouterr()
    assert "warn" in captured.err.lower() or "error" in captured.err.lower() or "audit" in captured.err.lower()


def test_emit_deny_audit_git_push(tmp_path: Path) -> None:
    """emit_deny_audit works for git push with full argv."""
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    argv = ["git", "push", "origin", "main"]
    emit_deny_audit(argv=argv, command_label="git push", audit_path=audit_path)

    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    row = json.loads(lines[0])
    assert row["verb"] == "autopilot.network.deny"
    assert row["command_label"] == "git push"
    assert "git push origin main" in row["command"]


# ---------------------------------------------------------------------------
# shim_main
# ---------------------------------------------------------------------------


def test_shim_main_allows_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """shim_main: HARNESS_AUTOPILOT_NETWORK not set → execvp called (allow pass-through)."""
    monkeypatch.delenv("HARNESS_AUTOPILOT_NETWORK", raising=False)

    execvp_calls: list[tuple] = []

    def fake_execvp(prog: str, argv: list[str]) -> None:
        execvp_calls.append((prog, argv))
        # Don't actually replace the process

    monkeypatch.setattr(os, "execvp", fake_execvp)

    result = shim_main(["ls", "-la"])
    # shim_main returns None when execvp is called (process replaced)
    # We monkeypatched execvp to NOT replace, so control returns.
    assert len(execvp_calls) == 1
    assert execvp_calls[0][0] == "ls"


def test_shim_main_allows_when_env_not_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """shim_main: HARNESS_AUTOPILOT_NETWORK=allow → execvp called (not deny)."""
    monkeypatch.setenv("HARNESS_AUTOPILOT_NETWORK", "allow")

    execvp_calls: list[tuple] = []
    monkeypatch.setattr(os, "execvp", lambda p, a: execvp_calls.append((p, a)))

    shim_main(["curl", "http://example.com"])
    assert len(execvp_calls) == 1


def test_shim_main_denies_curl_returns_4(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """shim_main: env=deny + curl → returns 4, audit emitted, stderr has 'refused'."""
    monkeypatch.setenv("HARNESS_AUTOPILOT_NETWORK", "deny")
    monkeypatch.delenv("HARNESS_ALLOW_NETWORK", raising=False)

    # Point audit to a controlled tmp location
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    # Monkeypatch the audit path resolution inside shim_main
    import lib.autopilot_guard as _guard
    monkeypatch.setattr(_guard, "_resolve_audit_path", lambda: audit_path)

    execvp_calls: list[tuple] = []
    monkeypatch.setattr(os, "execvp", lambda p, a: execvp_calls.append((p, a)))

    result = shim_main(["curl", "http://example.com"])

    assert result == 4, f"Expected exit code 4, got {result}"
    assert len(execvp_calls) == 0, "execvp must NOT be called on denied command"

    captured = capsys.readouterr()
    assert "refused" in captured.err.lower() or "curl" in captured.err.lower()

    # Audit must be emitted
    assert audit_path.exists(), "Audit file must exist after deny"
    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) >= 1
    row = json.loads(lines[0])
    assert row["verb"] == "autopilot.network.deny"


def test_shim_main_allows_ls_when_deny(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """shim_main: env=deny + ls → execvp called (ls is not deny-listed)."""
    monkeypatch.setenv("HARNESS_AUTOPILOT_NETWORK", "deny")
    monkeypatch.delenv("HARNESS_ALLOW_NETWORK", raising=False)

    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    import lib.autopilot_guard as _guard
    monkeypatch.setattr(_guard, "_resolve_audit_path", lambda: audit_path)

    execvp_calls: list[tuple] = []
    monkeypatch.setattr(os, "execvp", lambda p, a: execvp_calls.append((p, a)))

    shim_main(["ls", "-la"])

    assert len(execvp_calls) == 1
    assert execvp_calls[0][0] == "ls"


def test_shim_main_denies_git_push_returns_4(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """shim_main: env=deny + git push → returns 4."""
    monkeypatch.setenv("HARNESS_AUTOPILOT_NETWORK", "deny")
    monkeypatch.delenv("HARNESS_ALLOW_NETWORK", raising=False)

    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    import lib.autopilot_guard as _guard
    monkeypatch.setattr(_guard, "_resolve_audit_path", lambda: audit_path)

    monkeypatch.setattr(os, "execvp", lambda p, a: None)

    result = shim_main(["git", "push", "origin", "main"])
    assert result == 4


# ---------------------------------------------------------------------------
# Audit row shape — end-to-end field validation
# ---------------------------------------------------------------------------


def test_audit_row_shape_all_fields_present(tmp_path: Path) -> None:
    """Audit row emitted by emit_deny_audit has verb, command_label, command, cwd, at."""
    audit_path = tmp_path / ".harness" / "audit.log"
    audit_path.parent.mkdir(parents=True)

    argv = ["ssh", "user@host", "-p", "22"]
    emit_deny_audit(argv=argv, command_label="ssh", audit_path=audit_path)

    lines = [l for l in audit_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines, "Audit must have at least one entry"
    row = json.loads(lines[0])

    assert row.get("verb") == "autopilot.network.deny"
    assert row.get("command_label") == "ssh"
    assert isinstance(row.get("command"), str)
    assert isinstance(row.get("cwd"), str)
    assert isinstance(row.get("at"), str)
    # at should be ISO format
    assert "T" in row["at"] or "-" in row["at"]


# ---------------------------------------------------------------------------
# phase_autopilot.run_start sets HARNESS_AUTOPILOT_NETWORK=deny on success
# ---------------------------------------------------------------------------


def _fake_oidc_fetcher(url: str) -> str:
    """TEST-ONLY fake OIDC fetcher."""
    return "fake-oidc-token"


def _fake_oidc_verifier(token: str, expected_claims: dict) -> dict:
    """TEST-ONLY fake OIDC verifier."""
    return {
        "sub": "repo:org/repo:ref:refs/heads/main",
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "https://github.com/org/repo",
        "repository": "org/repo",
        "sha": "abc123def456",
        "workflow": "ci.yml",
        "run_id": "1234567890",
        "run_attempt": "1",
    }


def _ci_env_github(*, by_trust: str = "ci-bot@example.com") -> dict:
    """Minimal GitHub Actions CI environment that satisfies §3.5.1."""
    return {
        "HARNESS_AUTOMATION": "phase",
        "HARNESS_BY_TRUST": by_trust,
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "1234567890",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_WORKFLOW": "ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
    }


def test_run_start_sets_autopilot_network_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run_start sets HARNESS_AUTOPILOT_NETWORK=deny in os.environ on success."""
    from lib import phase_autopilot, phase_lock, phase_txn

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "autopilot_run_id": None,
        "autopilot_mode": None,
        "autopilot_phase_slug": None,
        "autopilot_start_entry_hash": None,
        "cli_budgets_remaining": None,
        "autopilot_allow_network": False,
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={"verb": "phase.set", "by": "seed", "args": {"phase": "plan"}},
        )
        phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)
    finally:
        phase_lock.release_primary(lock)

    # Remove the env var so we can verify run_start sets it
    monkeypatch.delenv("HARNESS_AUTOPILOT_NETWORK", raising=False)

    ci_env = _ci_env_github()

    lock2 = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_autopilot.run_start(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock2,
            phase_slug="plan",
            mode="phase",
            budgets=None,
            allow_network=False,
            skip_anchor_preflight=True,
            anchor_verified=True,
            stdin_is_tty=False,
            env=ci_env,
            oidc_fetcher=_fake_oidc_fetcher,
            oidc_verifier=_fake_oidc_verifier,
        )
    finally:
        phase_lock.release_primary(lock2)

    assert result.exit_code == 0, f"Expected success, got {result}"
    assert os.environ.get("HARNESS_AUTOPILOT_NETWORK") == "deny", (
        "run_start must set HARNESS_AUTOPILOT_NETWORK=deny on success"
    )


def test_run_start_does_not_set_autopilot_network_env_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_start does NOT set HARNESS_AUTOPILOT_NETWORK=deny when it fails."""
    from lib import phase_autopilot, phase_lock, phase_txn

    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"

    # Seed state with execution_mode != manual → triggers already_active failure
    active_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "phase_autopilot",
        "autopilot_run_id": "existing-run",
        "autopilot_mode": "phase",
        "autopilot_phase_slug": "plan",
        "autopilot_start_entry_hash": "abc",
        "cli_budgets_remaining": {"shell_invocations": 50, "file_mutation_ops": 100, "wall_seconds": 300},
        "autopilot_allow_network": False,
        "last_halt": None,
        "last_halt_history": [],
        "state_schema_version": 2,
        "autopilot_started_at_iso": "2026-01-01T00:00:00Z",
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=active_state,
            audit_entry_draft={"verb": "phase.set", "by": "seed", "args": {"phase": "plan"}},
        )
        phase_txn.commit_transaction(scratch, lock=lock, request=req, audit_path=audit_path)
    finally:
        phase_lock.release_primary(lock)

    monkeypatch.delenv("HARNESS_AUTOPILOT_NETWORK", raising=False)

    lock2 = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        result = phase_autopilot.run_start(
            scratch_root=scratch,
            audit_path=audit_path,
            lock_handle=lock2,
            phase_slug="plan",
            mode="phase",
            budgets=None,
            allow_network=False,
            skip_anchor_preflight=True,
            anchor_verified=True,
            env={"HARNESS_OIDC_TEST_MODE": "1"},
        )
    finally:
        phase_lock.release_primary(lock2)

    assert result.exit_code != 0, "Expected failure"
    assert os.environ.get("HARNESS_AUTOPILOT_NETWORK") != "deny", (
        "run_start must NOT set HARNESS_AUTOPILOT_NETWORK=deny on failure"
    )
