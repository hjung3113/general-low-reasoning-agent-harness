"""CLI subcommand handlers for `scripts/harness.py state ...`."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TextIO

from lib import state_repair
from lib.exitcodes import EXIT_OPERATIONAL, EXIT_UNPARSEABLE_JSON
from lib.planning_status import ProjectionError, load_projection

# ---------------------------------------------------------------------------
# Root resolution
# ---------------------------------------------------------------------------
# Project state MUST be resolved via cwd walk-up (or an explicit override).
# Package-resource paths (skeleton files, manifest, hook bodies) may continue
# to use __file__-relative resolution — see lib/version.py and lib/hooks.py.
# ---------------------------------------------------------------------------


def resolve_root(cli_root_arg: "Path | None" = None) -> Path:
    """Resolve the harness project root.

    Priority:
    1. ``cli_root_arg`` (from ``--root <path>``)
    2. ``HARNESS_STATE_ROOT`` environment variable
    3. Walk up from ``Path.cwd()`` looking for ``.scratch/phase-state.json``
       or ``.harness`` directory (either signals a harness project root).

    Raises ``SystemExit`` with a clear error message when no project root is
    found and no explicit override was supplied.
    """
    if cli_root_arg is not None:
        return Path(cli_root_arg).resolve()

    env_root = os.environ.get("HARNESS_STATE_ROOT")
    if env_root:
        return Path(env_root).resolve()

    p = Path.cwd().resolve()
    while True:
        if (p / ".scratch" / "phase-state.json").exists() or (p / ".harness").exists():
            return p
        parent = p.parent
        if parent == p:
            # Reached filesystem root — no project found.
            raise SystemExit(
                "error: no harness project found in cwd ancestry "
                "(set --root <path> or HARNESS_STATE_ROOT env var)"
            )
        p = parent


def run_show(*, root: Path, stream: TextIO, fmt: str = "text") -> int:
    try:
        projection = load_projection(root)
    except ProjectionError as exc:
        stream.write(f"error: {exc}\n")
        return 1
    payload = {
        "phase": projection.phase,
        "phase_id": projection.phase_id,
        "active_phase_folder": projection.active_phase_folder,
        "state_path": projection.state_path,
        "roadmap_path": projection.roadmap_path,
        "checkpoint_path": projection.checkpoint_path,
        "plan_path": projection.plan_path,
        "verification_path": projection.verification_path,
        "summary_path": projection.summary_path,
        "allowed_paths": projection.allowed_paths,
        "acceptance_criteria": projection.acceptance_criteria,
        "verification": projection.verification,
        "required_reads": projection.required_reads,
        "warnings": [
            {"code": w.code, "severity": w.severity, "message": w.message, "paths": w.paths}
            for w in projection.warnings
        ],
    }
    if fmt == "json":
        stream.write(json.dumps(payload, indent=2) + "\n")
        return 0
    stream.write(f"phase:            {payload['phase']}\n")
    stream.write(f"phase_id:         {payload['phase_id']}\n")
    stream.write(f"checkpoint_path:  {payload['checkpoint_path']}\n")
    stream.write(f"plan_path:        {payload['plan_path']}\n")
    if payload["allowed_paths"]:
        stream.write("allowed_paths:\n")
        for path in payload["allowed_paths"]:
            stream.write(f"  - {path}\n")
    if payload["warnings"]:
        stream.write("warnings:\n")
        for warning in payload["warnings"]:
            stream.write(f"  - [{warning['severity']}] {warning['code']}: {warning['message']}\n")
    return 0


def run_repair(*, root: Path, stream: TextIO) -> int:
    """Translate state_repair exceptions to CLI exit codes.

    Exit code contract (IMPL-PLAN REV-2 §3.4 / v0.9.5 NEW-3 fix):
    - 0 — recovery completed cleanly OR no work to do
    - 1 — partial recovery with quarantine (files moved to .harness/conflicts/)
    - 2 — catastrophic failure (repair() raised an unexpected exception)
    - 5 (EXIT_UNPARSEABLE_JSON) — RefusedError (duplicate slug / malformed input)

    Legacy mapping preserved:
    - state_repair.RepairRefusedError → exit 5 (EXIT_UNPARSEABLE_JSON) per
      CONTRACT-PIN §4. Diagnostic written to both `stream` and stderr.
    - SystemExit(1) propagating from a backup-collision in lib.backups →
      exit 1 (EXIT_OPERATIONAL). The pre-existing files are untouched
      because backups precede atomic_write_text.
    """
    try:
        report = state_repair.repair(root)
    except state_repair.RepairRefusedError as exc:
        stream.write(str(exc) + "\n")
        print(str(exc), file=sys.stderr)
        return EXIT_UNPARSEABLE_JSON
    except SystemExit as exc:
        if getattr(exc, "code", None) == EXIT_OPERATIONAL:
            msg = str(exc)
            if msg:
                stream.write(msg + "\n")
                print(msg, file=sys.stderr)
            return EXIT_OPERATIONAL
        raise
    except Exception as exc:  # noqa: BLE001
        # Catastrophic: repair() raised an unexpected exception.
        msg = f"state repair: catastrophic error — {exc}"
        stream.write(msg + "\n")
        print(msg, file=sys.stderr)
        return 2
    if report.files_updated:
        stream.write("updated:\n")
        for path in report.files_updated:
            stream.write(f"  - {path}\n")
    if report.markers_added:
        stream.write("markers_added:\n")
        for path in report.markers_added:
            stream.write(f"  - {path}\n")
    if report.payloads_canonicalized:
        stream.write("canonicalized:\n")
        for path in report.payloads_canonicalized:
            stream.write(f"  - {path}\n")
    if report.warnings:
        stream.write("warnings:\n")
        for w in report.warnings:
            stream.write(f"  - {w}\n")
    if not (report.files_updated or report.markers_added or report.payloads_canonicalized
            or report.warnings):
        stream.write("nothing to repair (already canonical)\n")
    # rc=1 when quarantine occurred (partial recovery — operator must check .harness/conflicts/).
    if report.quarantined_count > 0:
        return 1
    return 0
