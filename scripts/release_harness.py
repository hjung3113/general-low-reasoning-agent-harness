#!/usr/bin/env python3
"""Verify release version, tag, and worktree gates."""

from __future__ import annotations

import argparse
import sys

import harness


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=None)
    parser.add_argument("--require-origin-main", action="store_true")
    args = parser.parse_args(argv)
    version = harness.release_check(
        root=harness.repo_root(),
        expected_version=args.expected_version,
        require_origin_main=args.require_origin_main,
    )
    print(f"release-check PASS v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
