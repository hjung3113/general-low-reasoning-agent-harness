"""Install state, scope resolution, hashing, and timestamping."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from lib.manifest import (
    KNOWN_ADAPTERS,
    KNOWN_PACKS,
    MANIFEST_PATH,
    ManifestEntry,
    destination_path,
    load_manifest,
    load_manifest_data,
    select_entries,
    selected_pack_metadata,
    source_path,
)
from lib.profiles import KNOWN_PROFILES
from lib.append_block import parse_append_block, sha256_text, normalize_payload
from lib.atomic_io import atomic_write_text


# ---------------------------------------------------------------------------
# Install-state path constant
# ---------------------------------------------------------------------------

INSTALL_STATE = Path(".harness/installed-manifest.json")


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
# Hashing and timestamping
# ---------------------------------------------------------------------------

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def manifest_sha256(root: Path) -> str:
    return file_hash(root / MANIFEST_PATH)


# ---------------------------------------------------------------------------
# JSON writing
# ---------------------------------------------------------------------------

def write_json(path: Path, data: object) -> None:
    # Routed through lib.atomic_io.atomic_write_text (T0-A) so a crash
    # between open() and close() cannot corrupt managed JSON state.
    # See .planning/phases/02b-hardening/plans/02b-01-T0-A-PLAN.md task 13.
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def scope_record(*, adapters: set[str], profiles: set[str], packs: set[str]) -> dict[str, list[str]]:
    return {
        "adapters": sorted(adapters),
        "profiles": sorted(profiles),
        "packs": sorted(packs),
    }


def installed_scope(installed: dict[str, object], key: str, *, default: set[str]) -> set[str]:
    init_options = installed.get("init_options", {})
    if isinstance(init_options, dict) and isinstance(init_options.get(key), list):
        return {str(value) for value in init_options[key]}
    values = installed.get(key)
    if isinstance(values, list):
        return {str(value) for value in values}
    return set(default)


def available_scopes(root: Path) -> dict[str, list[str]]:
    entries = load_manifest(root)
    manifest_packs = load_manifest_data(root).get("packs", {})
    pack_names = sorted(manifest_packs) if isinstance(manifest_packs, dict) else sorted(KNOWN_PACKS)
    return {
        "adapters": sorted({entry.adapter for entry in entries if entry.adapter} or KNOWN_ADAPTERS),
        "profiles": sorted({entry.profile for entry in entries if entry.profile} or KNOWN_PROFILES),
        "packs": pack_names,
    }


def parse_optional_scope(value: str | None) -> set[str] | None:
    if value is None:
        return None
    return parse_scope(value, default=set())


def parse_scope(value: str, *, default: set[str]) -> set[str]:
    if value is None:
        return set(default)
    normalized = value.strip().lower()
    if normalized in {"", "default"}:
        return set(default)
    if normalized in {"none", "core", "core-only"}:
        return set()
    if normalized in {"both", "all"}:
        return {"roo", "opencode"}
    return {item.strip().lower() for item in value.split(",") if item.strip()}


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def delegated_source_provenance(env: dict[str, str] | None = None) -> dict[str, str] | None:
    from lib.version import normalize_release_version
    env = os.environ if env is None else env
    kind = env.get("HARNESS_DELEGATED_SOURCE_KIND")
    repo = env.get("HARNESS_DELEGATED_SOURCE_REPO")
    ref = env.get("HARNESS_DELEGATED_SOURCE_REF")
    version = env.get("HARNESS_DELEGATED_SOURCE_VERSION")
    if not kind and not repo and not ref and not version:
        return None
    data: dict[str, str] = {}
    if kind:
        data["kind"] = kind
    if repo:
        data["repo"] = repo
    if ref:
        data["ref"] = ref
    if version:
        data["version"] = normalize_release_version(version)
    return data


# ---------------------------------------------------------------------------
# File state record
# ---------------------------------------------------------------------------

def file_state(
    *,
    root: Path,
    target: Path,
    entry: ManifestEntry,
    source: Path,
    applied_sha256: str | None = None,
) -> dict[str, object]:
    destination = destination_path(target, entry)
    state: dict[str, object] = {
        "policy": entry.policy,
        "version": _active_harness_version(),
        "installed_at": now_utc(),
        "source_sha256": file_hash(source),
        "sha256": file_hash(destination),
        "owner": entry.owner,
        "adapter": entry.adapter,
        "profile": entry.profile,
        "pack": entry.pack,
    }
    if applied_sha256 is not None:
        state["applied_sha256"] = applied_sha256
    return state


# ---------------------------------------------------------------------------
# Install state read/write
# ---------------------------------------------------------------------------

def write_install_state(
    *,
    root: Path,
    target: Path,
    entries: Iterable[ManifestEntry],
    adapters: set[str],
    profiles: set[str],
    packs: set[str],
) -> None:
    from lib.version import source_provenance
    files = {}
    for entry in entries:
        if entry.policy == "exclude":
            continue
        destination = target / entry.path
        source = source_path(root, entry)
        applied_sha256 = None
        if entry.policy == "managed-append":
            parsed = parse_append_block(destination.read_text(encoding="utf-8"), entry.path.as_posix())
            if parsed is None:
                raise SystemExit(f"Installed managed-append file is missing marker: {entry.path}")
            applied_sha256 = sha256_text(parsed.text)
        files[str(entry.path)] = file_state(
            root=root,
            target=target,
            entry=entry,
            source=source,
            applied_sha256=applied_sha256,
        )
    installed: dict[str, object] = {
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
    }
    provenance = source_provenance(root)
    if provenance:
        installed["source_provenance"] = provenance
    write_json(target / INSTALL_STATE, installed)


def read_install_state(target: Path) -> dict[str, object]:
    path = target / INSTALL_STATE
    if not path.exists():
        return {"version": None, "files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_installed_scope_names(installed: dict[str, object]) -> None:
    unknown = []
    scopes = installed.get("available_scopes", {})
    if not isinstance(scopes, dict):
        scopes = {}
    for kind, values, available in (
        ("adapter", installed.get("adapters", []), set(scopes.get("adapters", [])) or KNOWN_ADAPTERS),
        ("profile", installed.get("profiles", []), set(scopes.get("profiles", [])) or KNOWN_PROFILES),
        ("pack", installed.get("packs", []), set(scopes.get("packs", [])) or KNOWN_PACKS),
    ):
        if not isinstance(values, list):
            unknown.append(f"{kind}: <not an array>")
            continue
        missing = sorted(str(value) for value in values if value not in available)
        if missing:
            unknown.append(f"{kind}: {', '.join(missing)}")
    if unknown:
        raise SystemExit("Unknown installed harness scope: " + "; ".join(unknown))


def validate_installed_managed_append(*, destination: Path, path_text: str, info: dict[str, object]) -> None:
    try:
        parsed = parse_append_block(destination.read_text(encoding="utf-8"), path_text)
    except ValueError as exc:
        raise SystemExit(f"Installed managed-append marker is malformed: {path_text}") from exc
    if parsed is None:
        raise SystemExit(f"Installed managed-append marker is missing: {path_text}")
    applied_sha256 = info.get("applied_sha256")
    if applied_sha256 and sha256_text(parsed.text) != applied_sha256:
        raise SystemExit(f"Installed managed-append marker hash drift: {path_text}")


def required_phrase_scope(*, path: Path, relative: str) -> str:
    text = path.read_text(encoding="utf-8")
    if relative != "AGENTS.md":
        return text
    try:
        parsed = parse_append_block(text, relative)
    except ValueError as exc:
        raise SystemExit(f"Installed managed-append marker is malformed: {relative}") from exc
    if parsed is None:
        raise SystemExit(f"Required guardrail phrases missing: {relative}: missing managed marker")
    return parsed.payload
