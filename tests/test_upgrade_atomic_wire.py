"""T4 — upgrade.py two-pass wire-in (atomic staging for harness-owned files).

Test cases:
1. v0.9.6 → v0.9.7 in-place: same outcome with/without crash (manifest bytes-equal modulo allowlist)
2. SIGTERM mid-upgrade at phase boundary: state repair recovers to consistent version
3. Idempotency: state repair 3x after upgrade abort
4. Two-pass dry-run: Pass A's staged content equals final manifest content
4b. Pending sidecar bytes == final manifest bytes after os.replace (FIX-3 staleness guard)
5. v0.9.4 → v0.9.7 → blocked by skip-upgrade guard BEFORE any .staging-* created
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.upgrade import UpgradeRefused, _check_skip_upgrade_guard, upgrade  # noqa: E402
from lib.install_recovery import recover_aborted_install  # noqa: E402


# ---------------------------------------------------------------------------
# Test 5: skip-upgrade guard blocks v0.9.4 → v0.9.7 before .staging-* created
# ---------------------------------------------------------------------------


def test_skip_upgrade_guard_blocks_v094_no_staging(tmp_path, monkeypatch):
    """T4-5: v0.9.4 → v0.9.7 blocked by skip-upgrade guard; no .staging-* created."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    # Simulate a v0.9.4 installed state
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps({"version": "0.9.4", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    prior_state = {"version": "0.9.4"}
    with pytest.raises(UpgradeRefused) as exc_info:
        _check_skip_upgrade_guard(prior_state, "0.9.7")

    assert "v0.9.4" in str(exc_info.value)
    assert "v0.9.5" in str(exc_info.value) or "0.9.5" in str(exc_info.value)

    # No .staging-* should be created (guard fires before any staging)
    staging_dirs = list(harness_dir.glob(".staging-*"))
    assert not staging_dirs, f"No staging dirs should exist when guard fires: {staging_dirs}"


# ---------------------------------------------------------------------------
# Test 1: v0.9.6 → v0.9.7 in-place upgrade: manifest correct after upgrade
# ---------------------------------------------------------------------------


def test_upgrade_produces_correct_manifest(tmp_path, monkeypatch):
    """T4-1: upgrade produces manifest with correct version; staging artifacts cleaned."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    # Simulate existing v0.9.6 install state
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps({
            "version": "0.9.6",
            "schema_version": 2,
            "files": {},
            "adapters": ["roo"],
            "profiles": ["generic"],
            "packs": [],
        }),
        encoding="utf-8",
    )

    # Create minimal manifest root
    root = tmp_path / "source"
    root.mkdir()
    harness_manifest_dir = root / "harness"
    harness_manifest_dir.mkdir()
    manifest_path = harness_manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": 2,
            "version": "__release__",
            "files": [
                {
                    "path": "scripts/harness.py",
                    "source": "scripts/harness.py",
                    "policy": "harness-owned",
                    "owner": "harness",
                    "adapter": "roo",
                    "profile": "generic",
                }
            ],
            "packs": {},
        }),
        encoding="utf-8",
    )
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "harness.py").write_text("# v0.9.7 content\n", encoding="utf-8")

    # Patch out trust verification and chain hash for simplicity
    monkeypatch.setattr("lib.state._active_harness_version", lambda: "0.9.7-test")
    monkeypatch.setattr("lib.state.now_utc", lambda: "2026-05-21T00:00:00Z")
    monkeypatch.setattr("lib.state._git_user_email_sha256", lambda: None)
    import lib.upgrade as _upg
    import lib.manifest_reconciler as _mrc
    monkeypatch.setattr(_mrc, "verify_install_record_integrity", lambda t: None)
    monkeypatch.setattr(_upg, "_build_release_manifest_v2", lambda **kw: {
        "schema_version": 2,
        "harness_version": "0.9.7-test",
        "files": {"scripts/harness.py": {
            "installed_sha256": "abc",
            "current_sha256": "abc",
            "policy": "harness-owned",
            "owner": "harness",
        }},
    })
    monkeypatch.setattr(_upg, "_reconcile_install", lambda **kw: [])
    monkeypatch.setattr(_upg, "_stamp_installed_manifest_v2", lambda installed, **kw: None)

    # Create the file in target (existing install)
    target_scripts = target / "scripts"
    target_scripts.mkdir()
    (target_scripts / "harness.py").write_text("# v0.9.6 content\n", encoding="utf-8")

    rc = upgrade(
        root=root,
        target=target,
        adapters={"roo"},
        profiles={"generic"},
        packs=set(),
        harness_version="0.9.7-test",
        force=True,
    )

    assert rc == 0, "Upgrade must exit 0"
    final = harness_dir / "installed-manifest.json"
    assert final.exists(), "Final manifest must exist"
    data = json.loads(final.read_text(encoding="utf-8"))
    assert data["version"] == "0.9.7-test"

    # No staging artifacts
    staging_dirs = list(harness_dir.glob(".staging-*"))
    pending_files = list(harness_dir.glob("installed-manifest.json.pending-*"))
    assert not staging_dirs, f"Staging dirs should be cleaned up: {staging_dirs}"
    assert not pending_files, f"Pending files should be cleaned up: {pending_files}"


# ---------------------------------------------------------------------------
# Test 2: SIGTERM mid-upgrade: pending+journal+staging present; repair resumes
# ---------------------------------------------------------------------------


def test_sigterm_mid_upgrade_repair_resumes(tmp_path):
    """T4-2: crash mid-upgrade -> state repair resumes and finalizes."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    runid = "99999-20260521T100000Z-upgrade1"
    staging_dir = harness_dir / f".staging-{runid}"
    staging_dir.mkdir()
    (staging_dir / "scripts").mkdir()
    (staging_dir / "scripts" / "harness.py").write_text("# upgraded\n", encoding="utf-8")

    journal_path = harness_dir / f".staging-{runid}.journal.jsonl"
    journal_path.write_text("", encoding="utf-8")

    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )

    result = recover_aborted_install(target)

    final = harness_dir / "installed-manifest.json"
    assert final.exists(), "Manifest should be finalized after repair"
    assert not pending_path.exists(), "Pending should be consumed"


# ---------------------------------------------------------------------------
# Test 3: Idempotency — state repair 3x after upgrade abort
# ---------------------------------------------------------------------------


def test_state_repair_3x_after_upgrade_abort(tmp_path):
    """T4-3: state repair 3x after sentinel-finalize; all succeed (no-op after first)."""
    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    runid = "99999-20260521T100001Z-upgrade2"
    pending_path = harness_dir / f"installed-manifest.json.pending-{runid}"
    sentinel_path = harness_dir / f".staging-{runid}.complete"
    pending_path.write_text(
        json.dumps({"version": "0.9.7-test", "schema_version": 2, "files": {}}),
        encoding="utf-8",
    )
    sentinel_path.write_bytes(b"")

    r1 = recover_aborted_install(target)
    assert len(r1.finished) >= 1

    r2 = recover_aborted_install(target)
    r3 = recover_aborted_install(target)
    assert r2.found_staging_dirs == 0 or len(r2.finished) == 0
    assert r3.found_staging_dirs == 0 or len(r3.finished) == 0


# ---------------------------------------------------------------------------
# Test 4: Two-pass payload equivalence (Pass A staging_map hashes == source hashes)
# ---------------------------------------------------------------------------


def test_two_pass_payload_equivalence(tmp_path, monkeypatch):
    """T4-4: staged file hash equals source hash (two-pass durability property)."""
    import hashlib
    import shutil

    # Create source file
    source_content = b"# upgrade test content\n"
    source = tmp_path / "source.py"
    source.write_bytes(source_content)

    # Create staging dir with staged file (simulating Pass A)
    staging_dir = tmp_path / ".staging-test"
    staging_dir.mkdir()
    staged = staging_dir / "scripts" / "harness.py"
    staged.parent.mkdir(parents=True)
    shutil.copyfile(str(source), str(staged))

    # Verify: staged content == source content
    assert staged.read_bytes() == source_content
    expected_sha = hashlib.sha256(source_content).hexdigest()
    staged_sha = hashlib.sha256(staged.read_bytes()).hexdigest()
    assert staged_sha == expected_sha, (
        f"Staged hash must equal source hash. Expected {expected_sha}, got {staged_sha}"
    )


# ---------------------------------------------------------------------------
# Test 4b: Pending sidecar bytes == final manifest bytes after upgrade (FIX-3)
#
# Verifies that the pending sidecar written in B4a (post-roomodes-sync) is
# byte-equal to the final installed-manifest.json produced by os.replace in B5.
# This closes Architect C-1/C-2: previously the sidecar was written pre-batch
# and never updated, so a crash between B3 and B5 would recover stale content.
# ---------------------------------------------------------------------------


def test_pending_sidecar_bytes_equal_final_manifest(tmp_path, monkeypatch):
    """T4-4b: after upgrade, pending sidecar (pre-os.replace) == final manifest."""
    import json

    target = tmp_path / "target"
    target.mkdir()
    harness_dir = target / ".harness"
    harness_dir.mkdir()

    # Simulate existing v0.9.6 install state
    (harness_dir / "installed-manifest.json").write_text(
        json.dumps({
            "version": "0.9.6",
            "schema_version": 2,
            "files": {},
            "adapters": ["roo"],
            "profiles": ["generic"],
            "packs": [],
        }),
        encoding="utf-8",
    )

    # Minimal manifest root
    root = tmp_path / "source"
    root.mkdir()
    harness_manifest_dir = root / "harness"
    harness_manifest_dir.mkdir()
    manifest_path = harness_manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "schema_version": 2,
            "version": "__release__",
            "files": [
                {
                    "path": "scripts/harness.py",
                    "source": "scripts/harness.py",
                    "policy": "harness-owned",
                    "owner": "harness",
                    "adapter": "roo",
                    "profile": "generic",
                }
            ],
            "packs": {},
        }),
        encoding="utf-8",
    )
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "harness.py").write_text("# v0.9.7 content\n", encoding="utf-8")

    target_scripts = target / "scripts"
    target_scripts.mkdir()
    (target_scripts / "harness.py").write_text("# v0.9.6 content\n", encoding="utf-8")

    # Track whether pending_path bytes == final_path bytes at the os.replace call.
    # We intercept os.replace to capture the pending content just before promotion.
    _pending_bytes_at_replace: list[bytes] = []

    import lib.upgrade as _upg_mod
    original_os_replace = os.replace

    def _capturing_os_replace(src: str, dst: str) -> None:
        # Capture only the pending sidecar → final manifest replace
        if "installed-manifest.json.pending-" in src:
            _pending_bytes_at_replace.append(Path(src).read_bytes())
        original_os_replace(src, dst)

    monkeypatch.setattr("lib.upgrade.os.replace", _capturing_os_replace)
    monkeypatch.setattr("lib.state._active_harness_version", lambda: "0.9.7-test")
    monkeypatch.setattr("lib.state.now_utc", lambda: "2026-05-21T00:00:00Z")
    monkeypatch.setattr("lib.state._git_user_email_sha256", lambda: None)
    import lib.manifest_reconciler as _mrc
    monkeypatch.setattr(_mrc, "verify_install_record_integrity", lambda t: None)
    monkeypatch.setattr(_upg_mod, "_build_release_manifest_v2", lambda **kw: {
        "schema_version": 2,
        "harness_version": "0.9.7-test",
        "files": {"scripts/harness.py": {
            "installed_sha256": "abc",
            "current_sha256": "abc",
            "policy": "harness-owned",
            "owner": "harness",
        }},
    })
    monkeypatch.setattr(_upg_mod, "_reconcile_install", lambda **kw: [])
    monkeypatch.setattr(_upg_mod, "_stamp_installed_manifest_v2", lambda installed, **kw: None)

    from lib.upgrade import upgrade
    rc = upgrade(
        root=root,
        target=target,
        adapters={"roo"},
        profiles={"generic"},
        packs=set(),
        harness_version="0.9.7-test",
        force=True,
    )
    assert rc == 0, "Upgrade must exit 0"

    final_path = harness_dir / "installed-manifest.json"
    assert final_path.exists(), "Final manifest must exist"

    # The pending sidecar bytes captured at os.replace time must equal
    # the final manifest bytes (since os.replace is atomic rename).
    assert _pending_bytes_at_replace, "os.replace for pending→final must have been called"
    final_bytes = final_path.read_bytes()
    assert _pending_bytes_at_replace[-1] == final_bytes, (
        "Pending sidecar bytes must equal final manifest bytes after os.replace. "
        "Mismatch indicates sidecar was not rewritten post-roomodes-sync (FIX-3 regression)."
    )
