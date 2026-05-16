"""Read and write `.roomodes` with a logical base/profile split.

`.roomodes` on disk is plain JSON of shape `{"customModes": [ ... ]}`. We do
not embed marker strings in the file (they would be invalid JSON). Instead the
writer recognizes the eight harness-baseline modes by slug and treats every
other entry whose `slug` is in `KNOWN_PROFILE_MODE_SLUGS` as profile-owned.
Any third mode it cannot classify is preserved as `unmanaged_modes` so a
later upgrade refuses to overwrite project-owned customizations.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BASE_MODE_SLUGS = (
    "orchestrator",
    "architect",
    "tdd-code",
    "diagnose",
    "review",
    "docs-issues",
    "ops-observability",
    "harness-maintainer",
)

KNOWN_PROFILE_MODE_SLUGS = frozenset({"ui-engineer"})


@dataclass
class RoomodesContent:
    base_modes: list[dict] = field(default_factory=list)
    profile_modes: list[dict] = field(default_factory=list)
    unmanaged_modes: list[dict] = field(default_factory=list)


def read(path: Path) -> RoomodesContent:
    data = json.loads(path.read_text(encoding="utf-8"))
    modes = data.get("customModes", [])
    base, profile, unmanaged = [], [], []
    for mode in modes:
        slug = mode.get("slug")
        if slug in BASE_MODE_SLUGS:
            base.append(mode)
        elif slug in KNOWN_PROFILE_MODE_SLUGS:
            profile.append(mode)
        else:
            unmanaged.append(mode)
    base.sort(key=lambda m: BASE_MODE_SLUGS.index(m["slug"]))
    return RoomodesContent(base_modes=base, profile_modes=profile, unmanaged_modes=unmanaged)


def write(path: Path, content: RoomodesContent) -> None:
    modes = list(content.base_modes) + list(content.profile_modes) + list(content.unmanaged_modes)
    payload = {"customModes": modes}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def set_profile_modes(path: Path, profile_modes: list[dict]) -> None:
    current = read(path)
    current.profile_modes = profile_modes
    write(path, current)
