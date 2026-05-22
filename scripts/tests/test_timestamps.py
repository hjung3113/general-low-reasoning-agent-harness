#!/usr/bin/env python3
"""Tests for scripts/lib/timestamps.py (T0-3 amendment #5)."""

from __future__ import annotations

import datetime
import re
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


NANOS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{9}Z$")


class TimestampsTests(unittest.TestCase):
    def test_now_iso_nanos_format(self) -> None:
        from lib.timestamps import now_iso_nanos
        s = now_iso_nanos()
        self.assertRegex(s, NANOS_RE)

    def test_parse_iso_nanos_roundtrip(self) -> None:
        from lib.timestamps import parse_iso_nanos
        dt = parse_iso_nanos("2026-05-16T19:30:45.123456789Z")
        self.assertEqual(dt.tzinfo, datetime.timezone.utc)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 5)
        self.assertEqual(dt.microsecond, 123456)  # nanos truncated to micros for datetime

    def test_parse_iso_nanos_rejects_garbage(self) -> None:
        from lib.timestamps import parse_iso_nanos
        with self.assertRaises(ValueError):
            parse_iso_nanos("not a timestamp")


if __name__ == "__main__":
    unittest.main()
