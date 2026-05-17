"""S07-prep + S08a review-fix B tests.

Covers:
  P1-B2: run_next_pending (and run_start/run_stop) run crash recovery before state read.
  P1-B3: autopilot_start_entry_hash matches the real audit row's entry_hash (64 hex).
  P2-B1: --allow-network semantics documented (sentinel test).
  P2-B2: _parse_budgets rejects negative and oversized values with exit 2.
  P2-B3: slug fullmatch rejects trailing newline.
  P2-B4: manifest.json has removed_in_version entry for .roo/commands/fsd-phase.md.

Design refs: §1.1, §3.5, §3.5.2, §6
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import approval_nonce, phase_autopilot, phase_lock, phase_txn
from lib.phase_autopilot_cli import _parse_budgets
from lib.fsd_wrappers import _validate_argument


# ---------------------------------------------------------------------------
# Shared fixture (mirrors conftest env fixture)
# ---------------------------------------------------------------------------


def _make_env(tmp_path: Path) -> dict:
    """Create a primed harness environment in tmp_path."""
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

    planning = tmp_path / ".planning" / "phases"
    planning.mkdir(parents=True)
    for slug in ("phase-alpha", "phase-beta"):
        (planning / slug).mkdir()

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [{"email": "alice@example.com", "added_at": "2026-05-17T03:14:15Z", "source": "gitconfig_auto"}],
    }
    (harness / "install-record.json").write_text(json.dumps(install_record, indent=2) + "\n")

    nonce_dir = tmp_path / "out-of-project" / "approval-nonces"
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


def _mint_nonce(nonce_dir: Path, minter_tty: str = "/dev/ttys001") -> approval_nonce.Nonce:
    return approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.autopilot.start",
        minter_tty=minter_tty,
        ttl_seconds=120,
    )


def _start_ci(env: dict) -> phase_autopilot.AutopilotResult:
    """Run run_start via CI env (simpler than TTY path for integration tests)."""
    ci_env = {
        "HARNESS_AUTOMATION": "phase",
        "HARNESS_BY_TRUST": "ci-bot@example.com",
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "1234567890",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_WORKFLOW": "ci.yml",
        "GITHUB_RUN_ATTEMPT": "1",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
    }

    def fake_fetcher(url):
        return "fake-token"

    def fake_verifier(token, claims):
        return {
            "iss": "https://token.actions.githubusercontent.com",
            "sub": "repo:org/repo:ref:refs/heads/main",
            "repository": "org/repo",
            "ref": "refs/heads/main",
            "sha": "abc123def456",
        }

    lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
    try:
        return phase_autopilot.run_start(
            scratch_root=env["scratch"],
            audit_path=env["audit_path"],
            lock_handle=lock,
            phase_slug="phase-alpha",
            mode="phase",
            budgets=None,
            allow_network=False,
            anchor_verified=True,
            skip_anchor_preflight=True,
            repo_root=None,
            roadmap_root=env["roadmap_root"],
            env=ci_env,
            stdin_is_tty=False,
            oidc_fetcher=fake_fetcher,
            oidc_verifier=fake_verifier,
            install_record_root=env["install_record_root"],
        )
    finally:
        phase_lock.release_primary(lock)


def _read_state(env: dict) -> dict:
    state_path = env["scratch"] / phase_txn.STATE_NAME
    return json.loads(state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# P1-B2: crash recovery called before state read in next_pending / start / stop
# ---------------------------------------------------------------------------


class TestCrashRecoveryRunsFirst:
    """Verify that crash recovery executes before any state read in autopilot verbs."""

    def test_next_pending_runs_crash_recovery_first(self, tmp_path: Path):
        """Seed a partial-write journal (row 5: J=1, T=0, A=0), call run_next_pending.
        Crash recovery should roll back the journal (row 5: rollback_journal_only),
        and run_next_pending should then return a sensible result.
        """
        env = _make_env(tmp_path)
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        # Seed a journal for a txn that hasn't touched state or audit yet
        # (simulates crash after journal write, before audit append = row 5).
        journal_path = scratch / phase_txn.JOURNAL_NAME
        journal_payload = {
            "txn_id": "deadbeefdeadbeef" * 2,
            "action": "phase.set",
            "before_sha256": "somehash",
            "after_sha256": "anotherhash",
            "audit_entry_draft": {"verb": "phase.set"},
            "started_at_monotonic": 0.0,
        }
        journal_path.write_text(json.dumps(journal_payload))

        # run_next_pending must run crash recovery (which sees J=1, T=0, A=0,
        # and state_hash != before_sha -> row 10/11 corruption). But since we
        # seeded a valid state (after the initial seed txn), the recovery should
        # find that state_hash != journal.before_sha and audit_txn != journal_txn
        # → row 11 (corruption) → exit 14. Verify that next_pending properly
        # returns this as a non-zero result (not silently ignoring recovery).
        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = phase_autopilot.run_next_pending(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                skip_anchor_preflight=True,
                roadmap_root=env["roadmap_root"],
            )
        finally:
            phase_lock.release_primary(lock)

        # Journal seeded with mismatched hashes → undecidable (row 11 or 10).
        # The important assertion is exit_code != 0, proving recovery ran.
        assert result.exit_code != 0, (
            "Expected non-zero exit from run_next_pending when a corrupted journal "
            "is present (crash recovery should block the read)"
        )

    def test_next_pending_clean_state_succeeds(self, tmp_path: Path):
        """With no journal artifacts (quiescent state), run_next_pending succeeds."""
        env = _make_env(tmp_path)

        lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
        try:
            result = phase_autopilot.run_next_pending(
                scratch_root=env["scratch"],
                audit_path=env["audit_path"],
                lock_handle=lock,
                anchor_verified=True,
                skip_anchor_preflight=True,
                roadmap_root=env["roadmap_root"],
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0
        assert result.next_slug == "phase-alpha"

    def test_next_pending_blocks_on_partial_write_audit(self, tmp_path: Path):
        """Row 12: audit partial write → recovery returns exit 14 → next_pending blocked."""
        env = _make_env(tmp_path)
        scratch = env["scratch"]
        audit_path = env["audit_path"]

        # Corrupt the last line of the audit (partial JSON = malformed tail).
        current = audit_path.read_text(encoding="utf-8")
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write('{"verb":"partial","at":"broken\n')  # intentionally malformed

        lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
        try:
            result = phase_autopilot.run_next_pending(
                scratch_root=scratch,
                audit_path=audit_path,
                lock_handle=lock,
                anchor_verified=True,
                skip_anchor_preflight=True,
                roadmap_root=env["roadmap_root"],
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 14  # crash_recovery_undecidable (audit_partial_write)


# ---------------------------------------------------------------------------
# P1-B3: autopilot_start_entry_hash equals real audit row entry_hash
# ---------------------------------------------------------------------------


class TestAutopilotStartEntryHashMatchesAuditRow:
    """§1.1: autopilot_start_entry_hash must be the real audit entry_hash (64 hex chars)."""

    def test_entry_hash_is_64_hex(self, tmp_path: Path):
        """After run_start, autopilot_start_entry_hash is a 64-char hex string."""
        env = _make_env(tmp_path)
        result = _start_ci(env)
        assert result.exit_code == 0

        state = _read_state(env)
        h = state.get("autopilot_start_entry_hash")
        assert h is not None, "autopilot_start_entry_hash should not be None after start"
        assert len(h) == 64, f"Expected 64-char hex, got {len(h)!r} chars: {h!r}"
        assert all(c in "0123456789abcdef" for c in h.lower()), (
            f"Expected lowercase hex, got {h!r}"
        )

    def test_entry_hash_matches_audit_row(self, tmp_path: Path):
        """After run_start, the state's entry_hash equals the audit row's entry_hash."""
        env = _make_env(tmp_path)
        result = _start_ci(env)
        assert result.exit_code == 0

        state = _read_state(env)
        state_hash = state.get("autopilot_start_entry_hash")
        assert state_hash is not None

        # Read the audit log and find the phase.autopilot.start entry.
        audit_text = env["audit_path"].read_text(encoding="utf-8")
        start_entry = None
        for line in audit_text.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("verb") == "phase.autopilot.start":
                start_entry = entry

        assert start_entry is not None, "phase.autopilot.start audit entry not found"
        audit_entry_hash = start_entry.get("entry_hash")
        assert audit_entry_hash is not None, "entry_hash missing from audit row"
        assert len(audit_entry_hash) == 64, f"audit entry_hash should be 64 hex chars"

        assert state_hash == audit_entry_hash, (
            f"State autopilot_start_entry_hash {state_hash!r} does not match "
            f"audit row entry_hash {audit_entry_hash!r}"
        )

    def test_entry_hash_not_pending(self, tmp_path: Path):
        """autopilot_start_entry_hash must not be the sentinel 'PENDING' string."""
        env = _make_env(tmp_path)
        result = _start_ci(env)
        assert result.exit_code == 0

        state = _read_state(env)
        h = state.get("autopilot_start_entry_hash")
        assert h != "PENDING", "autopilot_start_entry_hash should not be 'PENDING' sentinel"


# ---------------------------------------------------------------------------
# P2-B1: --allow-network semantics sentinel test
# ---------------------------------------------------------------------------


class TestAllowNetworkSemantics:
    """Sentinel test documenting the per-flag re-eval interpretation (audit-label only).

    Per P2-B1 design decision: flag-specific re-authorization is deferred;
    allow_network_by_source records the authorization_source for audit traceability.
    """

    def test_allow_network_by_source_recorded_in_audit(self, tmp_path: Path):
        """When allow_network=True, the audit row records allow_network_by_source."""
        env = _make_env(tmp_path)

        ci_env = {
            "HARNESS_AUTOMATION": "phase",
            "HARNESS_BY_TRUST": "ci-bot@example.com",
            "GITHUB_ACTIONS": "true",
            "GITHUB_RUN_ID": "1234567890",
            "GITHUB_REPOSITORY": "org/repo",
            "GITHUB_SHA": "abc123def456",
            "GITHUB_WORKFLOW": "ci.yml",
            "GITHUB_RUN_ATTEMPT": "1",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.com/oidc",
        }

        def fake_fetcher(url):
            return "fake-token"

        def fake_verifier(token, claims):
            return {
                "iss": "https://token.actions.githubusercontent.com",
                "sub": "repo:org/repo:ref:refs/heads/main",
                "repository": "org/repo",
                "ref": "refs/heads/main",
                "sha": "abc123def456",
            }

        lock = phase_lock.acquire_primary(env["scratch"], timeout_s=2.0)
        try:
            result = phase_autopilot.run_start(
                scratch_root=env["scratch"],
                audit_path=env["audit_path"],
                lock_handle=lock,
                phase_slug="phase-alpha",
                mode="phase",
                budgets=None,
                allow_network=True,  # explicitly enabled
                anchor_verified=True,
                skip_anchor_preflight=True,
                env=ci_env,
                stdin_is_tty=False,
                oidc_fetcher=fake_fetcher,
                oidc_verifier=fake_verifier,
                install_record_root=env["install_record_root"],
            )
        finally:
            phase_lock.release_primary(lock)

        assert result.exit_code == 0

        # The audit row must record allow_network_by_source = authorization_source.
        audit_text = env["audit_path"].read_text(encoding="utf-8")
        start_entry = None
        for line in audit_text.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("verb") == "phase.autopilot.start":
                start_entry = entry

        assert start_entry is not None
        assert start_entry.get("allow_network") is True
        # Per-flag re-eval = audit-label: allow_network_by_source matches
        # authorization_source, not a separate re-verification.
        assert start_entry.get("allow_network_by_source") == start_entry.get(
            "authorization_source"
        ), (
            "allow_network_by_source should equal authorization_source "
            "(per-flag re-eval = audit-label only; flag-specific gate deferred)"
        )


# ---------------------------------------------------------------------------
# P2-B2: _parse_budgets clamps to sane range
# ---------------------------------------------------------------------------


class TestParseBudgetsClamping:
    """_parse_budgets rejects negative and oversized values with exit 2."""

    def test_parse_budgets_rejects_negative(self):
        with pytest.raises(SystemExit) as exc_info:
            _parse_budgets(["shell_invocations=-1"])
        assert exc_info.value.code == 2

    def test_parse_budgets_rejects_oversized(self):
        from lib.phase_autopilot_cli import MAX_BUDGET_VALUE
        oversized = MAX_BUDGET_VALUE + 1
        with pytest.raises(SystemExit) as exc_info:
            _parse_budgets([f"shell_invocations={oversized}"])
        assert exc_info.value.code == 2

    def test_parse_budgets_accepts_zero(self):
        result = _parse_budgets(["shell_invocations=0"])
        assert result == {"shell_invocations": 0}

    def test_parse_budgets_accepts_max(self):
        from lib.phase_autopilot_cli import MAX_BUDGET_VALUE
        result = _parse_budgets([f"shell_invocations={MAX_BUDGET_VALUE}"])
        assert result == {"shell_invocations": MAX_BUDGET_VALUE}

    def test_parse_budgets_rejects_non_integer(self):
        with pytest.raises(SystemExit) as exc_info:
            _parse_budgets(["shell_invocations=abc"])
        assert exc_info.value.code == 2

    def test_parse_budgets_rejects_malformed_no_equals(self):
        with pytest.raises(SystemExit) as exc_info:
            _parse_budgets(["shell_invocations"])
        assert exc_info.value.code == 2

    def test_parse_budgets_valid_multiple_entries(self):
        result = _parse_budgets(["shell_invocations=100", "wall_seconds=300"])
        assert result == {"shell_invocations": 100, "wall_seconds": 300}

    def test_parse_budgets_none_input(self):
        assert _parse_budgets(None) is None

    def test_parse_budgets_empty_list(self):
        assert _parse_budgets([]) is None


# ---------------------------------------------------------------------------
# P2-B3: slug regex fullmatch rejects trailing newline
# ---------------------------------------------------------------------------


class TestSlugFullmatch:
    """_validate_argument uses fullmatch so trailing newline is rejected."""

    def test_slug_with_trailing_newline_rejected(self):
        """'phase-alpha\\n' must be rejected with slug_regex_mismatch."""
        slug, err = _validate_argument("phase-alpha\n")
        assert slug is None
        assert err is not None
        assert err.exit_code == 2
        assert err.sub_reason == "slug_regex_mismatch"

    def test_slug_with_trailing_space_rejected(self):
        """'phase-alpha ' must be rejected (whitespace detected before regex)."""
        slug, err = _validate_argument("phase-alpha ")
        assert slug is None
        assert err is not None
        assert err.exit_code == 2

    def test_valid_slug_accepted(self):
        """'phase-alpha' (no trailing chars) must be accepted."""
        slug, err = _validate_argument("phase-alpha")
        assert err is None
        assert slug == "phase-alpha"

    def test_numeric_slug_accepted(self):
        """'01-init' must be accepted."""
        slug, err = _validate_argument("01-init")
        assert err is None
        assert slug == "01-init"

    def test_none_argument_returns_none_slug(self):
        """None argument → None slug, no error (next-pending path)."""
        slug, err = _validate_argument(None)
        assert slug is None
        assert err is None


# ---------------------------------------------------------------------------
# P2-B4: manifest removed_in_version entry
# ---------------------------------------------------------------------------


class TestManifestRemovedInVersion:
    """harness/manifest.json must contain removed_in_version with fsd-phase.md entry."""

    def test_manifest_has_removed_in_version(self):
        manifest_path = REPO_ROOT / "harness" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "removed_in_version" in data, (
            "manifest.json is missing top-level 'removed_in_version' list (§6)"
        )

    def test_manifest_removed_in_version_is_list(self):
        manifest_path = REPO_ROOT / "harness" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(data["removed_in_version"], list)

    def test_manifest_fsd_phase_entry_present(self):
        manifest_path = REPO_ROOT / "harness" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = data.get("removed_in_version", [])
        paths = [e.get("path") for e in entries]
        assert ".roo/commands/fsd-phase.md" in paths, (
            ".roo/commands/fsd-phase.md not found in removed_in_version"
        )

    def test_manifest_fsd_phase_entry_fields(self):
        manifest_path = REPO_ROOT / "harness" / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = data.get("removed_in_version", [])
        entry = next(
            (e for e in entries if e.get("path") == ".roo/commands/fsd-phase.md"),
            None,
        )
        assert entry is not None
        assert entry.get("removed_in") == "v0.7.0", (
            f"Expected removed_in='v0.7.0', got {entry.get('removed_in')!r}"
        )
        assert entry.get("replaced_by") == ".roo/commands/fsd-run-phase.md", (
            f"Expected replaced_by='.roo/commands/fsd-run-phase.md', got {entry.get('replaced_by')!r}"
        )
