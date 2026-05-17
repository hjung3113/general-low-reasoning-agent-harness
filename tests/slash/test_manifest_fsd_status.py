"""Tests that harness/manifest.json includes both fsd-status entries (§12.11).

Validates the Roo and OpenCode manifest entries for the /fsd-status slash
command, added in S15 step 2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "harness" / "manifest.json"

ROO_COMMAND_PATH = ".roo/commands/fsd-status.md"
OPENCODE_COMMAND_PATH = ".opencode/commands/fsd-status.md"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest_files(manifest) -> list[dict]:
    return manifest["files"]


class TestManifestRooFsdStatusEntry:
    """Verify that .roo/commands/fsd-status.md is declared in manifest files."""

    def test_entry_present_in_files(self, manifest_files):
        paths = [f["path"] for f in manifest_files]
        assert ROO_COMMAND_PATH in paths, (
            f"{ROO_COMMAND_PATH!r} is missing from harness/manifest.json 'files' array. "
            "Users running `harness install --adapters roo` will not receive this file."
        )

    def test_entry_policy_harness_owned(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == ROO_COMMAND_PATH), None)
        assert entry is not None, f"{ROO_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("policy") == "harness-owned", (
            f"Expected policy='harness-owned', got {entry.get('policy')!r}"
        )

    def test_entry_adapter_roo(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == ROO_COMMAND_PATH), None)
        assert entry is not None, f"{ROO_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("adapter") == "roo", (
            f"Expected adapter='roo', got {entry.get('adapter')!r}"
        )

    def test_entry_owner_adapter_roo(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == ROO_COMMAND_PATH), None)
        assert entry is not None, f"{ROO_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("owner") == "adapter:roo", (
            f"Expected owner='adapter:roo', got {entry.get('owner')!r}"
        )

    def test_entry_source_matches_path(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == ROO_COMMAND_PATH), None)
        assert entry is not None, f"{ROO_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("source") == ROO_COMMAND_PATH, (
            f"Expected source={ROO_COMMAND_PATH!r}, got {entry.get('source')!r}"
        )

    def test_on_disk_file_present(self):
        on_disk = REPO_ROOT / ROO_COMMAND_PATH
        assert on_disk.exists(), (
            f"On-disk file {on_disk} does not exist — manifest entry would be broken."
        )


class TestManifestOpencodeFsdStatusEntry:
    """Verify that .opencode/commands/fsd-status.md is declared in manifest files."""

    def test_entry_present_in_files(self, manifest_files):
        paths = [f["path"] for f in manifest_files]
        assert OPENCODE_COMMAND_PATH in paths, (
            f"{OPENCODE_COMMAND_PATH!r} is missing from harness/manifest.json 'files' array. "
            "Users running `harness install --adapters opencode` will not receive this file."
        )

    def test_entry_policy_harness_owned(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == OPENCODE_COMMAND_PATH), None)
        assert entry is not None, f"{OPENCODE_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("policy") == "harness-owned", (
            f"Expected policy='harness-owned', got {entry.get('policy')!r}"
        )

    def test_entry_adapter_opencode(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == OPENCODE_COMMAND_PATH), None)
        assert entry is not None, f"{OPENCODE_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("adapter") == "opencode", (
            f"Expected adapter='opencode', got {entry.get('adapter')!r}"
        )

    def test_entry_owner_adapter_opencode(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == OPENCODE_COMMAND_PATH), None)
        assert entry is not None, f"{OPENCODE_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("owner") == "adapter:opencode", (
            f"Expected owner='adapter:opencode', got {entry.get('owner')!r}"
        )

    def test_entry_source_matches_path(self, manifest_files):
        entry = next((f for f in manifest_files if f["path"] == OPENCODE_COMMAND_PATH), None)
        assert entry is not None, f"{OPENCODE_COMMAND_PATH!r} not found in manifest files"
        assert entry.get("source") == OPENCODE_COMMAND_PATH, (
            f"Expected source={OPENCODE_COMMAND_PATH!r}, got {entry.get('source')!r}"
        )

    def test_on_disk_file_present(self):
        on_disk = REPO_ROOT / OPENCODE_COMMAND_PATH
        assert on_disk.exists(), (
            f"On-disk file {on_disk} does not exist — manifest entry would be broken."
        )
