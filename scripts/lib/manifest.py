"""Manifest model, loading, selection, and validation."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from lib.profiles import KNOWN_PROFILES


# ---------------------------------------------------------------------------
# Runtime version constants – the authoritative copy lives in harness.py;
# this module mirrors them and uses a lazy lookup so that mocking
# harness.HARNESS_VERSION in tests propagates correctly.
# ---------------------------------------------------------------------------
HARNESS_VERSION: str = "0.0.0-dev+unknown"
MANIFEST_SOURCE_VERSION: str = "__release__"


def _active_harness_version() -> str:
    """Return the currently-active harness version.

    Reads from ``harness.HARNESS_VERSION`` when the harness module is already
    imported (so that test patches and run()-time updates are respected),
    otherwise falls back to this module's own ``HARNESS_VERSION``.
    """
    harness_mod = sys.modules.get("harness")
    if harness_mod is not None:
        return getattr(harness_mod, "HARNESS_VERSION", HARNESS_VERSION)
    return HARNESS_VERSION

# ---------------------------------------------------------------------------
# Paths and scope constants
# ---------------------------------------------------------------------------
MANIFEST_PATH = Path("harness/manifest.json")

KNOWN_ADAPTERS: set[str] = {"roo", "opencode"}
KNOWN_POLICIES: set[str] = {"harness-owned", "managed", "managed-append", "project-owned", "exclude"}
KNOWN_PACKS: set[str] = {
    "workflow-core",
    "tech-python",
    "tech-react",
    "tech-typescript",
    "tech-tailwind",
    "tech-csharp",
    "tech-mssql",
    "tech-postgresql",
    "workflow-data-analysis",
    "workflow-data-processing",
    "workflow-etl",
    "workflow-db-context",
    "workflow-web-development",
    "workflow-tdd",
    "workflow-debugging",
    "workflow-code-review",
    "workflow-skill-authoring",
    "workflow-security-review",
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestEntry:
    path: PurePosixPath
    source: PurePosixPath
    policy: str
    owner: str = "core"
    adapter: str | None = None
    profile: str | None = None
    pack: str | None = None
    retired_action: str = "remove_if_unmodified"


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def infer_adapter(path_text: str) -> str | None:
    if path_text == ".roomodes" or path_text.startswith(".roo/"):
        return "roo"
    if path_text == "docs/roo-orchestration-design.md":
        return "roo"
    if path_text.startswith(".opencode/"):
        return "opencode"
    return None


def infer_pack(path_text: str) -> str | None:
    if path_text.startswith(".db-context/") or "db_context" in path_text or path_text == "docs/db-context-snapshot.md":
        return "db-context"
    return None


def infer_owner(path_text: str) -> str:
    adapter = infer_adapter(path_text)
    if adapter:
        return f"adapter:{adapter}"
    pack = infer_pack(path_text)
    if pack:
        return f"pack:{pack}"
    return "core"


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

def validate_managed_append_destinations(entries: Iterable[ManifestEntry]) -> None:
    seen: dict[str, ManifestEntry] = {}
    duplicates: list[str] = []
    for entry in entries:
        if entry.policy != "managed-append":
            continue
        path_text = str(entry.path)
        if path_text in seen:
            duplicates.append(path_text)
        seen[path_text] = entry
    if duplicates:
        raise SystemExit("Duplicate managed-append destinations: " + ", ".join(sorted(set(duplicates))))


def load_manifest(root: Path) -> list[ManifestEntry]:
    data = load_manifest_data(root)
    entries = []
    for item in data.get("files", []):
        policy = item["policy"]
        if policy not in KNOWN_POLICIES:
            raise SystemExit(f"Unknown manifest policy: {policy}")
        entries.append(
            ManifestEntry(
                path=PurePosixPath(item["path"]),
                source=PurePosixPath(item["source"]),
                policy=policy,
                owner=item.get("owner") or infer_owner(item["path"]),
                adapter=item.get("adapter") or infer_adapter(item["path"]),
                profile=item.get("profile"),
                pack=item.get("pack") or infer_pack(item["path"]),
                retired_action=item.get("retired_action", "remove_if_unmodified"),
            )
        )
    validate_managed_append_destinations(entries)
    return entries


def load_manifest_data(root: Path, *, version: str | None = None) -> dict[str, object]:
    manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    resolved_version = version or _active_harness_version()
    source_version = manifest.get("version")
    if source_version not in {MANIFEST_SOURCE_VERSION, resolved_version}:
        raise SystemExit(
            f"Manifest source version must be {MANIFEST_SOURCE_VERSION!r} or the resolved version {resolved_version!r}."
        )
    manifest["version"] = resolved_version
    return manifest


def selected_pack_metadata(root: Path, packs: set[str]) -> dict[str, object]:
    metadata = load_manifest_data(root).get("packs", {})
    if not isinstance(metadata, dict):
        return {}
    return {pack: metadata[pack] for pack in sorted(packs) if pack in metadata}


# ---------------------------------------------------------------------------
# Selection and validation
# ---------------------------------------------------------------------------

def select_entries(
    entries: Iterable[ManifestEntry],
    *,
    adapters: set[str],
    profiles: set[str],
    packs: set[str],
) -> list[ManifestEntry]:
    selected = []
    for entry in entries:
        if entry.adapter and entry.adapter not in adapters:
            continue
        if entry.profile and entry.profile not in profiles:
            continue
        if entry.pack and entry.pack not in packs:
            continue
        selected.append(entry)
    return selected


def validate_scope_names(
    entries: Iterable[ManifestEntry],
    *,
    adapters: set[str],
    profiles: set[str],
    packs: set[str],
) -> None:
    entries = list(entries)
    available_adapters = {entry.adapter for entry in entries if entry.adapter}
    available_profiles = {entry.profile for entry in entries if entry.profile}
    available_packs = {entry.pack for entry in entries if entry.pack}
    unknown = []
    for kind, requested, available in (
        ("adapter", adapters, available_adapters),
        ("profile", profiles, available_profiles),
        ("pack", packs, available_packs),
    ):
        missing = sorted(requested - available)
        if missing:
            unknown.append(f"{kind}: {', '.join(missing)}")
    if unknown:
        raise SystemExit("Unknown harness scope requested: " + "; ".join(unknown))


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def source_path(root: Path, entry: ManifestEntry) -> Path:
    if entry.source.is_absolute():
        raise SystemExit(f"Absolute manifest sources are not allowed: {entry.source}")
    path = (root / entry.source).resolve()
    if not _is_relative_to(path, root.resolve()):
        raise SystemExit(f"Manifest source escapes repository: {entry.source}")
    return path


def destination_path(target: Path, entry: ManifestEntry) -> Path:
    if entry.path.is_absolute():
        raise SystemExit(f"Manifest destination escapes target: {entry.path}")
    parts = entry.path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or re.match(r"^[A-Za-z]:", parts[0]):
        raise SystemExit(f"Manifest destination escapes target: {entry.path}")
    destination = (target / Path(*parts)).resolve(strict=False)
    if not _is_relative_to(destination, target.resolve(strict=False)):
        raise SystemExit(f"Manifest destination escapes target: {entry.path}")
    return destination
