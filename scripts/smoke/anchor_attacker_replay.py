#!/usr/bin/env python3
"""Smoke: out-of-repo audit-tip anchor defeats repo-local replay attacker.

Required by design doc §9 S00.7-anchor verify command:

    python scripts/smoke/anchor_attacker_replay.py

Scenarios (each runs against an isolated tempdir HOME + tempdir repo, so the
script is safe to run on a developer workstation; nothing under the real
``~/.harness`` is mutated):

  1. **Replay attack rejected.** Mint anchor at seq=5. Attacker rewinds
     live audit tail to a stale-but-valid entry from seq=2 and corresponding
     entry_hash. ``verify_anchor`` MUST raise ``audit_tail_diverged_from_anchor``.
  2. **Signature tamper rejected.** Mint anchor. Attacker rewrites the
     anchor file body in place. ``verify_anchor`` MUST raise
     ``anchor_signature_invalid``.
  3. **Install-record swap rejected.** Mint anchor. Attacker rewrites
     ``install-record.json`` to add their own approver email. The new file
     hash differs from the recorded ``install_record_sha256``.
     ``verify_anchor`` MUST raise ``install_record_mutated_post_install``.
  4. **Rollback write refused.** After write at seq=5, ``write_anchor``
     called again with seq=3 MUST raise ``anchor_rollback_refused``.
  5. **Cross-repo replay refused.** Anchor minted for repo A cannot
     verify when passed with repo B's path. MUST raise
     ``anchor_repo_root_mismatch``.

Exit codes:
  0  every scenario asserted the expected sub_reason
  1  any scenario failed (verifier accepted attacker input)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import audit_anchor, secret_key  # noqa: E402


SCENARIOS = (
    "replay_attack_rejected",
    "signature_tamper_rejected",
    "install_record_swap_rejected",
    "rollback_write_refused",
    "cross_repo_replay_refused",
)


def _setup_home(tmp: Path) -> Path:
    home = tmp / "home"
    home.mkdir(parents=True)
    os.environ["HOME"] = str(home)
    os.environ["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    # Reset the rollback cache so successive scenarios in one process see a
    # clean slate.
    try:
        audit_anchor.reset_seen_for_testing()
    except Exception:  # pragma: no cover - defensive
        pass
    return home


def _new_repo(tmp: Path, name: str) -> Path:
    root = tmp / name
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".scratch").mkdir(parents=True, exist_ok=True)
    return root


def _boot_args(
    *,
    seq: int = 1,
    entry_hash: str = "b" * 64,
    install_record_sha256: str = "a" * 64,
) -> dict[str, object]:
    return dict(
        harness_version="v0.7.0.dev0",
        install_id="00000000-0000-0000-0000-000000000001",
        install_record_sha256=install_record_sha256,
        audit_tip_entry_hash=entry_hash,
        audit_tip_seq_global=seq,
    )


def _assert_raises(scenario: str, expected_sub_reason: str, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except audit_anchor.AnchorError as exc:
        if exc.sub_reason == expected_sub_reason:
            print(f"PASS  {scenario}: rejected with sub_reason={expected_sub_reason}")
            return True
        print(
            f"FAIL  {scenario}: got sub_reason={exc.sub_reason!r}, "
            f"expected {expected_sub_reason!r}"
        )
        return False
    print(f"FAIL  {scenario}: verifier did NOT raise (attacker would succeed!)")
    return False


def run_replay_attack_rejected(tmp: Path) -> bool:
    repo = _new_repo(tmp, "repo-replay")
    audit_anchor.write_anchor(repo, **_boot_args(seq=5, entry_hash="b" * 64))
    anchor = audit_anchor.read_anchor(repo)
    # Attacker rewrites audit.log so live tail shows seq=2's entry_hash.
    return _assert_raises(
        "replay_attack_rejected",
        "audit_tail_diverged_from_anchor",
        audit_anchor.verify_anchor,
        anchor,
        audit_tip_entry_hash="2" * 64,
        audit_tip_seq_global=2,
        install_record_sha256="a" * 64,
        repo_root=repo,
    )


def run_signature_tamper_rejected(tmp: Path) -> bool:
    repo = _new_repo(tmp, "repo-tamper")
    audit_anchor.write_anchor(repo, **_boot_args(seq=1))
    path = audit_anchor.anchor_path(repo)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["audit_tip_entry_hash"] = "0" * 64  # mutate signed field; signature stays old
    path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    anchor = audit_anchor.read_anchor(repo)
    return _assert_raises(
        "signature_tamper_rejected",
        "anchor_signature_invalid",
        audit_anchor.verify_anchor,
        anchor,
        audit_tip_entry_hash="0" * 64,
        audit_tip_seq_global=1,
        install_record_sha256="a" * 64,
        repo_root=repo,
    )


def run_install_record_swap_rejected(tmp: Path) -> bool:
    repo = _new_repo(tmp, "repo-record-swap")
    audit_anchor.write_anchor(repo, **_boot_args(seq=1, install_record_sha256="a" * 64))
    anchor = audit_anchor.read_anchor(repo)
    return _assert_raises(
        "install_record_swap_rejected",
        "install_record_mutated_post_install",
        audit_anchor.verify_anchor,
        anchor,
        audit_tip_entry_hash="b" * 64,
        audit_tip_seq_global=1,
        install_record_sha256="d" * 64,  # attacker rewrote install-record.json
        repo_root=repo,
    )


def run_rollback_write_refused(tmp: Path) -> bool:
    repo = _new_repo(tmp, "repo-rollback")
    audit_anchor.write_anchor(repo, **_boot_args(seq=5))
    return _assert_raises(
        "rollback_write_refused",
        "anchor_rollback_refused",
        audit_anchor.write_anchor,
        repo,
        **_boot_args(seq=3),
    )


def run_cross_repo_replay_refused(tmp: Path) -> bool:
    repo_a = _new_repo(tmp, "repo-a")
    repo_b = _new_repo(tmp, "repo-b")
    audit_anchor.write_anchor(repo_a, **_boot_args(seq=1))
    anchor_a = audit_anchor.read_anchor(repo_a)
    return _assert_raises(
        "cross_repo_replay_refused",
        "anchor_repo_root_mismatch",
        audit_anchor.verify_anchor,
        anchor_a,
        audit_tip_entry_hash="b" * 64,
        audit_tip_seq_global=1,
        install_record_sha256="a" * 64,
        repo_root=repo_b,
    )


def main() -> int:
    handlers = {
        "replay_attack_rejected": run_replay_attack_rejected,
        "signature_tamper_rejected": run_signature_tamper_rejected,
        "install_record_swap_rejected": run_install_record_swap_rejected,
        "rollback_write_refused": run_rollback_write_refused,
        "cross_repo_replay_refused": run_cross_repo_replay_refused,
    }
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="harness-anchor-smoke-") as tmp_str:
        tmp = Path(tmp_str)
        for name in SCENARIOS:
            _setup_home(tmp / name)
            ok = handlers[name](tmp / name)
            if not ok:
                failures.append(name)
    if failures:
        print(f"\nFAIL anchor_attacker_replay: {len(failures)} scenario(s) failed: {failures}")
        return 1
    print(f"\nOK anchor_attacker_replay: {len(SCENARIOS)} scenarios passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
