"""S06-audit-chain: chain-stamped audit writer tests (design §2.1, §2.2).

Tests verify that audit_append now stamps chain fields on every new entry.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.audit import audit_append


class TestChainStampedWriter:
    def _append(self, tmp_path: Path, verb: str = "phase.set", **extra) -> dict:
        audit_path = tmp_path / "audit.log"
        entry = {"verb": verb, "at": "2026-05-17T00:00:00Z", **extra}
        audit_append(entry, audit_path=audit_path)
        lines = [ln for ln in audit_path.read_text().splitlines() if ln.strip()]
        return json.loads(lines[-1])

    def test_new_entry_has_schema_version_2(self, tmp_path):
        entry = self._append(tmp_path)
        assert entry.get("schema_version") == 2

    def test_new_entry_has_seq(self, tmp_path):
        entry = self._append(tmp_path)
        assert entry.get("seq") == 1

    def test_new_entry_has_seq_global(self, tmp_path):
        entry = self._append(tmp_path)
        assert entry.get("seq_global") == 1

    def test_new_entry_has_entry_hash(self, tmp_path):
        entry = self._append(tmp_path)
        assert "entry_hash" in entry
        assert len(entry["entry_hash"]) == 64

    def test_new_entry_has_previous_entry_hash(self, tmp_path):
        entry = self._append(tmp_path)
        assert "previous_entry_hash" in entry
        # First entry: previous = genesis (all zeros)
        assert entry["previous_entry_hash"] == "0" * 64

    def test_second_entry_chains_to_first(self, tmp_path):
        audit_path = tmp_path / "audit.log"
        e1 = {"verb": "phase.set", "at": "2026-05-17T00:00:00Z"}
        e2 = {"verb": "phase.approve", "at": "2026-05-17T00:01:00Z"}
        audit_append(e1, audit_path=audit_path)
        audit_append(e2, audit_path=audit_path)
        lines = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
        assert lines[1]["previous_entry_hash"] == lines[0]["entry_hash"]
        assert lines[1]["seq"] == 2
        assert lines[1]["seq_global"] == 2

    def test_entry_hash_verifiable(self, tmp_path):
        """entry_hash must equal compute_entry_hash(entry_minus_entry_hash)."""
        from lib.audit_chain import compute_entry_hash
        entry = self._append(tmp_path)
        entry_for_hash = {k: v for k, v in entry.items() if k != "entry_hash"}
        assert entry["entry_hash"] == compute_entry_hash(entry_for_hash)

    def test_minimal_fallback_preserves_chain_fields(self, tmp_path):
        """§12.5 #1: last-resort minimal fallback must preserve chain fields."""
        from lib.audit_chain import GENESIS_HASH
        audit_path = tmp_path / "audit.log"
        # Write a very large entry that triggers minimal-fallback
        big_entry = {
            "verb": "phase.set",
            "at": "2026-05-17T00:00:00Z",
            "args": {"data": "x" * 2000},  # force minimal fallback
        }
        audit_append(big_entry, audit_path=audit_path)
        lines = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
        entry = lines[-1]
        # Even in minimal fallback, chain fields must be present
        assert "entry_hash" in entry
        assert "previous_entry_hash" in entry
        assert "seq" in entry
        assert "seq_global" in entry
