"""Read-only planning status projection for low-reasoning preflight."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "phase-status.v1"
LEGACY_READ_ORDER = [
    ".planning/STATE.md",
    ".planning/ROADMAP.md",
    ".planning/codebase/**",
    "<active checkpoint file>",
    "<active phase docs>",
    ".scratch/phase-state.json",
]


class ProjectionError(ValueError):
    """Raised when the projection cannot be produced at all."""


@dataclass(frozen=True)
class PlanningWarning:
    code: str
    severity: str
    message: str
    paths: list[str]
    required_read: bool


@dataclass(frozen=True)
class PlanningProjection:
    contract_version: str
    phase: str
    phase_id: str
    phase_title: str
    approved: bool
    plan_id: str | None
    automation_mode: str
    projected_execute_gate_valid: bool
    projected_execute_gate_reason: str
    active_phase_folder: str
    active_checkpoint_id: str
    active_checkpoint_title: str
    active_checkpoint_status: str
    state_path: str
    roadmap_path: str
    checkpoint_path: str
    plan_path: str
    verification_path: str
    summary_path: str
    allowed_paths: list[str]
    blocked_paths: list[str]
    acceptance_criteria: list[str]
    verification: list[str]
    warnings: list[PlanningWarning]
    required_reads: list[str]
    suggested_next_read: str


@dataclass(frozen=True)
class StateMetadata:
    phase_id: str
    phase_title: str
    checkpoint_id: str
    checkpoint_path: str
    total_phases: int | None
    completed_phases: int | None
    percent: int | None


@dataclass(frozen=True)
class CheckpointMetadata:
    checkpoint_id: str
    title: str
    status: str


@dataclass(frozen=True)
class RoadmapMetadata:
    total_phases: int
    completed_phases: int
    phase_ids: list[str]


def load_projection(root: Path) -> PlanningProjection:
    root = root.resolve()
    phase_state_path = ".scratch/phase-state.json"
    phase_state = _load_phase_state(root / phase_state_path)

    state_path = _string_value(phase_state.get("state_path")) or ".planning/STATE.md"
    roadmap_path = ".planning/ROADMAP.md"
    checkpoint_path = _string_value(phase_state.get("checkpoint_path")) or ""
    plan_path = _string_value(phase_state.get("plan_path")) or ""

    state_text = _read_text_if_exists(root, state_path)
    roadmap_text = _read_text_if_exists(root, roadmap_path)
    state_meta = _parse_state_metadata(state_text)
    roadmap_meta = _parse_roadmap_metadata(roadmap_text)
    if not checkpoint_path:
        checkpoint_path = state_meta.checkpoint_path

    active_phase_folder = _parent_path(checkpoint_path) or _parent_path(plan_path)
    phase_id = _phase_id_from_folder(active_phase_folder) or state_meta.phase_id
    phase_title = _roadmap_phase_title(roadmap_text, phase_id) or state_meta.phase_title
    current_checkpoint = _string_value(phase_state.get("current_checkpoint")) or state_meta.checkpoint_id
    checkpoint_text = _read_text_if_exists(root, checkpoint_path)
    checkpoint_meta = _parse_checkpoint_metadata(checkpoint_text, current_checkpoint)

    if not checkpoint_meta.checkpoint_id:
        active_checkpoint_id = current_checkpoint
    else:
        active_checkpoint_id = checkpoint_meta.checkpoint_id
    active_checkpoint_title = checkpoint_meta.title
    active_checkpoint_status = checkpoint_meta.status

    verification_path = _phase_doc_path(active_phase_folder, phase_id, "VERIFICATION")
    summary_path = _summary_doc_path(root, active_phase_folder, phase_id, plan_path, current_checkpoint)
    phase_value = _string_value(phase_state.get("phase")) or "unknown"
    if phase_value == "discuss" and verification_path and not (root / verification_path).is_file():
        verification_path = ""
    allowed_paths = _list_of_strings(phase_state.get("allowed_paths"))
    blocked_paths = _list_of_strings(phase_state.get("blocked_paths"))
    acceptance_criteria = _list_of_strings(phase_state.get("acceptance_criteria"))
    verification = _list_of_strings(phase_state.get("verification"))
    warnings = _warnings(
        root=root,
        phase_state=phase_state,
        state_path=state_path,
        roadmap_path=roadmap_path,
        checkpoint_path=checkpoint_path,
        plan_path=plan_path,
        verification_path=verification_path,
        summary_path=summary_path,
        state_meta=state_meta,
        roadmap_meta=roadmap_meta,
        active_checkpoint_id=active_checkpoint_id,
        active_checkpoint_status=active_checkpoint_status,
        plan_id=_string_value(phase_state.get("plan_id")),
        allowed_paths=allowed_paths,
        acceptance_criteria=acceptance_criteria,
        verification=verification,
    )
    execute_gate_valid, execute_gate_reason = _execute_gate(
        phase=phase_value,
        approved=bool(phase_state.get("approved")),
        plan_id=_string_value(phase_state.get("plan_id")),
        phase_state=phase_state,
        warnings=warnings,
    )
    required_reads = _required_reads(
        root,
        state_path,
        roadmap_path,
        checkpoint_path,
        plan_path,
        verification_path,
        summary_path,
        warnings,
    )

    return PlanningProjection(
        contract_version=CONTRACT_VERSION,
        phase=phase_value,
        phase_id=phase_id,
        phase_title=phase_title,
        approved=bool(phase_state.get("approved")),
        plan_id=_string_value(phase_state.get("plan_id")),
        automation_mode=_string_value(phase_state.get("automation_mode")) or "manual",
        projected_execute_gate_valid=execute_gate_valid,
        projected_execute_gate_reason=execute_gate_reason,
        active_phase_folder=active_phase_folder,
        active_checkpoint_id=active_checkpoint_id,
        active_checkpoint_title=active_checkpoint_title,
        active_checkpoint_status=active_checkpoint_status,
        state_path=state_path,
        roadmap_path=roadmap_path,
        checkpoint_path=checkpoint_path,
        plan_path=plan_path,
        verification_path=verification_path,
        summary_path=summary_path,
        allowed_paths=allowed_paths,
        blocked_paths=blocked_paths,
        acceptance_criteria=acceptance_criteria,
        verification=verification,
        warnings=warnings,
        required_reads=required_reads,
        suggested_next_read=required_reads[0] if required_reads else state_path,
    )


def projection_to_dict(projection: PlanningProjection) -> dict[str, object]:
    return {
        "contract_version": projection.contract_version,
        "phase": projection.phase,
        "phase_id": projection.phase_id,
        "phase_title": projection.phase_title,
        "approved": projection.approved,
        "plan_id": projection.plan_id,
        "automation_mode": projection.automation_mode,
        "projected_execute_gate_valid": projection.projected_execute_gate_valid,
        "projected_execute_gate_reason": projection.projected_execute_gate_reason,
        "active_phase_folder": projection.active_phase_folder,
        "active_checkpoint_id": projection.active_checkpoint_id,
        "active_checkpoint_title": projection.active_checkpoint_title,
        "active_checkpoint_status": projection.active_checkpoint_status,
        "state_path": projection.state_path,
        "roadmap_path": projection.roadmap_path,
        "checkpoint_path": projection.checkpoint_path,
        "plan_path": projection.plan_path,
        "verification_path": projection.verification_path,
        "summary_path": projection.summary_path,
        "allowed_paths": projection.allowed_paths,
        "blocked_paths": projection.blocked_paths,
        "acceptance_criteria": projection.acceptance_criteria,
        "verification": projection.verification,
        "warnings": [warning.__dict__ for warning in projection.warnings],
        "required_reads": projection.required_reads,
        "suggested_next_read": projection.suggested_next_read,
    }


def projection_to_json(projection: PlanningProjection) -> str:
    return json.dumps(projection_to_dict(projection), sort_keys=True, separators=(",", ":"))


def _load_phase_state(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectionError(f"{_display_path(path)} could not be read: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectionError(f"{_display_path(path)} is malformed JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ProjectionError(f"{_display_path(path)} must contain a JSON object.")
    return parsed


def _read_text_if_exists(root: Path, rel_path: str) -> str:
    if not rel_path:
        return ""
    path = root / rel_path
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _parse_state_metadata(text: str) -> StateMetadata:
    phase_id = ""
    phase_title = ""
    phase_match = re.search(r"- \*\*Phase\*\*:\s*(?P<number>\d+)\s*-\s*(?P<title>.+?)(?:\s+\*\*.*)?\.", text)
    if phase_match:
        phase_id = phase_match.group("number").zfill(2)
        phase_title = phase_match.group("title").strip()

    checkpoint_id = ""
    checkpoint_match = re.search(r"- \*\*Checkpoint\*\*:\s*(?P<id>CP-[0-9]+(?:-[0-9]+)?)(?:\s*-\s*.+)?", text)
    if checkpoint_match:
        checkpoint_id = checkpoint_match.group("id")

    checkpoint_path = ""
    path_match = re.search(r"- \*\*Checkpoint file\*\*:\s*`(?P<path>[^`]+)`", text)
    if path_match:
        checkpoint_path = path_match.group("path")

    frontmatter = _frontmatter_values(text)
    return StateMetadata(
        phase_id=phase_id,
        phase_title=phase_title,
        checkpoint_id=checkpoint_id,
        checkpoint_path=checkpoint_path,
        total_phases=_optional_int(frontmatter.get("progress.total_phases")),
        completed_phases=_optional_int(frontmatter.get("progress.completed_phases")),
        percent=_optional_int(frontmatter.get("progress.percent")),
    )


def _parse_checkpoint_metadata(text: str, fallback_id: str) -> CheckpointMetadata:
    heading = None
    if fallback_id:
        pattern = re.compile(rf"^##\s+({re.escape(fallback_id)})\s*(?:-\s*(.+))?$", re.MULTILINE)
        heading = pattern.search(text)
    if heading is None:
        heading = re.search(r"^##\s+(CP-[0-9]+(?:-[0-9]+)?)\s*(?:-\s*(.+))?$", text, re.MULTILINE)

    checkpoint_id = heading.group(1) if heading else ""
    title = (heading.group(2) or "").strip().rstrip(".") if heading else ""
    status_match = re.search(r"- \*\*Status\*\*:\s*(?P<status>.+)", text)
    status = status_match.group("status").strip().rstrip(".") if status_match else ""
    return CheckpointMetadata(checkpoint_id=checkpoint_id, title=title, status=status)


def _roadmap_phase_title(text: str, phase_id: str) -> str:
    if not phase_id:
        return ""
    phase_number = str(int(phase_id)) if phase_id.isdigit() else phase_id
    pattern = re.compile(rf"^- \[[ xX]\] \*\*Phase {re.escape(phase_number)}:\s*(?P<title>[^*]+)\*\*", re.MULTILINE)
    match = pattern.search(text)
    return match.group("title").strip() if match else ""


def _parse_roadmap_metadata(text: str) -> RoadmapMetadata:
    phase_ids: list[str] = []
    completed = 0
    for match in re.finditer(r"^- \[(?P<mark>[ xX])\] \*\*Phase (?P<number>[0-9]+):", text, re.MULTILINE):
        phase_ids.append(match.group("number").zfill(2))
        if match.group("mark").lower() == "x":
            completed += 1
    return RoadmapMetadata(total_phases=len(phase_ids), completed_phases=completed, phase_ids=phase_ids)


def _warnings(
    *,
    root: Path,
    phase_state: dict[str, object],
    state_path: str,
    roadmap_path: str,
    checkpoint_path: str,
    plan_path: str,
    verification_path: str,
    summary_path: str,
    state_meta: StateMetadata,
    roadmap_meta: RoadmapMetadata,
    active_checkpoint_id: str,
    active_checkpoint_status: str,
    plan_id: str | None,
    allowed_paths: list[str],
    acceptance_criteria: list[str],
    verification: list[str],
) -> list[PlanningWarning]:
    warnings: list[PlanningWarning] = []
    phase = _string_value(phase_state.get("phase"))
    active_files = [state_path, roadmap_path, checkpoint_path, plan_path, summary_path]
    if phase in {"plan", "execute", "done"}:
        active_files.append(verification_path)
    missing = [rel_path for rel_path in active_files if rel_path and not (root / rel_path).is_file()]
    if missing:
        warnings.append(
            PlanningWarning(
                code="missing_active_file",
                severity="blocking",
                message="One or more active planning files are missing.",
                paths=missing,
                required_read=True,
            )
        )

    current_checkpoint = _string_value(phase_state.get("current_checkpoint"))
    if state_meta.checkpoint_id and current_checkpoint and state_meta.checkpoint_id != current_checkpoint:
        warnings.append(
            PlanningWarning(
                code="state_checkpoint_drift",
                severity="blocking",
                message="STATE active checkpoint differs from phase-state current_checkpoint.",
                paths=[state_path, ".scratch/phase-state.json"],
                required_read=True,
            )
        )
    if state_meta.checkpoint_path and checkpoint_path and state_meta.checkpoint_path != checkpoint_path:
        warnings.append(
            PlanningWarning(
                code="state_checkpoint_path_drift",
                severity="blocking",
                message="STATE checkpoint file differs from phase-state checkpoint_path.",
                paths=[state_path, ".scratch/phase-state.json"],
                required_read=True,
            )
        )
    if current_checkpoint and active_checkpoint_id and current_checkpoint != active_checkpoint_id:
        warnings.append(
            PlanningWarning(
                code="checkpoint_file_drift",
                severity="blocking",
                message="Active checkpoint file does not contain phase-state current_checkpoint.",
                paths=[checkpoint_path, ".scratch/phase-state.json"],
                required_read=True,
            )
        )

    if state_meta.phase_id and roadmap_meta.phase_ids and state_meta.phase_id not in roadmap_meta.phase_ids:
        warnings.append(
            PlanningWarning(
                code="roadmap_active_phase_drift",
                severity="blocking",
                message="STATE active phase is not listed in ROADMAP.",
                paths=[state_path, roadmap_path],
                required_read=True,
            )
        )
    if state_meta.total_phases is not None and roadmap_meta.total_phases and state_meta.total_phases != roadmap_meta.total_phases:
        warnings.append(
            PlanningWarning(
                code="roadmap_total_phases_drift",
                severity="blocking",
                message="STATE progress total_phases differs from ROADMAP phase count.",
                paths=[state_path, roadmap_path],
                required_read=True,
            )
        )
    if (
        state_meta.completed_phases is not None
        and roadmap_meta.total_phases
        and state_meta.completed_phases != roadmap_meta.completed_phases
    ):
        warnings.append(
            PlanningWarning(
                code="roadmap_completed_phases_drift",
                severity="blocking",
                message="STATE progress completed_phases differs from ROADMAP completed phase count.",
                paths=[state_path, roadmap_path],
                required_read=True,
            )
        )

    canonical_plan_id = _plan_id_from_text(_read_text_if_exists(root, plan_path))
    if plan_id and canonical_plan_id and plan_id != canonical_plan_id:
        warnings.append(
            PlanningWarning(
                code="plan_id_drift",
                severity="blocking",
                message="phase-state plan_id differs from the active plan metadata.",
                paths=[plan_path, ".scratch/phase-state.json"],
                required_read=True,
            )
        )

    approved = bool(phase_state.get("approved"))
    if phase == "done" and approved:
        warnings.append(
            PlanningWarning(
                code="stale_execute_approval",
                severity="blocking",
                message="A done phase cannot carry execute approval for new edits.",
                paths=[".scratch/phase-state.json", state_path],
                required_read=True,
            )
        )
    if phase == "execute":
        if active_checkpoint_status.lower() in {"complete", "completed", "published", "done"}:
            warnings.append(
                PlanningWarning(
                    code="completed_checkpoint_execute_approval",
                    severity="blocking",
                    message="Execute approval points at a checkpoint that is already complete.",
                    paths=[checkpoint_path, ".scratch/phase-state.json"],
                    required_read=True,
                )
            )
        if approved and (not _string_value(phase_state.get("approved_by")) or not _string_value(phase_state.get("approved_at"))):
            warnings.append(
                PlanningWarning(
                    code="missing_approval_metadata",
                    severity="blocking",
                    message="Execute approval is missing approval provenance.",
                    paths=[".scratch/phase-state.json"],
                    required_read=True,
                )
            )
        if not plan_id:
            warnings.append(
                PlanningWarning(
                    code="missing_plan_id",
                    severity="blocking",
                    message="Execute phase is missing plan_id.",
                    paths=[".scratch/phase-state.json", plan_path],
                    required_read=True,
                )
            )
        if not allowed_paths:
            warnings.append(
                PlanningWarning(
                    code="empty_allowed_paths",
                    severity="blocking",
                    message="Execute phase has no allowed paths.",
                    paths=[".scratch/phase-state.json"],
                    required_read=True,
                )
            )
        if not acceptance_criteria:
            warnings.append(
                PlanningWarning(
                    code="empty_acceptance_criteria",
                    severity="blocking",
                    message="Execute phase has no acceptance criteria.",
                    paths=[".scratch/phase-state.json", plan_path],
                    required_read=True,
                )
            )
        if not verification:
            warnings.append(
                PlanningWarning(
                    code="empty_verification",
                    severity="blocking",
                    message="Execute phase has no verification commands.",
                    paths=[".scratch/phase-state.json", verification_path],
                    required_read=True,
                )
            )
    return warnings


def _execute_gate(
    *,
    phase: str,
    approved: bool,
    plan_id: str | None,
    phase_state: dict[str, object],
    warnings: list[PlanningWarning],
) -> tuple[bool, str]:
    blocking_codes = [warning.code for warning in warnings if warning.severity == "blocking"]
    if phase != "execute":
        return False, f"phase is {phase}; only phase=execute can project a valid execute gate."
    if not approved:
        return False, "phase-state approved is not true."
    if not plan_id:
        return False, "phase-state plan_id is missing."
    if not _string_value(phase_state.get("approved_by")) or not _string_value(phase_state.get("approved_at")):
        return False, "execute approval metadata is missing."
    if blocking_codes:
        return False, "blocking warnings prevent execute gate projection: " + ", ".join(blocking_codes)
    return True, "phase-state and active planning pointers project a valid execute gate."


def _required_reads(
    root: Path,
    state_path: str,
    roadmap_path: str,
    checkpoint_path: str,
    plan_path: str,
    verification_path: str,
    summary_path: str,
    warnings: list[PlanningWarning],
) -> list[str]:
    paths = [
        state_path,
        roadmap_path,
        *_codebase_read_paths(root),
        checkpoint_path,
        plan_path,
        verification_path,
        summary_path,
        ".scratch/phase-state.json",
    ]
    for warning in warnings:
        if warning.required_read:
            paths.extend(warning.paths)
    return _dedupe([path for path in paths if path])


def _plan_id_from_text(text: str) -> str:
    patterns = (
        r"^plan_id:\s*(?P<value>[^\s]+)\s*$",
        r"^- \*\*Plan ID\*\*:\s*(?P<value>\S+)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            return match.group("value").strip().strip('"').strip("'")
    return ""


def _phase_doc_path(active_phase_folder: str, phase_id: str, suffix: str) -> str:
    if not active_phase_folder or not phase_id:
        return ""
    return f"{active_phase_folder}/{phase_id}-{suffix}.md"


def _summary_doc_path(root: Path, active_phase_folder: str, phase_id: str, plan_path: str, checkpoint_id: str) -> str:
    candidates: list[str] = []
    if plan_path.endswith("-PLAN.md"):
        candidates.append(plan_path[: -len("-PLAN.md")] + "-SUMMARY.md")
    checkpoint_match = re.fullmatch(r"CP-(\d+)-(\d+)", checkpoint_id)
    if active_phase_folder and checkpoint_match:
        candidates.append(f"{active_phase_folder}/{checkpoint_match.group(1)}-{checkpoint_match.group(2)}-SUMMARY.md")
    candidates.append(_phase_doc_path(active_phase_folder, phase_id, "SUMMARY"))
    for candidate in candidates:
        if candidate and (root / candidate).is_file():
            return candidate
    return next((candidate for candidate in candidates if candidate and plan_path), "")


def _codebase_read_paths(root: Path) -> list[str]:
    codebase_root = root / ".planning/codebase"
    if not codebase_root.is_dir():
        return []
    return [path.relative_to(root).as_posix() for path in sorted(codebase_root.glob("*.md"))]


def _frontmatter_values(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    values: dict[str, str] = {}
    parents: list[tuple[int, str]] = []
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        while parents and parents[-1][0] >= indent:
            parents.pop()
        clean_value = value.strip().strip('"').strip("'")
        full_key = ".".join([item[1] for item in parents] + [key.strip()])
        if clean_value:
            values[full_key] = clean_value
        else:
            parents.append((indent, key.strip()))
    return values


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _phase_id_from_folder(folder: str) -> str:
    match = re.search(r"(?:^|/)([0-9]+)-[^/]+$", folder)
    return match.group(1).zfill(2) if match else ""


def _parent_path(path: str) -> str:
    if not path or "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _display_path(path: Path) -> str:
    parts = path.parts
    if ".scratch" in parts:
        return "/".join(parts[parts.index(".scratch") :])
    return str(path)
