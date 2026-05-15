#!/usr/bin/env python3
"""Diagnose harness planning and adapter drift."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import harness


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    harness.doctor(root=(args.target or harness.repo_root()).resolve(), output_format=args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
