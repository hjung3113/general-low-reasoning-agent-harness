"""S10d — Windows degraded posture + PowerShell/.cmd shim tests (§5.2).

Tests:
  A. detect_network_guard_posture — posture values on linux/darwin/win32/allow_network
  B. run_start audit field — network_guard_posture stamped in verb=phase.autopilot.start
  C. Windows chain-mode exit 11 (without --accept-degraded or --allow-network)
  D. File-presence + contract-string verification for .ps1 and .cmd wrappers

Design refs:
  - §5.2 lines 909-916 — Windows two-track: WARN + degraded posture
  - §3.4 — exit 11 windows_containment_degraded
  - §5.2 line 916 — network_guard_posture values
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo root (for file-presence tests)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Part A: detect_network_guard_posture
# ---------------------------------------------------------------------------

from lib.autopilot_guard import detect_network_guard_posture


class TestDetectNetworkGuardPosture:
    """Unit tests for detect_network_guard_posture (§5.2 line 916)."""

    def test_detect_posture_returns_posix_audit_guard_on_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        result = detect_network_guard_posture(allow_network=False)
        assert result == "posix_audit_guard"

    def test_detect_posture_returns_posix_audit_guard_on_darwin(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = detect_network_guard_posture(allow_network=False)
        assert result == "posix_audit_guard"

    def test_detect_posture_returns_windows_degraded(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        result = detect_network_guard_posture(allow_network=False)
        assert result == "windows_audit_guard_degraded"

    def test_detect_posture_returns_windows_degraded_on_win_prefix_variant(self, monkeypatch):
        """sys.platform may be 'win32' or start with 'win' on Windows."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = detect_network_guard_posture(allow_network=False)
        assert result == "windows_audit_guard_degraded"

    def test_detect_posture_returns_network_allowed_when_allow_network(self):
        """allow_network=True returns 'network_allowed' regardless of platform."""
        result = detect_network_guard_posture(allow_network=True)
        assert result == "network_allowed"

    def test_detect_posture_network_allowed_overrides_windows(self, monkeypatch):
        """allow_network=True on Windows still returns 'network_allowed'."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = detect_network_guard_posture(allow_network=True)
        assert result == "network_allowed"

    def test_detect_posture_accept_degraded_windows_does_not_change_posture(self, monkeypatch):
        """accept_degraded_windows=True does not change the posture value."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = detect_network_guard_posture(
            allow_network=False, accept_degraded_windows=True
        )
        assert result == "windows_audit_guard_degraded"

    def test_detect_posture_wsl_is_posix(self, monkeypatch):
        """WSL reports sys.platform='linux' — treated as POSIX."""
        monkeypatch.setattr(sys, "platform", "linux")
        result = detect_network_guard_posture(allow_network=False)
        assert result == "posix_audit_guard"


# ---------------------------------------------------------------------------
# Part B: run_start audit field — network_guard_posture stamped
# ---------------------------------------------------------------------------

from lib import approval_nonce, phase_autopilot, phase_lock, phase_txn


@pytest.fixture
def harness_env(tmp_path: Path) -> dict:
    """Primed harness root with scratch, audit, roadmap, install-record, and nonce dir."""
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
        phase_txn.commit_transaction(
            scratch,
            lock=lock,
            request=phase_txn.TxnRequest(
                action="phase.set",
                before_state=None,
                after_state=seed_state,
                audit_entry_draft={"verb": "phase.set", "by": "seed", "args": {"phase": "plan"}},
            ),
            audit_path=audit_path,
        )
    finally:
        phase_lock.release_primary(lock)

    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z", "source": "gitconfig_auto"}
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    )

    nonce_dir = tmp_path / "nonces"
    nonce_dir.mkdir(parents=True)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "roadmap_root": planning,
        "install_record_root": tmp_path,
        "nonce_dir": nonce_dir,
    }


def _mint_and_start(
    env: dict,
    *,
    phase_slug: str = "phase-alpha",
    mode: str = "phase",
    allow_network: bool = False,
    accept_degraded_windows_containment: bool = False,
    monkeypatch=None,
    fake_platform: str | None = None,
) -> phase_autopilot.AutopilotResult:
    """Mint nonce + call run_start; return result."""
    nonce_dir = env["nonce_dir"]
    nonce = approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.autopilot.start",
        minter_tty="/dev/ttys001",
        ttl_seconds=120,
    )
    if monkeypatch and fake_platform:
        monkeypatch.setattr(sys, "platform", fake_platform)
    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug=phase_slug,
            mode=mode,
            budgets=None,
            allow_network=allow_network,
            anchor_verified=True,
            skip_anchor_preflight=True,
            accept_degraded_windows_containment=accept_degraded_windows_containment,
            repo_root=None,
            roadmap_root=env["roadmap_root"],
            env=None,
            stdin_is_tty=True,
            consumer_tty="/dev/ttys002",
            nonce_audience="phase.autopilot.start",
            nonce_dir=nonce_dir,
            by_email="alice@example.com",
            install_record_root=env["install_record_root"],
            oidc_fetcher=None,
            oidc_verifier=None,
        )
    finally:
        phase_lock.release_primary(lock)


def _read_audit_entries(audit_path: Path) -> list[dict]:
    """Parse all JSON lines from audit_path."""
    entries = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


class TestRunStartAuditCarriesNetworkGuardPosture:
    """Verify network_guard_posture field on verb=phase.autopilot.start (§5.2 line 916)."""

    def test_audit_posture_posix_audit_guard(self, harness_env, monkeypatch):
        """On POSIX (linux), audit entry has network_guard_posture=posix_audit_guard."""
        monkeypatch.setattr(sys, "platform", "linux")
        result = _mint_and_start(harness_env)
        assert result.exit_code == 0, f"expected success, got {result}"
        entries = _read_audit_entries(harness_env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "posix_audit_guard", (
            f"expected network_guard_posture='posix_audit_guard', got {entry.get('network_guard_posture')!r}"
        )

    def test_audit_posture_network_allowed(self, harness_env, monkeypatch):
        """With allow_network=True, audit entry has network_guard_posture=network_allowed."""
        monkeypatch.setattr(sys, "platform", "linux")
        result = _mint_and_start(harness_env, allow_network=True)
        assert result.exit_code == 0, f"expected success, got {result}"
        entries = _read_audit_entries(harness_env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "network_allowed", (
            f"expected network_guard_posture='network_allowed', got {entry.get('network_guard_posture')!r}"
        )

    def test_audit_posture_windows_degraded(self, harness_env, monkeypatch):
        """On Windows, audit entry has network_guard_posture=windows_audit_guard_degraded."""
        monkeypatch.setattr(sys, "platform", "win32")
        # accept_degraded=True to bypass exit-11 so we reach the audit step
        result = _mint_and_start(
            harness_env,
            mode="chain",
            accept_degraded_windows_containment=True,
            monkeypatch=monkeypatch,
            fake_platform=None,  # already patched above
        )
        assert result.exit_code == 0, f"expected success (with accept_degraded), got {result}"
        entries = _read_audit_entries(harness_env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "windows_audit_guard_degraded", (
            f"expected network_guard_posture='windows_audit_guard_degraded', "
            f"got {entry.get('network_guard_posture')!r}"
        )

    def test_audit_posture_windows_with_allow_network_is_network_allowed(self, harness_env, monkeypatch):
        """Windows + allow_network=True → network_guard_posture=network_allowed."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = _mint_and_start(harness_env, allow_network=True)
        assert result.exit_code == 0, f"expected success, got {result}"
        entries = _read_audit_entries(harness_env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "network_allowed", (
            f"expected network_guard_posture='network_allowed', got {entry.get('network_guard_posture')!r}"
        )


# ---------------------------------------------------------------------------
# Part C: Windows chain-mode exit 11 + accept-degraded success path
# ---------------------------------------------------------------------------


class TestWindowsChainModeContainment:
    """Windows + chain mode without accept-degraded or allow-network → exit 11 (§3.4 + §3.5)."""

    def test_windows_chain_without_accept_degraded_or_allow_network_exits_11(
        self, harness_env, monkeypatch
    ):
        """Windows + chain + neither flag → exit 11 windows_containment_degraded."""
        monkeypatch.setattr(sys, "platform", "win32")
        # Mint nonce first
        nonce = approval_nonce.mint(
            nonce_dir=harness_env["nonce_dir"],
            audience="phase.autopilot.start",
            minter_tty="/dev/ttys001",
            ttl_seconds=120,
        )
        lock = phase_lock.acquire_primary(harness_env["scratch"], timeout_s=2.0)
        try:
            result = phase_autopilot.run_start(
                scratch_root=harness_env["scratch"],
                audit_path=harness_env["audit_path"],
                lock_handle=lock,
                phase_slug="phase-alpha",
                mode="chain",
                budgets=None,
                allow_network=False,
                anchor_verified=True,
                skip_anchor_preflight=True,
                accept_degraded_windows_containment=False,
                repo_root=None,
                roadmap_root=harness_env["roadmap_root"],
                env=None,
                stdin_is_tty=True,
                consumer_tty="/dev/ttys002",
                nonce_audience="phase.autopilot.start",
                nonce_dir=harness_env["nonce_dir"],
                by_email="alice@example.com",
                install_record_root=harness_env["install_record_root"],
                oidc_fetcher=None,
                oidc_verifier=None,
            )
        finally:
            phase_lock.release_primary(lock)
        assert result.exit_code == 11, (
            f"expected exit 11 (windows_containment_degraded), got {result.exit_code}"
        )
        assert result.sub_reason == "windows_containment_degraded"

    def test_windows_chain_with_accept_degraded_succeeds_with_posture_degraded_in_audit(
        self, harness_env, monkeypatch
    ):
        """Windows + chain + accept_degraded=True → success + audit posture=windows_audit_guard_degraded."""
        monkeypatch.setattr(sys, "platform", "win32")
        result = _mint_and_start(
            harness_env,
            mode="chain",
            accept_degraded_windows_containment=True,
        )
        assert result.exit_code == 0, (
            f"expected success with accept_degraded=True, got {result}"
        )
        entries = _read_audit_entries(harness_env["audit_path"])
        start_entries = [e for e in entries if e.get("verb") == "phase.autopilot.start"]
        assert start_entries, "no phase.autopilot.start audit entry found"
        entry = start_entries[0]
        assert entry.get("network_guard_posture") == "windows_audit_guard_degraded"


# ---------------------------------------------------------------------------
# Part D: File-presence + contract-string verification
# ---------------------------------------------------------------------------


PS1_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard.ps1"
CURL_CMD_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard_wrappers" / "curl.cmd"
GH_CMD_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard_wrappers" / "gh.cmd"
GIT_CMD_PATH = REPO_ROOT / "scripts" / "lib" / "autopilot_guard_wrappers" / "git.cmd"

# Required contract strings that must appear in the files
_PS1_REQUIRED = [
    "HARNESS_AUTOPILOT_NETWORK",
    "refused:",
    "exit 4",
    "windows_audit_guard_degraded",
    "network_guard_posture",
]
_CURL_CMD_REQUIRED = [
    "HARNESS_AUTOPILOT_NETWORK",
    "refused: curl",
    "exit /b 4",
]
_GH_CMD_REQUIRED = [
    "HARNESS_AUTOPILOT_NETWORK",
    "refused: gh",
    "exit /b 4",
]
_GIT_CMD_REQUIRED = [
    "HARNESS_AUTOPILOT_NETWORK",
    "push",
    "pull",
    "fetch",
    "clone",
    "exit /b 4",
    "refused:",
]


class TestAutopilotGuardPs1:
    """Verify autopilot_guard.ps1 exists and contains required contract strings."""

    def test_autopilot_guard_ps1_exists(self):
        assert PS1_PATH.exists(), (
            f"autopilot_guard.ps1 not found at {PS1_PATH}. "
            "S10d requires this file to be shipped as a static Windows degraded network guard."
        )

    def test_autopilot_guard_ps1_contains_required_contract(self):
        content = PS1_PATH.read_text(encoding="utf-8")
        for required in _PS1_REQUIRED:
            assert required in content, (
                f"autopilot_guard.ps1 missing required contract string: {required!r}"
            )

    def test_autopilot_guard_ps1_has_deny_list_functions(self):
        content = PS1_PATH.read_text(encoding="utf-8")
        for cmd in ("curl", "wget", "nc", "ssh", "scp", "rsync", "gh", "glab"):
            assert f"function {cmd}" in content, (
                f"autopilot_guard.ps1 missing deny-list function for {cmd!r}"
            )

    def test_autopilot_guard_ps1_has_git_subcommand_filter(self):
        content = PS1_PATH.read_text(encoding="utf-8")
        assert "function git" in content, "autopilot_guard.ps1 missing git subcommand filter"
        for sub in ("push", "pull", "fetch", "clone"):
            assert sub in content, f"autopilot_guard.ps1 missing git subcommand: {sub!r}"


class TestAutopilotGuardCurlCmd:
    """Verify curl.cmd exists and contains required contract strings."""

    def test_autopilot_guard_curl_cmd_exists(self):
        assert CURL_CMD_PATH.exists(), f"curl.cmd not found at {CURL_CMD_PATH}"

    def test_autopilot_guard_curl_cmd_contains_required_contract(self):
        content = CURL_CMD_PATH.read_text(encoding="utf-8")
        for required in _CURL_CMD_REQUIRED:
            assert required in content, (
                f"curl.cmd missing required contract string: {required!r}"
            )

    def test_autopilot_guard_curl_cmd_has_pass_through(self):
        content = CURL_CMD_PATH.read_text(encoding="utf-8")
        assert "where curl" in content or "findstr" in content, (
            "curl.cmd should have a pass-through mechanism for real curl"
        )


class TestAutopilotGuardGhCmd:
    """Verify gh.cmd exists and contains required contract strings."""

    def test_autopilot_guard_gh_cmd_exists(self):
        assert GH_CMD_PATH.exists(), f"gh.cmd not found at {GH_CMD_PATH}"

    def test_autopilot_guard_gh_cmd_contains_required_contract(self):
        content = GH_CMD_PATH.read_text(encoding="utf-8")
        for required in _GH_CMD_REQUIRED:
            assert required in content, (
                f"gh.cmd missing required contract string: {required!r}"
            )


class TestAutopilotGuardGitCmd:
    """Verify git.cmd exists, contains required contract strings, and filters subcommands."""

    def test_autopilot_guard_git_cmd_exists(self):
        assert GIT_CMD_PATH.exists(), f"git.cmd not found at {GIT_CMD_PATH}"

    def test_autopilot_guard_git_cmd_contains_required_contract(self):
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        for required in _GIT_CMD_REQUIRED:
            assert required in content, (
                f"git.cmd missing required contract string: {required!r}"
            )

    def test_autopilot_guard_git_cmd_filters_subcommands(self):
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        for sub in ("push", "pull", "fetch", "clone"):
            assert sub in content, f"git.cmd missing denied subcommand: {sub!r}"

    def test_autopilot_guard_git_cmd_has_pass_through(self):
        content = GIT_CMD_PATH.read_text(encoding="utf-8")
        assert "where git" in content or "%%i" in content, (
            "git.cmd should have a pass-through mechanism for non-denied subcommands"
        )
