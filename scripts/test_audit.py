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

    def test_audit_rotation_holds_flock_across_rename(self) -> None:
        """C4 (white-box): _rotate MUST be called while the flock is held.

        The rename of the file-under-lock is the contended step. POSIX
        flock binds to the inode, which survives rename, so subsequent
        openers block correctly. If the flock is released before _rotate,
        a racing writer can rotate first, leading to FileNotFoundError /
        clobbered audit.log.1. This test asserts call ordering directly so
        the property holds regardless of test scheduling luck.
        """
        from unittest import mock
        import fcntl as _fcntl

        events: list[str] = []
        real_flock = _fcntl.flock
        real_rotate = audit_mod._rotate

        def trace_flock(fd, op):
            if op == _fcntl.LOCK_UN:
                events.append("unlock")
            elif op & _fcntl.LOCK_EX:
                events.append("lock")
            return real_flock(fd, op)

        def trace_rotate(p):
            events.append("rotate")
            return real_rotate(p)

        original = audit_mod.ROTATION_BYTES
        audit_mod.ROTATION_BYTES = 256
        try:
            # Pre-fill above threshold so the next append triggers rotation.
            for _ in range(6):
                audit_append(
                    {"verb": "phase.set", "args": {"p": "x" * 50},
                     "before_sha256": "a" * 64, "after_sha256": "b" * 64,
                     "at": "2026-05-16T00:00:00.000000000Z", "by": "t@e"},
                    audit_path=self.audit,
                )
            events.clear()
            with mock.patch.object(_fcntl, "flock", side_effect=trace_flock), \
                 mock.patch.object(audit_mod, "_rotate", side_effect=trace_rotate):
                audit_append(
                    {"verb": "phase.set", "args": {"p": "z" * 50},
                     "before_sha256": "a" * 64, "after_sha256": "b" * 64,
                     "at": "2026-05-16T00:00:00.000000000Z", "by": "t@e"},
                    audit_path=self.audit,
                )
        finally:
            audit_mod.ROTATION_BYTES = original
        # Required ordering: lock, rotate, ..., unlock — rotate MUST come
        # before the FIRST unlock, not after.
        lock_idx = events.index("lock")
        rotate_idx = events.index("rotate")
        first_unlock_after_lock = next(
            (i for i, ev in enumerate(events) if i > lock_idx and ev == "unlock"),
            None,
        )
        self.assertIsNotNone(first_unlock_after_lock, f"events={events}")
        self.assertLess(
            rotate_idx, first_unlock_after_lock,
            f"_rotate must run before flock is released; events={events}",
        )

    def test_audit_rotation_concurrent_writers_no_data_loss(self) -> None:
        """C4: writers crossing the rotation threshold concurrently must
        not lose entries or raise FileNotFoundError mid-rotation, and the
        rotated audit.log.1 must not be clobbered by a racing rename."""
        original = audit_mod.ROTATION_BYTES
        audit_mod.ROTATION_BYTES = 512
        try:
            self.audit.parent.mkdir(parents=True, exist_ok=True)
            # Pre-fill above the rotation threshold so the FIRST writer in
            # the next batch decides to rotate immediately. With 60 workers
            # all opening before any has finished, multiple workers see the
            # rotated-but-not-yet-replaced state and race on rotation.
            for i in range(20):
                audit_append(
                    {
                        "verb": "phase.set",
                        "args": {"i": i, "padding": "x" * 50},
                        "before_sha256": "a" * 64,
                        "after_sha256": "b" * 64,
                        "at": "2026-05-16T00:00:00.000000000Z",
                        "by": "t@e",
                    },
                    audit_path=self.audit,
                )
            with multiprocessing.Pool(20) as pool:
                results = pool.starmap_async(
                    _worker,
                    [(str(self.audit), i) for i in range(60)],
                )
                # Surface FileNotFoundError or any other exception from
                # rotation racing.
                try:
                    results.get(timeout=30)
                except FileNotFoundError as exc:  # pragma: no cover
                    self.fail(f"rotation raced into missing path: {exc}")
                except Exception as exc:
                    self.fail(f"rotation worker raised: {exc!r}")
            # Every line must be parseable JSON. No torn writes.
            files = [self.audit] + sorted(
                (self.tmp / ".harness").glob("audit.log.*")
            )
            total = 0
            for f in files:
                if not f.exists():
                    continue
                for ln in f.read_text().splitlines():
                    if not ln.strip():
                        continue
                    parsed = json.loads(ln)
                    self.assertIn("index", parsed)
                    total += 1
            # 20 pre-fill + 60 concurrent = 80 entries total (subject to
            # ROTATION_KEEP=5 dropping the oldest). With ~50-byte entries
            # at 512-byte rotation the oldest may be dropped; assert we
            # retain at least 60 (the most recent batch).
            self.assertGreaterEqual(total, 60, f"only {total} entries retained")
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
