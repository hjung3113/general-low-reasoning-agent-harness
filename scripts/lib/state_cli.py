"""CLI subcommand handlers for `scripts/harness.py state ...`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TextIO

from lib import state_repair
from lib.planning_status import ProjectionError, load_projection


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
    report = state_repair.repair(root)
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
    if not (report.files_updated or report.markers_added or report.payloads_canonicalized):
        stream.write("nothing to repair (already canonical)\n")
    return 0
