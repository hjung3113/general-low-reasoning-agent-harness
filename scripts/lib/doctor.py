"""Diagnostic findings collector and renderer."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lib.manifest import (
    MANIFEST_PATH,
    ManifestEntry,
    load_manifest,
    select_entries,
)
from lib.roadmap_state import (
    normalize_path,
    parse_roadmap_phases,
    parse_state_snapshot,
    find_roadmap_state_sync_findings,
)
from lib.state import (
    INSTALL_STATE,
    read_install_state,
    installed_scope,
)
from lib.planning_status import ProjectionError, load_projection
from lib.workflow_static_checks import (
    installed_scope_issues,
    optional_phase_pointer_keys,
    verification_contract_issues,
)


@dataclass(frozen=True)
class DoctorFinding:
    severity: str
    code: str
    path: str
    cause: str
    impact: str
    fix: str
    evidence: str
    connects_to_db: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "cause": self.cause,
            "impact": self.impact,
            "fix": self.fix,
            "evidence": self.evidence,
            "connects_to_db": self.connects_to_db,
        }


def doctor(*, root: Path, output_format: str) -> None:
    sys.stdout.write(render_doctor_report(collect_doctor_findings(root), output_format=output_format))


def collect_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    findings.extend(phase_status_projection_doctor_findings(root))
    findings.extend(roadmap_state_doctor_findings(root))
    findings.extend(phase_state_path_doctor_findings(root))
    findings.extend(verification_contract_doctor_findings(root))
    findings.extend(review_evidence_path_doctor_findings(root))
    findings.extend(installed_scope_doctor_findings(root))
    findings.extend(command_mode_doctor_findings(root))
    findings.extend(db_context_doctor_findings(root))
    findings.extend(opencode_profile_rules_doctor_findings(root))
    findings.extend(scope_double_star_doctor_findings(root))
    findings.extend(hash_drift_doctor_findings(root))
    findings.append(
        DoctorFinding(
            severity="P3",
            code="diff_before_mutation",
            path="scripts/harness.py",
            cause="Harness mutation commands can change many files when init or upgrade runs against a target.",
            impact="A low-reasoning agent may apply changes before the user has reviewed the affected files.",
            fix="Run dry-run or diagnostic commands first, inspect the diff or conflict report, then mutate only after review.",
            evidence="Use `python3 scripts/harness.py upgrade --target <path> --dry-run` before upgrade and `git diff` before commit.",
        )
    )
    return sorted(findings, key=lambda item: (item.severity, item.code, item.path, item.cause))


def phase_status_projection_doctor_findings(root: Path) -> list[DoctorFinding]:
    try:
        projection = load_projection(root)
    except ProjectionError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="phase_status_projection_failed",
                path=".scratch/phase-state.json",
                cause=str(exc),
                impact="Low-reasoning preflight must fall back to the legacy durable planning read order.",
                fix="Repair the planning state files or use the legacy read order until `show_phase_status.py` succeeds.",
                evidence=str(exc),
            )
        ]

    findings: list[DoctorFinding] = []
    if not getattr(projection, "required_reads", []):
        findings.append(
            DoctorFinding(
                severity="P2",
                code="phase_status_required_reads_empty",
                path=".scratch/phase-state.json",
                cause="Phase-status projection succeeded but returned no required reads.",
                impact="A resumed low-reasoning agent may not know the minimum durable planning files to hydrate.",
                fix="Inspect `scripts/lib/planning_status.py` and the live planning pointers; do not add required_reads to phase-state by hand.",
                evidence="projection.required_reads is empty",
            )
        )
    for warning in projection.warnings:
        findings.append(
            DoctorFinding(
                severity=projection_warning_severity(warning.severity),
                code=f"phase_status_{warning.code}",
                path=warning.paths[0] if warning.paths else ".scratch/phase-state.json",
                cause=warning.message,
                impact="Low-reasoning workflow preflight cannot trust the status projection without the required reads.",
                fix="Inspect the warning paths and reconcile `.planning/**` with `.scratch/phase-state.json`.",
                evidence=", ".join(warning.paths) if warning.paths else warning.code,
            )
        )
    return findings


def projection_warning_severity(severity: str) -> str:
    if severity == "blocking":
        return "P1"
    if severity == "warning":
        return "P2"
    return "P3"


def roadmap_state_doctor_findings(root: Path) -> list[DoctorFinding]:
    return [
        DoctorFinding(
            severity="P1",
            code="roadmap_state_sync",
            path=".planning/ROADMAP.md",
            cause=finding,
            impact="Agents may execute the wrong phase, compute progress incorrectly, or trust stale approval pointers.",
            fix="Update `.planning/ROADMAP.md`, `.planning/STATE.md`, the active checkpoint, and `.scratch/phase-state.json` together.",
            evidence=finding,
        )
        for finding in find_roadmap_state_sync_findings(root)
    ]


def phase_state_path_doctor_findings(root: Path) -> list[DoctorFinding]:
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return [
            DoctorFinding(
                severity="P1",
                code="phase_state_missing",
                path=".scratch/phase-state.json",
                cause="Live phase gate file is missing.",
                impact="Implementation workflows cannot prove phase, plan_id, approved state, allowed paths, or verification.",
                fix="Create `.scratch/phase-state.json` from schema/example and point it at durable `.planning/` files.",
                evidence="missing file",
            )
        ]
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="phase_state_invalid_json",
                path=".scratch/phase-state.json",
                cause=str(exc),
                impact="Harness checks and workflow gates cannot parse the live phase state.",
                fix="Repair JSON syntax and validate with `.scratch/phase-state.schema.json`.",
                evidence=f"line {exc.lineno} column {exc.colno}",
            )
        ]
    findings: list[DoctorFinding] = []
    for key in ("state_path", "plan_path", "checkpoint_path"):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            findings.append(
                DoctorFinding(
                    severity="P1",
                    code="phase_state_pointer_missing",
                    path=".scratch/phase-state.json",
                    cause=f"{key} points to missing path {value!r}.",
                    impact="Fresh sessions may restart from a non-existent plan or checkpoint.",
                    fix="Update the pointer to an existing durable planning file or restore the missing file.",
                    evidence=f"{key}={value}",
                )
            )
    phase = state.get("phase")
    for key in optional_phase_pointer_keys(phase):
        value = state.get(key)
        if isinstance(value, str) and value and not (root / normalize_path(value)).exists():
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="phase_state_optional_pointer_missing",
                    path=".scratch/phase-state.json",
                    cause=f"{key} points to missing path {value!r}.",
                    impact="Workflow reports may omit verification or closure evidence, but the live gate remains controlled by required phase pointers.",
                    fix="Restore the missing artifact or remove the optional pointer until the artifact exists.",
                    evidence=f"{key}={value}",
                )
            )
    return findings


def verification_contract_doctor_findings(root: Path) -> list[DoctorFinding]:
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    findings: list[DoctorFinding] = []
    for issue in verification_contract_issues(state):
        findings.append(
            DoctorFinding(
                severity="P2",
                code="verification_placeholder",
                path=".scratch/phase-state.json",
                cause=f"verification[{issue['index']}] is a {issue['reason']}.",
                impact="A low-reasoning agent may claim done without concrete evidence.",
                fix="Replace the placeholder with an exact command or an observable review action that already fits the phase.",
                evidence=issue["command"],
            )
        )
    return findings


def review_evidence_path_doctor_findings(root: Path) -> list[DoctorFinding]:
    """T0-4 (ADR-004): warn when ``review[i].evidence_path == ""``.

    Non-failing finding. The schema accepts the empty-string sentinel so the
    T0-4 migrator can produce valid output for soft-prefix entries it
    relocates from ``verification``; this finding prompts maintainers to
    backfill the path manually.
    """
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    review = state.get("review") or []
    if not isinstance(review, list):
        return []
    findings: list[DoctorFinding] = []
    for index, entry in enumerate(review):
        if not isinstance(entry, dict):
            continue
        ev = entry.get("evidence_path")
        if ev == "":
            actor = entry.get("actor", "?")
            findings.append(
                DoctorFinding(
                    severity="P3",
                    code="review_evidence_path_empty",
                    path=".scratch/phase-state.json",
                    cause=f"review[{index}] (actor={actor!r}) has empty evidence_path.",
                    impact="Reviewers cannot audit which artifact supports the human evidence; "
                           "the T0-4 migrator leaves this empty when it relocates a soft-prefix verification entry.",
                    fix="Backfill review[{}].evidence_path with the URL or repo-relative path of the supporting artifact.".format(index),
                    evidence=f"review[{index}].evidence_path=''",
                )
            )
    return findings


def installed_scope_doctor_findings(root: Path) -> list[DoctorFinding]:
    return [
        DoctorFinding(
            severity="P2",
            code=issue["code"],
            path=str(INSTALL_STATE),
            cause=issue["cause"],
            impact=issue["impact"],
            fix=issue["fix"],
            evidence=issue["evidence"],
        )
        for issue in installed_scope_issues(root / INSTALL_STATE)
    ]


def command_mode_doctor_findings(root: Path) -> list[DoctorFinding]:
    roomodes_path = root / ".roomodes"
    commands_dir = root / ".roo/commands"
    if not roomodes_path.exists() or not commands_dir.exists():
        return []
    try:
        modes = json.loads(roomodes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            DoctorFinding(
                severity="P1",
                code="roomodes_invalid_json",
                path=".roomodes",
                cause=str(exc),
                impact="Roo cannot reliably load project-local modes.",
                fix="Repair `.roomodes` JSON and run `jq . .roomodes >/dev/null`.",
                evidence=f"line {exc.lineno} column {exc.colno}",
            )
        ]
    _roo_builtin = frozenset({"ask", "code", "architect", "debug", "orchestrator"})
    known = {mode["slug"] for mode in modes.get("customModes", []) if isinstance(mode, dict) and "slug" in mode} | _roo_builtin
    findings: list[DoctorFinding] = []
    for command in commands_dir.glob("*.md"):
        text = command.read_text(encoding="utf-8")
        match = re.search(r"^mode:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
        if match and match.group(1) not in known:
            relative = str(command.relative_to(root))
            findings.append(
                DoctorFinding(
                    severity="P1",
                    code="command_unknown_mode",
                    path=relative,
                    cause=f"Command references unknown Roo mode {match.group(1)!r}.",
                    impact="The slash command may route to a mode that Roo cannot start.",
                    fix="Update the command frontmatter or add the missing mode to `.roomodes`.",
                    evidence=f"{relative} -> {match.group(1)}",
                )
            )
    return findings


def db_context_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    gitignore_path = root / ".gitignore"
    gitignore = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    required_patterns = [".db-context/", "db-context.config.json", "*.db-context.config.json", ".env", ".env.*", "!.env.example"]
    for pattern in required_patterns:
        if pattern not in gitignore:
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="db_context_secret_ignore_missing",
                    path=".gitignore",
                    cause=f"Secret-bearing DB context pattern {pattern!r} is not ignored.",
                    impact="Connection strings or generated DB context artifacts may be committed accidentally.",
                    fix=f"Add `{pattern}` to `.gitignore`.",
                    evidence=pattern,
                )
            )
    snapshot_path = root / ".db-context/latest.json"
    if snapshot_path.exists():
        try:
            report = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="db_context_snapshot_invalid_json",
                    path=".db-context/latest.json",
                    cause=str(exc),
                    impact="DB-dependent workflows cannot safely read cached database context.",
                    fix="Refresh the DB context snapshot after explicit user approval or repair the JSON.",
                    evidence=f"line {exc.lineno} column {exc.colno}",
                )
            )
        else:
            options = report.get("collection_options", {})
            if options.get("snapshot_scope") == "selected" and not any(
                options.get(key) for key in ("include_tables", "include_procedures", "include_jobs")
            ):
                findings.append(
                    DoctorFinding(
                        severity="P2",
                        code="db_context_selected_empty",
                        path=".db-context/latest.json",
                        cause="Snapshot scope is selected but no selected objects are recorded.",
                        impact="Agents may believe the snapshot is intentionally narrow while it contains no target object list.",
                        fix="Refresh with `--snapshot-scope selected` plus `--include-tables`, `--include-procedures`, or `--include-jobs`.",
                        evidence="collection_options.snapshot_scope=selected",
                    )
                )
            if options.get("include_jobs") and "agent_jobs" not in report:
                findings.append(
                    DoctorFinding(
                        severity="P2",
                        code="db_context_jobs_requested_not_collected",
                        path=".db-context/latest.json",
                        cause="Selected jobs are recorded but SQL Agent job metadata is absent.",
                        impact="Workflow review may miss job commands or schedules.",
                        fix="Refresh with `--include-agent-jobs --include-jobs <names>` after explicit user approval.",
                        evidence="include_jobs present; agent_jobs missing",
                    )
                )
    return findings


def opencode_profile_rules_doctor_findings(root: Path) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    cmd_dir = root / ".opencode/commands"
    if not cmd_dir.exists():
        return findings
    for name in ("discuss.md", "plan.md", "execute.md", "done.md"):
        path = cmd_dir / name
        if not path.exists():
            continue
        if ".opencode/profile-rules/" not in path.read_text(encoding="utf-8"):
            findings.append(
                DoctorFinding(
                    severity="P2",
                    code="opencode_profile_rules_missing",
                    path=f".opencode/commands/{name}",
                    cause=f"{name} is missing the .opencode/profile-rules/ read instruction.",
                    impact="Profile-specific rules will not be loaded when the command is invoked.",
                    fix=f"Add the profile-rules read instruction to .opencode/commands/{name}.",
                    evidence=f"{name}: missing .opencode/profile-rules/ read instruction",
                )
            )
    return findings


def scope_double_star_doctor_findings(root: Path) -> list[DoctorFinding]:
    """T0-2-SecM1: warn when a scope entry contains literal `**`.

    Per ADR-002 (G2-E) the loader treats `**` as a single-level `*`; this is
    an easy misconception for operators familiar with gitignore/rsync. We
    surface a P3 finding (non-failing) per offending entry so the operator
    can rewrite the pattern using explicit deeper paths if recursion was
    intended.
    """
    path = root / ".scratch/phase-state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    findings: list[DoctorFinding] = []
    for field in ("allowed_paths", "blocked_paths"):
        entries = state.get(field, []) or []
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, str):
                continue
            if "**" not in entry:
                continue
            findings.append(
                DoctorFinding(
                    severity="P3",
                    code="scope_double_star_treated_as_single_star",
                    path=".scratch/phase-state.json",
                    cause=(
                        f"scope entry {entry!r} uses `**` which is treated as `*` "
                        f"(single-level); use deeper paths if recursion intended."
                    ),
                    impact=(
                        "Operators expecting gitignore-style recursive globbing may "
                        "see fewer matches than intended; the loader silently treats "
                        "`**` as a single segment per ADR-002."
                    ),
                    fix=(
                        f"Rewrite {field}[{index}] using explicit deeper paths "
                        f"(e.g., 'docs/a/*.md', 'docs/a/b/*.md') instead of `**`."
                    ),
                    evidence=f"{field}[{index}]={entry}",
                )
            )
    return findings


def hash_drift_doctor_findings(root: Path) -> list[DoctorFinding]:
    """T8b: always-on per-policy hash drift detection for harness doctor.

    Calls ``verify_hashes(root)`` unconditionally (no ``--verify-hashes`` flag
    needed — doctor is a diagnostic command that is expected to be slower).
    Each drift finding surfaces as a P1 DoctorFinding.
    """
    try:
        from lib.check import verify_hashes as _verify_hashes, format_hash_drift_errors
    except ImportError:
        return []

    installed_state = root / INSTALL_STATE
    if not installed_state.exists():
        return []

    try:
        drift_list = _verify_hashes(root)
    except Exception:
        return []

    findings: list[DoctorFinding] = []
    for f in drift_list:
        findings.append(
            DoctorFinding(
                severity="P1",
                code=f.error_code,
                path=f.path,
                cause=(
                    f"On-disk hash ({f.found[:12]}…) does not match installed hash "
                    f"({f.expected[:12]}…) for policy={f.policy!r}."
                ),
                impact=(
                    "Harness-managed file has been modified outside of `harness upgrade`. "
                    "Agents may run against a tampered or stale file."
                ),
                fix="Run `harness upgrade --target <target>` to restore the file to its installed state.",
                evidence=f"{f.error_code}: {f.path}",
            )
        )
    return findings


def render_doctor_report(findings: list[DoctorFinding], *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps({"findings": [finding.to_dict() for finding in findings]}, indent=2, sort_keys=True) + "\n"
    if output_format != "markdown":
        raise SystemExit("doctor format must be markdown or json")
    if not findings:
        return "# Harness Doctor\n\nNo findings.\n"
    lines = ["# Harness Doctor", ""]
    for finding in findings:
        lines.extend(
            [
                f"## {finding.severity} {finding.code}",
                "",
                f"- Path: `{finding.path}`",
                f"- Cause: {finding.cause}",
                f"- Impact: {finding.impact}",
                f"- Fix: {finding.fix}",
                f"- Evidence: {finding.evidence}",
                f"- Connects to DB: `{str(finding.connects_to_db).lower()}`",
                "",
            ]
        )
    return "\n".join(lines)
