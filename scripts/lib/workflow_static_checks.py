"""Static workflow checks for installed low-reasoning harnesses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PLACEHOLDER_ENTRY = re.compile(r"^(?:todo|tbd|placeholder)\s*(?::|\.{3}|\.\s*$|-|$)", re.IGNORECASE)
EXACT_PLACEHOLDERS = {"manual test", "test manually"}


def verification_placeholder_reason(command: str) -> str | None:
    stripped = command.strip()
    normalized = stripped.lower()
    if not stripped:
        return "empty verification entry"
    if normalized in EXACT_PLACEHOLDERS or PLACEHOLDER_ENTRY.match(stripped):
        return "placeholder verification entry"
    return None


def verification_contract_issues(state: dict[str, Any]) -> list[dict[str, str]]:
    verification = state.get("verification", [])
    if not isinstance(verification, list):
        return []
    issues: list[dict[str, str]] = []
    for index, command in enumerate(verification):
        if not isinstance(command, str):
            continue
        placeholder_reason = verification_placeholder_reason(command)
        if placeholder_reason:
            issues.append(
                {
                    "index": str(index),
                    "command": command,
                    "reason": placeholder_reason,
                }
            )
    return issues


def optional_phase_pointer_keys(phase: object) -> tuple[str, ...]:
    if phase in {"plan", "execute"}:
        return ("verification_path",)
    if phase == "done":
        return ("verification_path", "summary_path")
    return ()


def installed_scope_issues(installed_path: Path) -> list[dict[str, str]]:
    if not installed_path.exists():
        return []
    try:
        installed = json.loads(installed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            {
                "code": "installed_manifest_invalid_json",
                "cause": str(exc),
                "impact": "Harness upgrade and scope audits cannot determine which adapters, profiles, or packs are active.",
                "fix": "Repair `.harness/installed-manifest.json` or reinstall the harness.",
                "evidence": f"line {exc.lineno} column {exc.colno}",
            }
        ]
    files = installed.get("files", {})
    if not isinstance(files, dict):
        return [
            {
                "code": "installed_manifest_files_invalid",
                "cause": "installed files metadata is not an object.",
                "impact": "Harness scope checks cannot prove selected adapters, profiles, or packs have installed files.",
                "fix": "Repair `.harness/installed-manifest.json` or reinstall the harness.",
                "evidence": "files",
            }
        ]
    issues: list[dict[str, str]] = []
    for field, selected_key in (
        ("adapter", "adapters"),
        ("profile", "profiles"),
        ("pack", "packs"),
    ):
        selected = installed.get(selected_key, [])
        if not isinstance(selected, list):
            issues.append(_invalid_scope_issue(selected_key, f"{selected_key} is not an array.", selected_key))
            continue
        for index, value in enumerate(selected):
            if not isinstance(value, str):
                issues.append(
                    _invalid_scope_issue(
                        selected_key,
                        f"{selected_key}[{index}] is not a string.",
                        f"{selected_key}[{index}]={value!r}",
                    )
                )
                continue
            matching = [
                path_text
                for path_text, info in files.items()
                if isinstance(info, dict) and info.get(field) == value
            ]
            if not matching:
                issues.append(
                    {
                        "code": "installed_scope_without_files",
                        "cause": f"Selected {field} {value!r} has no installed file metadata.",
                        "impact": "A model may treat an adapter, profile, or skill pack as active even though no installed files prove it.",
                        "fix": "Reinstall or upgrade the harness with the intended scopes; do not infer stack support from source files alone.",
                        "evidence": f"{selected_key}={value}",
                    }
                )
    return issues


def _invalid_scope_issue(selected_key: str, cause: str, evidence: str) -> dict[str, str]:
    return {
        "code": "installed_scope_invalid",
        "cause": cause,
        "impact": "Low-reasoning agents cannot tell which harness scopes are active.",
        "fix": f"Repair `{selected_key}` in `.harness/installed-manifest.json` or reinstall the harness.",
        "evidence": evidence,
    }
