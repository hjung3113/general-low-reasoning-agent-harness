"""Install flow: copy files, plan managed appends, sync roomodes, write install state."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

from lib.adoption import assert_safe_write_destination
from lib.append_block import (
    plan_managed_append,
    write_managed_append,
)
from lib.manifest import (
    MANIFEST_PATH,
    ManifestEntry,
    load_manifest,
    select_entries,
    source_path,
    destination_path,
    validate_managed_append_destinations,
    validate_scope_names,
    selected_pack_metadata,
)
from lib.profiles import default_packs_for_profile, normalize_profiles, db_packs
from lib.state import (
    INSTALL_STATE,
    scope_record,
    delegated_source_provenance,
    write_install_state,
    write_json,
    now_utc,
    file_hash,
    file_state,
    manifest_sha256,
    sha256_text,
)
from lib.version import (
    repo_root,
    resolve_harness_version,
    git_source_provenance,
    source_provenance,
)


def sync_roomodes_profile_modes(target: Path, profiles: Iterable[str], source_root: Path) -> None:
    """Replace the profile-modes section of target/.roomodes with the modes
    contributed by the currently installed profiles.

    If target/.roomodes does not exist (e.g. opencode-only install) this is a
    no-op. Profile-owned modes are read from
    ``<source_root>/harness/profiles/<profile>/modes/*.json``.
    """
    from lib import roomodes_writer

    roomodes_path = target / ".roomodes"
    if not roomodes_path.exists():
        return
    profile_modes: list[dict] = []
    for profile in profiles:
        modes_dir = source_root / "harness/profiles" / profile / "modes"
        if not modes_dir.exists():
            continue
        for mode_file in sorted(modes_dir.glob("*.json")):
            profile_modes.append(json.loads(mode_file.read_text(encoding="utf-8")))
    roomodes_writer.set_profile_modes(roomodes_path, profile_modes)


def install(
    *,
    root: Path,
    target: Path,
    dry_run: bool = False,
    adapters: set[str] | None = None,
    profiles: set[str] | None = None,
    packs: set[str] | None = None,
    harness_version: str = "0.0.0-dev+unknown",
) -> None:
    adapters = adapters if adapters is not None else {"roo"}
    profiles = profiles if profiles is not None else {"generic"}
    packs = packs if packs is not None else set()
    all_entries = load_manifest(root)
    validate_scope_names(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    entries = select_entries(all_entries, adapters=adapters, profiles=profiles, packs=packs)
    target = target.resolve()
    destinations = [
        (entry, source_path(root, entry), destination_path(target, entry))
        for entry in entries
        if entry.policy != "exclude"
    ]
    existing = [
        str(entry.path)
        for entry, _, destination in destinations
        if entry.policy not in {"managed-append", "project-owned"} and (destination.exists() or destination.is_symlink())
    ]
    if existing:
        raise SystemExit("Refusing to overwrite existing files during init: " + ", ".join(existing))

    if dry_run:
        print("init dry-run")
        print(f"target={target}")
        print(f"source={root.resolve()}")
        print(f"version={harness_version}")
        print("adapters=" + ",".join(sorted(adapters)))
        print("profiles=" + ",".join(sorted(profiles)))
        print("packs=" + ",".join(sorted(packs)))
        print(f"planned_writes={len(destinations)}")
        print("no mutation performed")
        return

    target.mkdir(parents=True, exist_ok=True)
    for entry, source, destination in destinations:
        if not dry_run:
            if entry.policy == "managed-append":
                write_managed_append(source=source, destination=destination, entry=entry)
            elif entry.policy == "project-owned" and destination.exists():
                continue
            else:
                write_copy(source, destination)

    sync_roomodes_profile_modes(target=target, profiles=profiles, source_root=root)
    write_install_state(root=root, target=target, entries=entries, adapters=adapters, profiles=profiles, packs=packs)


def write_copy(source: Path, destination: Path) -> None:
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def write_text_file(destination: Path, text: str) -> None:
    assert_safe_write_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")


def write_text_conflict(target: Path, path_text: str, content: str) -> None:
    from lib.roadmap_state import normalize_path
    destination = target / ".harness/conflicts" / normalize_path(path_text)
    write_text_file(destination, content)


def remove_empty_parents(path: Path, stop: Path) -> None:
    from lib.worktree import is_relative_to
    stop = stop.resolve()
    current = path.resolve()
    while current != stop and is_relative_to(current, stop):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
