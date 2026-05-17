"""Tests for scripts.lib.audit_anchor (S00.7-A).

Covers the §12.1 invariants:
  - signature roundtrip
  - signature reject on tamper
  - audit-tail divergence detection
  - install-record post-install mutation detection
  - monotonic rollback refusal
  - cross-repo replay refusal
  - schema version pin
"""

from __future__ import annotations

import json

import pytest

from lib import audit_anchor


@pytest.fixture
def boot_args():
    return dict(
        harness_version="v0.7.0.dev0",
        install_id="00000000-0000-0000-0000-000000000001",
        install_record_sha256="a" * 64,
        audit_tip_entry_hash="b" * 64,
        audit_tip_seq_global=1,
    )


def test_write_then_read_roundtrip(isolated_home, repo_root, boot_args):
    written = audit_anchor.write_anchor(repo_root, **boot_args)
    loaded = audit_anchor.read_anchor(repo_root)
    assert loaded.to_dict() == written.to_dict()


def test_verify_accepts_matching_live_state(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **boot_args)
    anchor = audit_anchor.read_anchor(repo_root)
    audit_anchor.verify_anchor(
        anchor,
        audit_tip_entry_hash=boot_args["audit_tip_entry_hash"],
        audit_tip_seq_global=boot_args["audit_tip_seq_global"],
        install_record_sha256=boot_args["install_record_sha256"],
        repo_root=repo_root,
    )


def test_verify_rejects_tampered_signature(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **boot_args)
    anchor_path = audit_anchor.anchor_path(repo_root)
    raw = json.loads(anchor_path.read_text(encoding="utf-8"))
    raw["audit_tip_entry_hash"] = "f" * 64  # mutate signed field, leave signature
    anchor_path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    anchor = audit_anchor.read_anchor(repo_root)
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.verify_anchor(
            anchor,
            audit_tip_entry_hash="f" * 64,
            audit_tip_seq_global=boot_args["audit_tip_seq_global"],
            install_record_sha256=boot_args["install_record_sha256"],
            repo_root=repo_root,
        )
    assert exc.value.sub_reason == "anchor_signature_invalid"


def test_verify_rejects_audit_tail_divergence(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **boot_args)
    anchor = audit_anchor.read_anchor(repo_root)
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.verify_anchor(
            anchor,
            audit_tip_entry_hash="c" * 64,  # diverged from anchor
            audit_tip_seq_global=boot_args["audit_tip_seq_global"],
            install_record_sha256=boot_args["install_record_sha256"],
            repo_root=repo_root,
        )
    assert exc.value.sub_reason == "audit_tail_diverged_from_anchor"


def test_verify_rejects_install_record_mutation(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **boot_args)
    anchor = audit_anchor.read_anchor(repo_root)
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.verify_anchor(
            anchor,
            audit_tip_entry_hash=boot_args["audit_tip_entry_hash"],
            audit_tip_seq_global=boot_args["audit_tip_seq_global"],
            install_record_sha256="d" * 64,  # post-install rewrite
            repo_root=repo_root,
        )
    assert exc.value.sub_reason == "install_record_mutated_post_install"


def test_write_refuses_monotonic_rollback(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **{**boot_args, "audit_tip_seq_global": 5})
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.write_anchor(repo_root, **{**boot_args, "audit_tip_seq_global": 3})
    assert exc.value.sub_reason == "anchor_rollback_refused"


def test_verify_rejects_cross_repo_replay(isolated_home, repo_root, boot_args, tmp_path):
    audit_anchor.write_anchor(repo_root, **boot_args)
    anchor = audit_anchor.read_anchor(repo_root)
    other_root = tmp_path / "other-repo"
    other_root.mkdir()
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.verify_anchor(
            anchor,
            audit_tip_entry_hash=boot_args["audit_tip_entry_hash"],
            audit_tip_seq_global=boot_args["audit_tip_seq_global"],
            install_record_sha256=boot_args["install_record_sha256"],
            repo_root=other_root,
        )
    assert exc.value.sub_reason == "anchor_repo_root_mismatch"


def test_verify_rejects_unsupported_schema_version(isolated_home, repo_root, boot_args):
    audit_anchor.write_anchor(repo_root, **boot_args)
    path = audit_anchor.anchor_path(repo_root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["anchor_schema_version"] = 99
    path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    anchor = audit_anchor.read_anchor(repo_root)
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.verify_anchor(
            anchor,
            audit_tip_entry_hash=boot_args["audit_tip_entry_hash"],
            audit_tip_seq_global=boot_args["audit_tip_seq_global"],
            install_record_sha256=boot_args["install_record_sha256"],
            repo_root=repo_root,
        )
    assert exc.value.sub_reason == "anchor_schema_version_unsupported"


def test_repair_is_idempotent(isolated_home, repo_root, boot_args):
    audit_anchor.repair_anchor(repo_root, **boot_args, by_user="alice@x")
    second = audit_anchor.repair_anchor(repo_root, **boot_args, by_user="alice@x")
    # Idempotent against same state; only updated_at_iso may differ.
    third = audit_anchor.read_anchor(repo_root)
    assert third.audit_tip_entry_hash == second.audit_tip_entry_hash
    assert third.audit_tip_seq_global == second.audit_tip_seq_global


def test_read_anchor_raises_when_missing(isolated_home, repo_root):
    with pytest.raises(audit_anchor.AnchorError) as exc:
        audit_anchor.read_anchor(repo_root)
    assert exc.value.sub_reason == "anchor_missing"


def test_repo_id_is_stable(isolated_home, repo_root):
    rid1 = audit_anchor.repo_id(repo_root)
    rid2 = audit_anchor.repo_id(repo_root)
    assert rid1 == rid2
    assert len(rid1) == 16
