#!/usr/bin/env python3
"""CLI wrapper around :mod:`lib.state_migrate`.

Owning plan: .planning/phases/02b-hardening/plans/02b-02-T0-1-PLAN.md Block C.
Contract pin: CONTRACT-PIN §1 (file path), §6.1 (.bak grammar), §6.3 (sidecar).

Usage:
    python3 scripts/migrate_state.py --forward [--target PATH] [--dry-run]
    python3 scripts/migrate_state.py --reverse [--target PATH] [--dry-run]
    python3 scripts/migrate_state.py --resume  [--target PATH]

Default target: ``.scratch/phase-state.json`` (relative to CWD).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lib import state_migrate  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate_state",
        description="Migrate .scratch/phase-state.json between v0 and v2 (ADR-001).",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--forward", action="store_true", help="Apply v0 -> v2 transformation.")
    mode.add_argument("--reverse", action="store_true", help="Apply v2 -> v0 transformation.")
    mode.add_argument("--resume", action="store_true", help="Resume from sidecar after crash.")
    p.add_argument(
        "--target",
        default=".scratch/phase-state.json",
        help="Path to phase-state file (default: .scratch/phase-state.json).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print canonical transformed output to stdout; do not touch disk.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    target = Path(args.target)

    if args.resume:
        if args.dry_run:
            print("--resume does not support --dry-run", file=sys.stderr)
            return 1
        state_migrate.resume(target)
        return 0

    direction = "forward" if args.forward else "reverse"

    if args.dry_run:
        # Read + transform + print canonical bytes; no filesystem mutation.
        import json
        state = json.loads(target.read_text(encoding="utf-8"))
        if direction == "forward":
            post = state_migrate.forward(state)
        else:
            post = state_migrate.reverse(state)
        sys.stdout.write(state_migrate.serialize(post).decode("utf-8"))
        return 0

    # S01-A.2 review-fix (P1, 2026-05-17): wire audit_path so the
    # production CLI emits the one-time `verb=migrate.state_v2` entry
    # required by design §1.2. The canonical audit log lives at
    # `<repo>/.harness/audit.log`; we derive the repo root from the
    # target's grandparent (target is `.scratch/phase-state.json`).
    # Dry-run already returned above, so no risk of leaking audit
    # entries for a hypothetical mutation that never happened.
    audit_path = _resolve_default_audit_path(target)
    state_migrate.migrate_file(target, direction=direction, audit_path=audit_path)
    return 0


def _resolve_default_audit_path(target: Path) -> Path:
    """Return the canonical audit log path for the repo containing `target`.

    Walks up from the target until a directory containing `.harness/`
    or `.scratch/` is found (mirrors `state_migrate._default_backups_dir`).
    Falls back to `<target.parent.parent>/.harness/audit.log` so a
    fresh layout (no ancestor markers yet) still gets a sensible path.
    """
    for parent in [target.parent, *target.parent.parents]:
        if (parent / ".harness").exists() or (parent / ".scratch").exists():
            return parent / ".harness" / "audit.log"
    return target.parent.parent / ".harness" / "audit.log"


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
