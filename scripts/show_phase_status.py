#!/usr/bin/env python3
"""Print the planning phase status projection as JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.planning_status import ProjectionError, load_projection, projection_to_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root to inspect.")
    args = parser.parse_args(argv)

    try:
        projection = load_projection(args.root)
    except ProjectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(projection_to_json(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
