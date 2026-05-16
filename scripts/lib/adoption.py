"""Manual install adoption: synthesize install state from a pre-existing target."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lib.manifest import (
    ManifestEntry,
    source_path,
    destination_path,
    selected_pack_metadata,
)
from lib.state import (
    file_hash,
    file_state,
    manifest_sha256,
    sha256_text,
    normalize_payload,
    scope_record,
    available_scopes,
)
from lib.append_block import (
    render_append_block,
    parse_append_block,
)


# ---------------------------------------------------------------------------
# Runtime version – mirrors the authoritative copy in harness.py via lazy
# lookup so that test patches and run()-time updates are respected.
# ---------------------------------------------------------------------------

def _active_harness_version() -> str:
    harness_mod = sys.modules.get("harness")
    if harness_mod is not None:
        return getattr(harness_mod, "HARNESS_VERSION", "0.0.0-dev+unknown")
    return "0.0.0-dev+unknown"


# ---------------------------------------------------------------------------
# Safety guard
# ---------------------------------------------------------------------------

def assert_safe_write_destination(destination: Path) -> None:
    for candidate in (destination, *destination.parents):
        if candidate.is_symlink():
            raise SystemExit(f"Refusing to write through symlink: {candidate}")
        if candidate == candidate.parent:
            break


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdoptionConflict:
    path_text: str
    content: str


@dataclass(frozen=True)
class AdoptionPlan:
    installed: dict[str, object]
    conflicts: list[AdoptionConflict]
    backups: list[AdoptionConflict]


# ---------------------------------------------------------------------------
# Core adoption functions
# ---------------------------------------------------------------------------

def normalize_selected_project_owned_state(
    *,
    root: Path,
    target: Path,
    entries: Iterable[ManifestEntry],
    installed: dict[str, object],
) -> None:
    files = installed.setdefault("files", {})
    if not isinstance(files, dict):
        return
    for entry in entries:
        if entry.policy != "project-owned":
            continue
        path_text = str(entry.path)
        destination = destination_path(target, entry)
        if not destination.exists():
            continue
        files[path_text] = file_state(
            root=root,
            target=target,
            entry=entry,
            source=source_path(root, entry),
        )


def build_adopted_install_state(
    *,
    root: Path,
    target: Path,
    entries: Iterable[ManifestEntry],
    adapters: set[str],
    profiles: set[str],
    packs: set[str],
    force: bool,
) -> AdoptionPlan:
    files: dict[str, object] = {}
    conflicts: list[AdoptionConflict] = []
    backups: list[AdoptionConflict] = []
    selected_entries = [entry for entry in entries if entry.policy != "exclude"]
    required_project_owned = [
        entry
        for entry in selected_entries
        if entry.policy == "project-owned" and is_required_adoption_project_owned_path(entry.path.as_posix())
    ]
    missing_project_owned = [
        str(entry.path) for entry in required_project_owned if not destination_path(target, entry).exists()
    ]
    if missing_project_owned:
        raise SystemExit(
            "Cannot adopt target missing required project-owned files: " + ", ".join(sorted(missing_project_owned))
        )
    has_existing_harness_artifact = any(
        is_existing_harness_artifact(root=root, target=target, entry=entry) for entry in selected_entries
    )
    if not has_existing_harness_artifact:
        raise SystemExit("Cannot adopt target without existing selected harness files. Run init instead.")

    for entry in selected_entries:
        destination = destination_path(target, entry)
        assert_safe_write_destination(destination)

    for entry in selected_entries:
        path_text = str(entry.path)
        source = source_path(root, entry)
        destination = destination_path(target, entry)

        if entry.policy == "project-owned":
            if destination.exists():
                files[path_text] = file_state(root=root, target=target, entry=entry, source=source)
            continue

        if entry.policy == "managed-append":
            block = render_append_block(source, entry)
            if not destination.exists():
                continue
            text = destination.read_text(encoding="utf-8")
            try:
                parsed = parse_append_block(text, entry.path.as_posix())
            except ValueError:
                conflicts.append(AdoptionConflict(f"{entry.path}.new", block))
                continue
            if parsed is None:
                continue
            block_hash = sha256_text(block)
            current_hash = sha256_text(parsed.text)
            source_payload = source.read_text(encoding="utf-8")
            if current_hash != block_hash and normalize_payload(parsed.payload) != normalize_payload(source_payload):
                conflicts.append(AdoptionConflict(f"{entry.path}.new", block))
                continue
            files[path_text] = file_state(
                root=root,
                target=target,
                entry=entry,
                source=source,
                applied_sha256=current_hash,
            )
            continue

        if entry.policy in {"harness-owned", "managed"}:
            if not destination.exists():
                continue
            if file_hash(destination) == file_hash(source):
                files[path_text] = file_state(root=root, target=target, entry=entry, source=source)
                continue
            if force:
                backups.append(AdoptionConflict(f"{entry.path}.adopted", destination.read_text(encoding="utf-8")))
                continue
            conflicts.append(AdoptionConflict(f"{entry.path}.new", source.read_text(encoding="utf-8")))

    return AdoptionPlan(
        installed={
            "state_schema_version": 2,
            "version": _active_harness_version(),
            "manifest_sha256": manifest_sha256(root),
            "source": str(root),
            "adapters": sorted(adapters),
            "profiles": sorted(profiles),
            "packs": sorted(packs),
            "init_options": scope_record(adapters=adapters, profiles=profiles, packs=packs),
            "pack_metadata": selected_pack_metadata(root, packs),
            "available_scopes": available_scopes(root),
            "files": files,
        },
        conflicts=conflicts,
        backups=backups,
    )


def is_required_adoption_project_owned_path(path_text: str) -> bool:
    return path_text in {
        ".planning/STATE.md",
        ".planning/ROADMAP.md",
        ".scratch/phase-state.json",
    } or path_text.startswith(".planning/codebase/")


def is_optional_project_owned_path(path_text: str) -> bool:
    return path_text == "README.md"


def is_existing_harness_artifact(*, root: Path, target: Path, entry: ManifestEntry) -> bool:
    if entry.policy not in {"harness-owned", "managed", "managed-append"}:
        return False
    destination = destination_path(target, entry)
    if not destination.exists():
        return False
    if entry.policy != "managed-append":
        return True
    try:
        return parse_append_block(destination.read_text(encoding="utf-8"), entry.path.as_posix()) is not None
    except ValueError:
        return True
