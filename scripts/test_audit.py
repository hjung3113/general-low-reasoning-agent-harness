#!/usr/bin/env python3
"""Tests for scripts/lib/audit.py — audit log atomic append + rotation (T0-3 G1-A)."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.audit import (  # noqa: E402
    audit_append,
    read_last_entry,
    compute_state_hash,
    AUDIT_MAX_LINE_BYTES,
)
from lib import audit as audit_mod  # noqa: E402


def _worker(audit_path: str, i: int) -> None:
    # multiprocessing requires top-level callable. Re-import inside the child.
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent))
    from lib.audit import audit_append as _aa
    _aa(
        {
            "verb": "phase.set",
            "args": {"phase": "discuss", "i": i},
            "before_sha256": "a" * 64,
            "after_sha256": "b" * 64,
            "at": "2026-05-16T00:00:00.000000000Z",
            "by": "t@e",
        },
        audit_path=_P(audit_path),
    )


class AuditLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.audit = self.tmp / ".harness" / "audit.log"

    def test_first_write_index_1(self) -> None:
        idx = audit_append(
            {
                "verb": "phase.set",
                "args": {},
                "before_sha256": "",
                "after_sha256": "x" * 64,
                "at": "2026-05-16T00:00:00.000000000Z",
                "by": "t@e",
            },
            audit_path=self.audit,
        )
        self.assertEqual(idx, 1)
        last = read_last_entry(self.audit)
        self.assertIsNotNone(last)
        self.assertEqual(last["index"], 1)

    def test_second_write_index_2(self) -> None:
        for _ in range(2):
            audit_append(
                {
                    "verb": "phase.set",
                    "args": {},
                    "before_sha256": "",
                    "after_sha256": "x" * 64,
                    "at": "2026-05-16T00:00:00.000000000Z",
                    "by": "t@e",
                },
                audit_path=self.audit,
            )
        last = read_last_entry(self.audit)
        self.assertEqual(last["index"], 2)

    def test_concurrent_appends_no_torn_lines(self) -> None:
        self.audit.parent.mkdir(parents=True, exist_ok=True)
        with multiprocessing.Pool(10) as pool:
            pool.starmap(_worker, [(str(self.audit), i) for i in range(100)])
        lines = self.audit.read_text().splitlines()
        self.assertEqual(len(lines), 100)
        for ln in lines:
            entry = json.loads(ln)
            self.assertIn("index", entry)
        indices = sorted(json.loads(l)["index"] for l in lines)
        self.assertEqual(indices, list(range(1, 101)))

    def test_oversize_args_triggers_overflow_sidecar(self) -> None:
        big = {
            "verb": "phase.set",
            "args": {"x": "y" * 1000},
            "before_sha256": "a" * 64,
            "after_sha256": "b" * 64,
            "at": "2026-05-16T00:00:00.000000000Z",
            "by": "t@e",
        }
        idx = audit_append(big, audit_path=self.audit)
        line = self.audit.read_text().splitlines()[-1]
        self.assertLessEqual(len(line.encode("utf-8")) + 1, AUDIT_MAX_LINE_BYTES)
        parsed = json.loads(line)
        self.assertEqual(parsed["args"], {"truncated": True})
        overflow = self.tmp / ".harness" / "audit.overflow" / f"{idx}.json"
        self.assertTrue(overflow.exists())

    def test_rotation_at_size_threshold(self) -> None:
        original = audit_mod.ROTATION_BYTES
        audit_mod.ROTATION_BYTES = 2048
        try:
            for i in range(80):
                audit_append(
                    {
                        "verb": "phase.set",
                        "args": {"i": i},
                        "before_sha256": "a" * 64,
                        "after_sha256": "b" * 64,
                        "at": "2026-05-16T00:00:00.000000000Z",
                        "by": "t@e",
                    },
                    audit_path=self.audit,
                )
            self.assertTrue((self.tmp / ".harness" / "audit.log.1").exists())
        finally:
            audit_mod.ROTATION_BYTES = original

    def test_rotation_keeps_at_most_5(self) -> None:
        original = audit_mod.ROTATION_BYTES
        audit_mod.ROTATION_BYTES = 512
        try:
            for i in range(400):
                audit_append(
                    {
                        "verb": "phase.set",
                        "args": {"i": i},
                        "before_sha256": "a" * 64,
                        "after_sha256": "b" * 64,
                        "at": "2026-05-16T00:00:00.000000000Z",
                        "by": "t@e",
                    },
                    audit_path=self.audit,
                )
            existing = sorted((self.tmp / ".harness").glob("audit.log.*"))
            self.assertLessEqual(len(existing), 5)
        finally:
            audit_mod.ROTATION_BYTES = original

    def test_compute_state_hash_empty(self) -> None:
        nonexistent = self.tmp / "missing.json"
        self.assertEqual(compute_state_hash(nonexistent), "")

    def test_compute_state_hash_value(self) -> None:
        f = self.tmp / "f.json"
        f.write_text("{}")
        import hashlib
        self.assertEqual(compute_state_hash(f), hashlib.sha256(b"{}").hexdigest())


if __name__ == "__main__":
    unittest.main()
