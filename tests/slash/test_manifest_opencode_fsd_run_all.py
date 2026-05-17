"""Tests that harness/manifest.json includes the .opencode/commands/fsd-run-all.md entry (S09b).

S09b adds /fsd-run-all as a NET-NEW OpenCode command per §4.4b.
This test locks down the presence of the manifest entry and the removed_in_version
entry for the never-existed .opencode/commands/fsd-chain-phase.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "harness" / "manifest.json"
COMMAND_PATH = ".opencode/commands/fsd-run-all.md"
OLD_COMMAND_PATH = ".opencode/commands/fsd-chain-phase.md"
SIBLING_PATH = ".opencode/commands/fsd-run-phase.md"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_files(manifest) -> list[dict]:
    return manifest["files"]


@pytest.fixture(scope="module")
def manifest_removed(manifest) -> list[dict]:
    return manifest.get("removed_in_version", [])


class TestManifestOpencodeRunAllEntry:
    """Verify that .opencode/commands/fsd-run-all.md is declared in manifest files."""

    def test_entry_present_in_files(self, manifest_files):
        paths = [f["path"] for f in manifest_files]
        assert COMMAND_PATH in paths, (
            f"{COMMAND_PATH!r} is missing from harness/manifest.json 'files' array. "
            "Users running `harness install --adapters opencode` will not receive this file."
        )

    def test_entry_policy_harness_owned(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == COMMAND_PATH), None)
        assert entry is not None, f"{COMMAND_PATH!r} not found in manifest files"
        assert entry.get("policy") == "harness-owned", (
            f"Expected policy='harness-owned', got {entry.get('policy')!r}"
        )

    def test_entry_owner_adapter_opencode(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == COMMAND_PATH), None)
        assert entry is not None, f"{COMMAND_PATH!r} not found in manifest files"
        assert entry.get("owner") == "adapter:opencode", (
            f"Expected owner='adapter:opencode', got {entry.get('owner')!r}"
        )

    def test_entry_adapter_opencode(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == COMMAND_PATH), None)
        assert entry is not None, f"{COMMAND_PATH!r} not found in manifest files"
        assert entry.get("adapter") == "opencode", (
            f"Expected adapter='opencode', got {entry.get('adapter')!r}"
        )

    def test_entry_source_matches_path(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == COMMAND_PATH), None)
        assert entry is not None, f"{COMMAND_PATH!r} not found in manifest files"
        assert entry.get("source") == COMMAND_PATH, (
            f"Expected source={COMMAND_PATH!r}, got {entry.get('source')!r}"
        )

    def test_on_disk_file_present(self):
        on_disk = REPO_ROOT / COMMAND_PATH
        assert on_disk.exists(), (
            f"On-disk file {on_disk} does not exist — manifest entry would be broken."
        )

    def test_removed_in_version_entry_for_old_path(self, manifest_removed):
        old_paths = [r["path"] for r in manifest_removed]
        assert OLD_COMMAND_PATH in old_paths, (
            f"{OLD_COMMAND_PATH!r} is missing from 'removed_in_version'. "
            "Should be declared removed in v0.7.0 (replaced by fsd-run-all.md)."
        )

    def test_removed_in_version_version_field(self, manifest_removed):
        entry = next((r for r in manifest_removed if r["path"] == OLD_COMMAND_PATH), None)
        assert entry is not None
        assert entry.get("removed_in") == "v0.7.0", (
            f"Expected removed_in='v0.7.0', got {entry.get('removed_in')!r}"
        )

    def test_removed_in_version_replaced_by(self, manifest_removed):
        entry = next((r for r in manifest_removed if r["path"] == OLD_COMMAND_PATH), None)
        assert entry is not None
        assert entry.get("replaced_by") == COMMAND_PATH, (
            f"Expected replaced_by={COMMAND_PATH!r}, got {entry.get('replaced_by')!r}"
        )

    def test_sibling_parity_same_key_shape(self, manifest_files):
        """fsd-run-all entry must have same key order/shape as fsd-run-phase sibling."""
        run_all = next((f for f in manifest_files if f["path"] == COMMAND_PATH), None)
        run_phase = next((f for f in manifest_files if f["path"] == SIBLING_PATH), None)
        assert run_all is not None, f"{COMMAND_PATH!r} not found"
        assert run_phase is not None, f"{SIBLING_PATH!r} not found"
        assert set(run_all.keys()) == set(run_phase.keys()), (
            f"fsd-run-all entry keys {set(run_all.keys())} differ from "
            f"fsd-run-phase entry keys {set(run_phase.keys())}."
        )

    def test_opencode_commands_siblings_all_present(self, manifest_files):
        """All OpenCode command siblings including fsd-run-all must be present."""
        expected_siblings = {
            ".opencode/commands/discuss.md",
            ".opencode/commands/plan.md",
            ".opencode/commands/execute.md",
            ".opencode/commands/done.md",
            ".opencode/commands/fsd-run-phase.md",
            ".opencode/commands/fsd-run-all.md",
        }
        present = {f["path"] for f in manifest_files}
        missing = expected_siblings - present
        assert not missing, (
            f"These OpenCode command entries are missing from the manifest: {missing}"
        )
