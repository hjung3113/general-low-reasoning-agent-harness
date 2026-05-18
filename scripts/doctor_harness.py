#!/usr/bin/env python3
"""Diagnose harness planning and adapter drift."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import harness


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose harness planning and adapter drift against the installed target. "
                    "Equivalent to 'harness doctor' invoked from the installed location.",
        epilog="Example:\n  python3 scripts/doctor_harness.py\n"
               "  python3 scripts/doctor_harness.py --format json   # machine-readable drift report\n\n"
               "For policy/structure validation use 'check_harness.py'; for state inspection use 'harness state show'.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    harness.doctor(root=(args.target or harness.repo_root()).resolve(), output_format=args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
