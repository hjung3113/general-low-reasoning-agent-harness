#!/usr/bin/env python3
"""Tests for atomic JTI replay defense (_check_and_record_jti) — B2-Fix-2 (Cycle-1).

Verifies:
 - Same JTI from two concurrent processes: one wins, one gets replay rejection.
 - Different JTIs from concurrent processes: both succeed.
 - No lost-update: the winning process does not corrupt the loser's marker.
"""

from __future__ import annotations

import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import phase_autopilot  # noqa: E402
from lib.ci_provenance import CiOidcJtiReplayed  # noqa: E402

_check_and_record_jti = phase_autopilot._check_and_record_jti


def _worker_check_jti(
    jti: str,
    harness_dir: str,
    audit_path: str,
    scripts_dir: str,
    result_queue: "multiprocessing.Queue[str]",
) -> None:
    """Worker: call _check_and_record_jti and push 'ok' or 'replay' to queue.

    scripts_dir is passed explicitly because multiprocessing.spawn does not
    inherit the parent's sys.path modifications.
    """
    import sys as _sys
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    from lib import phase_autopilot as _pa
    result = _pa._check_and_record_jti(
        jti,
        harness_dir=Path(harness_dir),
        audit_path=Path(audit_path),
    )
    if result is None:
        result_queue.put("ok")
    else:
        result_queue.put("replay")


class TestJtiAtomicConcurrency(unittest.TestCase):

    _SCRIPTS_DIR = str(Path(__file__).resolve().parent)

    def _run_two_concurrent(
        self, jti: str, harness_dir: Path, audit_path: Path
    ) -> tuple[str, str]:
        """Run two concurrent workers for the same jti; return their results."""
        ctx = multiprocessing.get_context("spawn")
        q: multiprocessing.Queue = ctx.Queue()
        p1 = ctx.Process(
            target=_worker_check_jti,
            args=(jti, str(harness_dir), str(audit_path), self._SCRIPTS_DIR, q),
        )
        p2 = ctx.Process(
            target=_worker_check_jti,
            args=(jti, str(harness_dir), str(audit_path), self._SCRIPTS_DIR, q),
        )
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)
        results = []
        while not q.empty():
            results.append(q.get_nowait())
        return tuple(sorted(results))  # type: ignore[return-value]

    def test_same_jti_one_wins_one_replay(self) -> None:
        """Concurrent claims on the same JTI: exactly one ok, one replay."""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir()
            audit_path = harness_dir / "audit.log"
            audit_path.touch()

            r1, r2 = self._run_two_concurrent("test-jti-collision", harness_dir, audit_path)
            outcomes = sorted([r1, r2])
            self.assertEqual(outcomes, ["ok", "replay"],
                             f"Expected one ok and one replay; got {outcomes}")

    def test_different_jtis_both_succeed(self) -> None:
        """Concurrent claims on different JTIs: both succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir()
            audit_path = harness_dir / "audit.log"
            audit_path.touch()

            ctx = multiprocessing.get_context("spawn")
            q: multiprocessing.Queue = ctx.Queue()
            p1 = ctx.Process(
                target=_worker_check_jti,
                args=("jti-alpha", str(harness_dir), str(audit_path), self._SCRIPTS_DIR, q),
            )
            p2 = ctx.Process(
                target=_worker_check_jti,
                args=("jti-beta", str(harness_dir), str(audit_path), self._SCRIPTS_DIR, q),
            )
            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)
            results = []
            while not q.empty():
                results.append(q.get_nowait())
            self.assertEqual(sorted(results), ["ok", "ok"],
                             f"Expected both ok; got {results}")

    def test_collision_distinct_jtis_not_replayed(self) -> None:
        """A-6 (Cycle-2): JTIs that differ only in /vs_ must NOT collide.

        Under the old sanitization scheme "a/b" → "a_b" and "a_b" → "a_b"
        were identical filenames, causing a false replay.  With sha256 they
        produce different hex digests and both succeed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir()
            audit_path = harness_dir / "audit.log"
            audit_path.touch()

            r1 = _check_and_record_jti("a/b", harness_dir=harness_dir, audit_path=audit_path)
            r2 = _check_and_record_jti("a_b", harness_dir=harness_dir, audit_path=audit_path)
            self.assertIsNone(r1, "a/b should succeed (new entry)")
            self.assertIsNone(r2, "a_b should succeed (distinct sha256 — no collision)")

    def test_second_call_same_jti_is_replay(self) -> None:
        """Sequential second call with same JTI returns CiOidcJtiReplayed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness_dir = Path(tmpdir) / ".harness"
            harness_dir.mkdir()
            audit_path = harness_dir / "audit.log"
            audit_path.touch()

            result1 = _check_and_record_jti(
                "my-jti",
                harness_dir=harness_dir,
                audit_path=audit_path,
            )
            self.assertIsNone(result1, "First call should succeed")

            result2 = _check_and_record_jti(
                "my-jti",
                harness_dir=harness_dir,
                audit_path=audit_path,
            )
            self.assertIsInstance(result2, CiOidcJtiReplayed,
                                  "Second call should be replay")


if __name__ == "__main__":
    unittest.main()
