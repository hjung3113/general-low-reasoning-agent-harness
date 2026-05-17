"""Integration tests for commit_transaction fence_protected_paths extension.

RED phase: written before implementation (TDD discipline).
Spec: §5.1 (fence integration with TxnRequest), §3.4 (exit 4).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.phase_txn import TxnRequest, commit_transaction
from scripts.lib.fs_fence import FenceDenyError
from scripts.lib.phase_lock import acquire_primary, release_primary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lock(scratch: Path):
    return acquire_primary(scratch)


def _make_audit(tmp_path: Path) -> Path:
    audit = tmp_path / ".harness" / "audit.log"
    audit.parent.mkdir(parents=True, exist_ok=True)
    return audit


def _make_state(
    *,
    execution_mode: str = "phase_autopilot",
    allowed_paths: list | None = None,
) -> dict:
    base = {
        "execution_mode": execution_mode,
        "phase": "execute",
        "allowed_paths": allowed_paths,
        "cli_budgets_remaining": None,
    }
    return base


def _commit_state(
    scratch: Path,
    audit_path: Path,
    state: dict,
    *,
    fence_protected_paths: list[str] | None = None,
    anchor: Path | None = None,
) -> str:
    lock = _make_lock(scratch)
    try:
        kwargs: dict = {}
        if fence_protected_paths is not None:
            kwargs["fence_protected_paths"] = fence_protected_paths
        if anchor is not None:
            kwargs["fence_anchor"] = anchor

        return commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="test.action",
                before_state=state,
                after_state={**state, "phase": "done"},
                audit_entry_draft={"verb": "test.action", "actor": "test"},
                **({} if not kwargs.get("fence_protected_paths") else {"fence_protected_paths": kwargs["fence_protected_paths"]}),
            ),
            audit_path=audit_path,
            **({} if "fence_anchor" not in kwargs else {"fence_anchor": kwargs["fence_anchor"]}),
        )
    finally:
        release_primary(lock)


# ---------------------------------------------------------------------------
# Backward compatibility: default fence_protected_paths=[] → no change
# ---------------------------------------------------------------------------


def test_commit_transaction_default_fence_protected_paths_empty_succeeds(tmp_path: Path):
    """Default TxnRequest (fence_protected_paths=[]) — no fence overhead,
    existing behavior unchanged."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)

    state = _make_state(execution_mode="manual")

    lock = _make_lock(scratch)
    try:
        txn_id = commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="test.compat",
                before_state=state,
                after_state={**state, "phase": "done"},
                audit_entry_draft={"verb": "test.compat", "actor": "test"},
            ),
            audit_path=audit_path,
        )
    finally:
        release_primary(lock)

    assert isinstance(txn_id, str)
    # Verify state file was written
    state_path = scratch / "phase-state.json"
    assert state_path.exists()


def test_txnrequest_default_fence_protected_paths_is_empty_list():
    """TxnRequest default fence_protected_paths should be []."""
    req = TxnRequest(
        action="test",
        before_state=None,
        after_state={"execution_mode": "manual"},
        audit_entry_draft={"verb": "test"},
    )
    assert req.fence_protected_paths == []


# ---------------------------------------------------------------------------
# fence_protected_paths — all paths pass → commit succeeds
# ---------------------------------------------------------------------------


def test_commit_transaction_fence_all_paths_pass(tmp_path: Path):
    """When all fence_protected_paths are allowed, commit proceeds normally."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)
    anchor = tmp_path
    (anchor / "scripts").mkdir()

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock(scratch)
    try:
        txn_id = commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="test.fence_pass",
                before_state=state,
                after_state={**state, "phase": "done"},
                audit_entry_draft={"verb": "test.fence_pass", "actor": "test"},
                fence_protected_paths=["scripts/lib/foo.py"],
            ),
            audit_path=audit_path,
            fence_anchor=anchor,
        )
    finally:
        release_primary(lock)

    assert isinstance(txn_id, str)
    state_path = scratch / "phase-state.json"
    assert state_path.exists()


# ---------------------------------------------------------------------------
# fence_protected_paths — one path denied → FenceDenyError raised, no artefacts
# ---------------------------------------------------------------------------


def test_commit_transaction_fence_denied_raises_before_journal(tmp_path: Path):
    """When a path is denied, FenceDenyError raised before journal/tmp/state created."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)
    anchor = tmp_path
    (anchor / "scripts").mkdir()

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock(scratch)
    try:
        with pytest.raises(FenceDenyError) as exc_info:
            commit_transaction(
                scratch,
                lock=lock,
                request=TxnRequest(
                    action="test.fence_deny",
                    before_state=state,
                    after_state={**state, "phase": "done"},
                    audit_entry_draft={"verb": "test.fence_deny", "actor": "test"},
                    fence_protected_paths=["docs/secret.md"],
                ),
                audit_path=audit_path,
                fence_anchor=anchor,
            )
    finally:
        release_primary(lock)

    err = exc_info.value
    assert err.exit_code == 4

    # Journal and tmp must NOT exist
    from scripts.lib.phase_txn import JOURNAL_NAME, TMP_NAME
    assert not (scratch / JOURNAL_NAME).exists(), "Journal must not be created on deny"
    assert not (scratch / TMP_NAME).exists(), "Tmp must not be created on deny"


def test_commit_transaction_fence_denied_emits_audit_deny_row(tmp_path: Path):
    """FenceDenyError path emits autopilot.fence.deny audit row."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)
    anchor = tmp_path
    (anchor / "scripts").mkdir()

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    lock = _make_lock(scratch)
    try:
        with pytest.raises(FenceDenyError):
            commit_transaction(
                scratch,
                lock=lock,
                request=TxnRequest(
                    action="test.fence_deny_audit",
                    before_state=state,
                    after_state={**state, "phase": "done"},
                    audit_entry_draft={"verb": "test.fence_deny_audit", "actor": "test"},
                    fence_protected_paths=["docs/other.md"],
                ),
                audit_path=audit_path,
                fence_anchor=anchor,
            )
    finally:
        release_primary(lock)

    # Audit must contain fence.deny row
    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    deny_entries = [json.loads(l) for l in lines if json.loads(l).get("verb") == "autopilot.fence.deny"]
    assert len(deny_entries) == 1
    assert deny_entries[0]["path"] == "docs/other.md"


def test_commit_transaction_fence_deny_state_not_created(tmp_path: Path):
    """When fence denies, phase-state.json must NOT be created or modified."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)
    anchor = tmp_path

    state = _make_state(
        execution_mode="phase_autopilot",
        allowed_paths=["scripts/"],
    )

    state_path = scratch / "phase-state.json"
    assert not state_path.exists()

    lock = _make_lock(scratch)
    try:
        with pytest.raises(FenceDenyError):
            commit_transaction(
                scratch,
                lock=lock,
                request=TxnRequest(
                    action="test.no_state",
                    before_state=state,
                    after_state={**state, "phase": "done"},
                    audit_entry_draft={"verb": "test.no_state", "actor": "test"},
                    fence_protected_paths=["evil.sh"],
                ),
                audit_path=audit_path,
                fence_anchor=anchor,
            )
    finally:
        release_primary(lock)

    assert not state_path.exists(), "State file must not be created on fence deny"


# ---------------------------------------------------------------------------
# fence_protected_paths — manual mode skips fence → commit succeeds
# ---------------------------------------------------------------------------


def test_commit_transaction_fence_manual_mode_skips_check(tmp_path: Path):
    """fence_protected_paths non-empty but manual mode → fence skipped, commit ok."""
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    audit_path = _make_audit(tmp_path)
    anchor = tmp_path

    state = _make_state(execution_mode="manual", allowed_paths=[])

    lock = _make_lock(scratch)
    try:
        txn_id = commit_transaction(
            scratch,
            lock=lock,
            request=TxnRequest(
                action="test.manual_skip",
                before_state=state,
                after_state={**state, "phase": "done"},
                audit_entry_draft={"verb": "test.manual_skip", "actor": "test"},
                fence_protected_paths=["any/path.py"],
            ),
            audit_path=audit_path,
            fence_anchor=anchor,
        )
    finally:
        release_primary(lock)

    assert isinstance(txn_id, str)
