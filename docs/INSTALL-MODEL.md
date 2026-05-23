# Install / Upgrade / Manifest Model

하네스를 타겟 프로젝트에 심고 갱신하는 메커니즘.

## 1. Manifest 구조 (`harness/manifest.json`)

> **Canonical artifact tables are in [`docs/ARTIFACTS.md`](ARTIFACTS.md)** — generated from
> `harness/manifest.json` by `python3 scripts/generate_artifacts_doc.py`.
> Do not hand-maintain file counts or pack lists here.

### 최상위 키

```json
{
  "version": "__release__",         // 릴리즈 시 interpolate
  "packs": { ... },                  // pack 정의 (count: see ARTIFACTS.md)
  "files": [ ... ],                  // manifest entries (count: see ARTIFACTS.md)
  "removed_in_version": [ ... ]      // graveyard — removed artifacts with upgrade_action
}
```

### Policy matrix

| Policy | Behavior |
|---|---|
| `harness-owned` | 읽기 전용. hash drift 검사 강함 |
| `managed` | mutable 이지만 hash-verified. AGENTS.md, planning 템플릿 |
| `managed-append` | append-only block (마커 포함). block-level hash |
| `project-owned` | application code. drift 검사 안 함 |
| `exclude` | 설치 시 skip |

### ManifestEntry dataclass (manifest.py)

```python
path: PurePosixPath          # 타겟 경로
source: PurePosixPath        # harness 트리 내 소스 경로
policy: str                  # 위 표 참고
owner: str = "core"          # core | adapter:<n> | pack:<n>
adapter: str | None          # roo | opencode | None (inferred)
profile: str | None          # generic | dotnet-etl | python-etl | react-web
pack: str | None             # workflow-core | tech-python | ...
retired_action: str          # remove_if_unmodified (default)
```

### Adapter inference

```python
.roo/*      → adapter="roo"
.roomodes   → adapter="roo"
.opencode/* → adapter="opencode"
```

`select_entries()` (manifest.py):
```python
if entry.adapter and entry.adapter not in requested_adapters: skip
if entry.profile and entry.profile not in requested_profiles: skip
if entry.pack and entry.pack not in requested_packs: skip
```

## 2. Skeleton (`harness/skeleton/clean/`)

2개 파일:
- `AGENTS.md` — agent rules (managed policy, partial managed-append for project section)
- `README.md` — project README (project-owned, 한 번만 복사)

## 3. Profiles (`harness/profiles/`)

| Profile | rules/ files | modes/ |
|---|---|---|
| generic | (none) | — |
| dotnet-etl | etl-tdd.md, data-bug-trace.md, restart-idempotency.md, etl-review.md | — |
| python-etl | (동일 4개) | — |
| react-web | ui-tdd.md, ui-review.md, ui-engineer-extras.md | modes/ |

각 profile/rules는 manifest에 entry 2개 (`.roo/rules-<role>/*` + `.opencode/profile-rules/*`).

## 4. Skill packs (`harness/skill-packs/`)

`workflow-core` (heavyweight, 9 files): data-workflow, ecosystem-skill-research, integration-boundary, multi-agent-review, release-readiness-audit, repository-evidence-research, risk-review, skill-plugin-composition, verification-contract.

다른 17개 pack은 각 1 file.

## 5. Install flow (`scripts/lib/install.py`, 753 LOC)

**호출**: `harness init --target <DIR>` 또는 `harness install --target <DIR>`.

### Phases

1. **Validate scopes**: requested adapters/profiles/packs ∈ KNOWN_*
2. **Load manifest**: parse + select entries
3. **Plan**:
   - file-by-file: source → dest, policy
   - managed-append: parse target, plan block merge
4. **Atomic batch**:
   - Create `.harness/.staging-<nonce>/`
   - Copy/render files
   - Write journal (sequence of renames)
   - fsync + rename batch
5. **Append blocks**: AGENTS.md 등에 managed:<slug> 블록 삽입
6. **Write install state**: `.harness/installed-manifest.json` (schema_version=2)
7. **Sync .roomodes**: roomodes_writer가 logical base/profile split
8. **Hook install (opt)**: `.git/hooks/pre-commit` 마커 블록 (hooks.py)
9. **install-record.json**: installer identity 기록 (git config email 자동, `--approver-email` 제거됨 — ADR-0002)

### Atomic batch (atomic_io.py + durable_fs.py)

- `.staging-<nonce>/` 안에 다 만들고
- journal 파일에 rename 시퀀스 기록
- fsync_parent_dir → os.replace 연속
- 완료 후 staging 삭제, journal 삭제

크래시 시 staging dir + journal 남음 → `install_recovery.recover_aborted_install()` 가 정리.

## 6. Upgrade flow (`scripts/lib/upgrade.py`, 890 LOC — heaviest aggregator)

**호출**: `harness upgrade --target <DIR>`.

### 의존 모듈 (Milestone 1 simplified)

```
adoption, atomic_io, exitcodes, install, manifest, manifest_reconciler,
manifest_v2, profiles, progress, roadmap_state, state, version
```

`release_trust` 의존 제거됨 (sec-7b에서 모듈 자체 삭제).

### Phases (ADR-0002: origin-trust fields stripped)

1. **Read target install state** (`installed-manifest.json` v2)
2. **Read source files from working tree** (no git tag verification, no commit SHA resolution)
3. **Manifest reconciliation** (`manifest_reconciler.py`, 463 LOC): 3-way merge
   - install된 sha vs 현재 sha vs 새 source sha
   - drift 검출: user-modified files → quarantine 또는 conflict
4. **Apply changes**: atomic batch (install.py와 동일)

### Dry-run

`--dry-run`: planned_writes 계산 + 출력. 디스크 변경 없음.

### Force

`--force`: 사용자가 수정한 harness-owned 파일도 덮어쓰기.

### Adopt-existing

`--adopt-existing`: 매뉴얼로 심어진 하네스에 대해 install state 합성 (`adoption.py`, 227 LOC).

## 7. Uninstall flow (`scripts/uninstall_harness.py`, 358 LOC)

Scope 선택 (roo / opencode / runtime / core / docs / all). 각 스코프 파일 제거 + .roomodes 정리 + hook 제거.

Conflicts/warnings: 사용자 편집된 managed 파일은 경고만, 강제 제거 안 함.

## 8. Manifest reconciler (`manifest_reconciler.py`, 463 LOC)

3-way merge:
- installed (manifest의 installed_sha256)
- current (디스크 현재 sha256)
- source (새 release source sha256)

결과:
- `unchanged`: skip
- `update`: source → disk
- `user_modified`: quarantine
- `vanished`: 디스크에서 사라짐 → restore 또는 skip
- `conflict`: user_modified + source_changed → conflicts/ 폴더로

## 9. Install state schema v2 (`.harness/installed-manifest.json`)

```json
{
  "schema_version": 2,
  "harness_version": "0.9.4",
  "scopes": {
    "adapters": ["roo", "opencode"],
    "profiles": ["generic"],
    "packs": ["workflow-core"]
  },
  "entries": [
    {
      "path": "...",
      "source": "...",
      "policy": "...",
      "installed_sha256": "...",
      "applied_sha256": "..."  // managed-append만
    },
    ...
  ],
  "managed_append": { "<dest>": ["<slug>", ...] }
}
```

**ADR-0002**: origin-trust fields (`trust_origin`, `release_tag`, `release_commit`) removed from schema — dead code for internal tool.

## 10. Adapter directories

| Adapter | Layout |
|---|---|
| `.roo/` | `commands/`, `rules/`, `rules-<role>/`, `skills/` |
| `.opencode/` | `commands/`, `profile-rules/` |

같은 repo에 둘 다 공존 가능.

## 11. Recovery directories

- `.harness/.staging-<nonce>/` — in-flight install
- `.harness/.staging-<nonce>.aborted` — sentinel
- `.harness/.staging-<nonce>.journal` — rename sequence
- `.harness/backups/<file>.<timestamp>.bak` — pre-mutation snapshots (retention 10)
- `.harness/conflicts/<file>` — quarantined user-modified files

## 12. Milestone 1 Completion: KEEP modules (deployment axis)

**KEEP**: install.py, upgrade.py, manifest.py, manifest_reconciler.py, append_block.py, managed_block.py, state.py, profiles.py, hooks.py, install_recovery.py, adoption.py, roomodes_writer.py, atomic_io.py, durable_fs.py, safe_open.py, backups.py, manifest_v2.py.

**Removed**: origin-trust fields from schema and all stamping logic (ADR-0002). Entry SHA verification/storage retained.
