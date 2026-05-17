"""S05-override — `--override-identity --reason <text>` for `phase approve`.

Design refs:
  - §3.1 step 4 — override branch (bypass approvers membership; record
                  `confirmation_kind=override_identity`,
                  `by_source=override_identity`, `override_reason`).
  - §3.1.1 final paragraph — sanitization rules for `--by` / `--reason` /
                  `--override-reason`: max 1024 chars; control chars
                  rejected; newlines normalized.
  - §12.6 — human-presence proof tightening (override still requires nonce).
  - ADR-001 (`docs/adr/2026-05-17-approver-provenance-and-execution-mode.md`)
            — `by_source=override_identity` is the audit discriminator for
            non-installed-record approvers; reason is mandatory.

Tests target `run_approve` directly with dependency injection; the env
fixture is reused from `test_approve_provenance.py` via the local
conftest.

Fault classes asserted:
  - override_reason_missing            exit 6
  - override_reason_invalid_chars      exit 6
  - override_reason_too_long           exit 6
  - approver_not_in_install_record     exit 6 (override-identity NOT in
                                              approvers — Round-2: the
                                              override still must name a
                                              listed approver; it is the
                                              identity *display* that is
                                              overridden, not the gate)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import phase_approve, approval_nonce, phase_lock, phase_txn


# ---------------------------------------------------------------------------
# Local env fixture (mirrors test_approve_provenance.py — keeps this file
# self-contained so reviewers can read it linearly without cross-file
# jumps).
# ---------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path) -> dict:
    scratch = tmp_path / ".scratch"
    scratch.mkdir()
    harness = tmp_path / ".harness"
    harness.mkdir()
    audit_path = harness / "audit.log"
    nonce_dir = tmp_path / "out-of-project" / "approval-nonces"
    nonce_dir.mkdir(parents=True)

    install_record = {
        "harness_version": "v0.7.0",
        "installed_at": "2026-05-17T03:14:15Z",
        "adapters": ["roo"],
        "git_present_at_install": True,
        "approvers": [
            {
                "email": "alice@example.com",
                "added_at": "2026-05-17T03:14:15Z",
                "source": "gitconfig_auto",
            }
        ],
    }
    (harness / "install-record.json").write_text(
        json.dumps(install_record, indent=2, sort_keys=True) + "\n"
    )

    seed_state = {
        "phase": "plan",
        "approved": False,
        "approved_at": None,
        "approved_by": None,
        "execution_mode": "manual",
        "state_schema_version": 2,
    }
    lock = phase_lock.acquire_primary(scratch, timeout_s=2.0)
    try:
        req = phase_txn.TxnRequest(
            action="phase.set",
            before_state=None,
            after_state=seed_state,
            audit_entry_draft={
                "verb": "phase.set", "by": "seed", "args": {"phase": "plan"},
            },
        )
        phase_txn.commit_transaction(
            scratch, lock=lock, request=req, audit_path=audit_path
        )
    finally:
        phase_lock.release_primary(lock)

    return {
        "tmp_path": tmp_path,
        "scratch": scratch,
        "harness": harness,
        "audit_path": audit_path,
        "install_record_path": harness / "install-record.json",
        "nonce_dir": nonce_dir,
    }


def _mint_valid_nonce(nonce_dir: Path, *, minter_tty: str = "/dev/ttys001"):
    return approval_nonce.mint(
        nonce_dir=nonce_dir,
        audience="phase.approve",
        minter_tty=minter_tty,
        ttl_seconds=120,
    )


def _make_args(**overrides):
    base = {
        "by": None,
        "at": None,
        "override_identity": None,
        "override_reason": None,
    }
    base.update(overrides)

    class Ns:
        pass

    ns = Ns()
    for k, v in base.items():
        setattr(ns, k, v)
    return ns


def _run(env, *, stdin_isatty=True, consumer_tty="/dev/ttys002",
         gitconfig_email="alice@example.com", **arg_overrides):
    args = _make_args(**arg_overrides)
    return phase_approve.run_approve(
        args,
        scratch=env["scratch"],
        harness_dir=env["harness"],
        audit_path=env["audit_path"],
        install_record_path=env["install_record_path"],
        nonce_dir=env["nonce_dir"],
        stdin_isatty=stdin_isatty,
        consumer_tty=consumer_tty,
        gitconfig_email_lookup=lambda: gitconfig_email,
        env_vars={},
        skip_anchor_preflight=True,
    )


# ---------------------------------------------------------------------------
# 1. Override identity replaces `by` in audit + `by_source`
# ---------------------------------------------------------------------------


def test_override_identity_replaces_by_in_audit(env):
    """Override identity is the *audit display*; gate is still approvers
    membership. We use `--by alice@example.com` (a listed approver) plus
    `--override-identity alice-alt@example.com --reason "..."`. Audit
    `by` MUST be the override value; `by_source=override_identity`."""
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="lost laptop, using backup identity",
    )
    assert rc.exit_code == 0
    assert rc.by_source == "override_identity"
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["by"] == "alice-alt@example.com"
    assert last["by_source"] == "override_identity"
    assert last["confirmation_kind"] == "override_identity"


# ---------------------------------------------------------------------------
# 2. Override reason mandatory when identity given
# ---------------------------------------------------------------------------


def test_override_identity_without_reason_rejected(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason=None,
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "override_reason_missing"


def test_override_identity_empty_reason_rejected(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="   ",
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "override_reason_missing"


# ---------------------------------------------------------------------------
# 3. Resolved identity (the `--by` / gitconfig value, NOT the override)
# still must be in approvers
# ---------------------------------------------------------------------------


def test_resolved_email_not_in_approvers_rejected_even_with_override(env):
    """Override identity is the audit *display* — the resolved email
    (gitconfig or --by) MUST still be a listed approver. This prevents
    `--override-identity` from being an env-spoof rename.

    Design decision (under-specified): §3.1 step 4 says override
    "bypasses step 3"; we read this as "bypasses the membership check
    for the DISPLAYED identity", NOT "lets any caller approve". The
    operational invariant is "humans listed in install-record approve".
    See ADR-001 + conductor brief.
    """
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="mallory@evil.example",  # NOT in approvers
        override_identity="alice@example.com",
        override_reason="trying to spoof identity",
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "approver_not_in_install_record"


# ---------------------------------------------------------------------------
# 4. Sanitization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_reason,desc", [
    ("contains\x00null", "NUL byte"),
    ("contains\nnewline", "literal LF"),
    ("contains\rcr", "literal CR"),
    ("contains\tcontrol", "tab (control char)"),
    ("contains\x1bescape", "ESC control char"),
    ("contains\x7fdel", "DEL control char"),
    ("bidi‮control", "bidi RLO"),
    ("bidi⁦isolate", "bidi LRI"),
])
def test_override_reason_invalid_chars_rejected(env, bad_reason, desc):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason=bad_reason,
    )
    assert rc.exit_code == 6, f"reason with {desc} should be rejected"
    assert rc.sub_reason == "override_reason_invalid_chars"


def test_override_reason_too_long_rejected(env):
    """§3.1.1 caps reason at 1024 chars."""
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="x" * 1025,
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "override_reason_too_long"


def test_override_reason_at_length_cap_accepted(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="x" * 1024,
    )
    assert rc.exit_code == 0


# ---------------------------------------------------------------------------
# 5. Nonce still required + consumed
# ---------------------------------------------------------------------------


def test_override_still_requires_nonce(env):
    """No nonce minted → human_proof_missing even with override flags."""
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="legit reason",
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "human_proof_missing"


def test_override_consumes_nonce(env):
    nonce = _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="rotating identity",
    )
    assert rc.exit_code == 0
    # Nonce file gone (single-use).
    remaining = list(env["nonce_dir"].glob("*.json"))
    assert not any(p.stem == nonce.nonce_id for p in remaining)


# ---------------------------------------------------------------------------
# 6. TTY still required
# ---------------------------------------------------------------------------


def test_override_still_requires_tty(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        stdin_isatty=False,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="legit",
    )
    assert rc.exit_code == 6
    assert rc.sub_reason == "non_tty_approval_blocked"


# ---------------------------------------------------------------------------
# 7. args.override_reason in audit — byte shape (JSON-encoded)
# ---------------------------------------------------------------------------


def test_audit_records_override_reason_in_args(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason="rotating identity per security policy",
    )
    assert rc.exit_code == 0
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    # `args` may be truncated; if so the override_reason lives in the
    # overflow archive. Verify the in-line shape only when not truncated.
    if "truncated" not in last.get("args", {}):
        assert last["args"]["override_reason"] == \
            "rotating identity per security policy"


# ---------------------------------------------------------------------------
# 8. Regression: without override flags, behavior identical to baseline
# ---------------------------------------------------------------------------


def test_baseline_unchanged_when_no_override_flag(env):
    """`override_identity=None` MUST yield the pre-S05 behavior:
    `by_source=gitconfig_auto`, `confirmation_kind=human_nonce`, audit
    `by=alice@example.com` (the resolved identity)."""
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(env)  # no override
    assert rc.exit_code == 0
    assert rc.by_source == "gitconfig_auto"
    assert rc.resolved_email == "alice@example.com"
    lines = [
        ln for ln in env["audit_path"].read_text().splitlines() if ln.strip()
    ]
    last = json.loads(lines[-1])
    assert last["by"] == "alice@example.com"
    assert last["by_source"] == "gitconfig_auto"
    assert last["confirmation_kind"] == "human_nonce"


# ---------------------------------------------------------------------------
# 9. Override-identity itself is sanitized (same charset as reason)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9b. P2-2 sanitizer parity — ZWJ / ZWNJ / ALM / LS / PS (§12.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("char,name", [
    ("‌", "ZWNJ (U+200C)"),
    ("‍", "ZWJ (U+200D)"),
    ("؜", "ALM (U+061C)"),
    (" ", "LINE SEPARATOR (U+2028)"),
    (" ", "PARAGRAPH SEPARATOR (U+2029)"),
])
def test_sanitizer_rejects_zwj_zwnj_alm_ls_ps(env, char, name):
    """P2-2: §12.6 Trojan-Source parity — zero-width joiners, Arabic
    Letter Mark, and Unicode line/paragraph separators must be rejected
    by the sanitizer (they are visual-spoof / audit-line-framing hazards
    that the original _BIDI_CONTROLS set missed)."""
    _mint_valid_nonce(env["nonce_dir"])
    bad_reason = f"legit reason{char}injected"
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice-alt@example.com",
        override_reason=bad_reason,
    )
    assert rc.exit_code == 6, (
        f"override_reason containing {name} should be rejected"
    )
    assert rc.sub_reason == "override_reason_invalid_chars", (
        f"expected override_reason_invalid_chars for {name}, got {rc.sub_reason!r}"
    )


def test_override_identity_with_control_chars_rejected(env):
    _mint_valid_nonce(env["nonce_dir"])
    rc = _run(
        env,
        by="alice@example.com",
        override_identity="alice\x00alt@example.com",
        override_reason="legit",
    )
    assert rc.exit_code == 6
    assert rc.sub_reason in (
        "override_identity_invalid_chars",
        "override_reason_invalid_chars",
    )
