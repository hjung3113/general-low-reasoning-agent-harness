#!/usr/bin/env python3
"""Validate harness structure and policy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import harness


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run harness drift/policy checks against the installed target. "
                    "Equivalent to 'harness check' invoked from the installed location.",
        epilog="Example:\n  python3 scripts/check_harness.py\n"
               "  python3 scripts/check_harness.py --worktree   # also enforce allowed_paths\n\n"
               "For detailed drift diagnosis use 'doctor_harness.py'; for state inspection use 'harness state show'.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--adapter", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)
    harness.check(
        root=harness.repo_root(),
        target=args.target,
        base=args.base,
        worktree=args.worktree,
        adapter=args.adapter,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
