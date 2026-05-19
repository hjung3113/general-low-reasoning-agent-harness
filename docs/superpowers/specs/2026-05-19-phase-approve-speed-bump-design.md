# Spec — v0.9.0: phase.approve Speed Bump + Terminology Cleanup

**Date**: 2026-05-19
**Owner**: kimhyojung
**Status**: Draft — awaiting user review

---

## 1. Purpose

Reduce friction in the most-used approval path (`harness phase approve`) without weakening the rarely-used release path. The current flow forces users into a multi-step ritual — separate `approve-nonce mint` verb, 120-second TTL, two-terminal separation, HMAC concepts — none of which serve their actual workflow. The owner has explicitly downgraded the threat model for `phase.approve`: it is a **workflow speed bump**, not a cryptographic human-presence proof.

The release path (`harness release`, signed tags, OIDC CI trust, release_trust) is **out of scope** and retains its existing mechanisms.

---

## 2. Non-goals

- Touching `harness release`, `scripts/release.py`, `scripts/release_smoke_test.py`, `release_trust.py`, signed-tag verification, `verify_release_tag`, or `docs/trust/`.
- Touching `.github/workflows/release.yml` or OIDC CI paths.
- Building an "auto-yes" feature. The speed bump always asks.
- Removing autopilot. Autopilot remains an orthogonal feature.
- Cryptographic guarantees on `phase.approve`. PTY-driving agents can defeat `[y/N]` — accepted.

---

## 3. Threat model reset (phase.approve only)

- A user with shell access is trusted.
- An agent that the user runs in their own TTY is trusted to the extent the user trusts it. The harness does not cryptographically verify the human at the keyboard.
- Non-TTY subprocess (no allocated tty, no inherited stdin) cannot proceed past `phase approve`. This is the only defended boundary.
- All other approval defenses (HMAC nonce, audience binding, minter/consumer TTY separation, TTL) are **release-path only**.

This is a **workflow speed bump**, not a security boundary. It exists to make accidental phase advances harder, not to attest provenance.

---

## 4. Behavioral spec

### 4.1 `harness phase approve`

| Condition | Behavior |
|-----------|----------|
| `sys.stdin.isatty() == True`, user types `y` or `Y` and Enter | Approval stamped on current phase. **No automatic phase advance.** `phase set <next>` remains the explicit advance command. Audit row appended. Exit 0. |
| TTY, user types `N`, `n`, empty Enter, anything else, or Ctrl+C | Halt. No state change. No audit row (cancel is not an event). Exit 0 (clean cancel). |
| `sys.stdin.isatty() == False` | Halt. No state change. Stderr message: `phase approve requires a terminal. Run this command yourself.` Exit code: `EXIT_HUMAN_CONFIRMATION_REQUIRED = 17` (new). |

**Prompt format** (stdout, single line, newline-terminated):

```
Approve current phase=<phase>? Type y to confirm, N to cancel [y/N]:
```

The prompt names the phase being stamped. It does NOT name a next phase, because approve does not advance. This avoids the autopilot-lite misread.

### 4.2 `harness approve-nonce mint`

- Verb retained for one release cycle (v0.9.0).
- `--audience phase.approve` → emits deprecation warning to stderr, performs no-op, exits 0. The phase.approve path no longer consumes nonces.
- `--audience release.*` → unchanged (release path is out of scope).
- v1.0.0: `--audience phase.approve` path removed entirely.

### 4.3 `phase.approve` consumer

- Remove nonce lookup, HMAC verification, audience matching, and consumer-tty check from the phase.approve handler.
- Remove `human_proof_*` reason codes from phase.approve exit paths. Replace with two reasons:
  - `non_tty_approval_blocked` → exit 18
  - `user_cancelled` → exit 0
- Release-path nonce verification logic stays in its own module.

### 4.4 Audit

- Append via existing `audit_append`. Chain stamping (`schema_version=2`, `seq`, `previous_entry_hash`, `entry_hash`) preserved unchanged.
- New row shape for phase.approve:
  - `verb`: `phase.approve`
  - `phase`: current phase
  - `proof_class`: `soft_tty` (new value; current values like `nonce` remain valid for release path)
  - `tty`: path of controlling tty
  - `response`: `y`
  - `actor`: existing actor field

Cancels are not logged.

### 4.5 Exit codes

| Code | Symbol | Meaning |
|------|--------|---------|
| 6 | `EXIT_WRONG_PHASE_FOR_VERB` | Existing meaning preserved. |
| 6 | `EXIT_NONCE_SIGNATURE_INVALID` | Retained for release-path nonce errors only. Internal alias of the same numeric value. |
| 17 | `EXIT_HUMAN_CONFIRMATION_REQUIRED` | **New symbol** at numeric 17 (already protocol-spec §3.4 "human action required"; existing `requires_human` autopilot halts also exit 17). `sub_reason: non_tty_approval_blocked` disambiguates from autopilot's `requires_human`. |

Tests asserting `exit 6 + human_proof_*` reason on phase.approve are rewritten to assert `exit 17 + non_tty_approval_blocked`.

---

## 5. Terminology audit and glossary

Current terms found across `docs/USER_MANUAL.md`, `README.md`, `docs/protocol-spec.md`, and adapter prompt templates:

| Current term | Where it leaks | Rename / decision |
|--------------|----------------|-------------------|
| `approve-nonce`, `approval nonce`, `Approve-Nonce` | USER_MANUAL §A4, §B1.1–B1.3, FAQ §C2.2, §B3, adapter templates | **Drop from phase.approve docs entirely.** Retain in release-path docs as "release confirmation token" with a parenthetical `(internally: approval nonce, HMAC-bound)`. |
| `human proof`, `human-proof`, `human_proof_*` | USER_MANUAL §B1.3, §A4, error strings, ADR | **Drop term.** No longer used for phase.approve. Release path uses "release confirmation". |
| `minter TTY` / `consumer TTY` | USER_MANUAL §A4 | **Drop from phase.approve docs.** Internal-only term for release path. |
| `audience` (as in `--audience phase.approve`) | CLI help, USER_MANUAL §A4 | **Drop from phase.approve.** Retain in release-path internal docs. |
| `HMAC` | USER_MANUAL §A4 | **Drop from user-facing docs.** Move to `docs/trust/` and protocol-spec only. |
| `TTL` | USER_MANUAL §A4, §B1 | **Drop from phase.approve docs.** Retain in release-path docs as "expiration window". |
| `BY_TRUST`, `HARNESS_BY_TRUST` | USER_MANUAL §C2.2 | Retained verbatim (release/CI scope, out of scope here). |
| `signed tag`, `trust root` | USER_MANUAL §A1 | Retained (out of scope). |
| `phase gate`, `phase-gate` | USER_MANUAL §1, protocol-spec | Retained. Core concept. |
| `autopilot` | USER_MANUAL §B3, §C1 | Retained. Add explicit boundary statement vs speed bump. |
| `provenance` (in approver-provenance ADR) | ADR title, USER_MANUAL FAQ | Retained in ADR. New ADR clarifies provenance is no longer claimed for phase.approve. |
| `halt` | USER_MANUAL §B, multiple | Retained. Already user-friendly. |
| `speed bump` / `방지턱` | **New term** | Added to glossary. Defines phase.approve's new role. |
| `환경 변수` / `environment variable` (in user-facing harness config tables) | USER_MANUAL §C env-var table, scattered `HARNESS_*` references | **Renamed to "하네스 설정 flag" / "harness flag" in user-facing docs.** Reason: OS env vars and harness-internal config knobs are conceptually different to users; calling them "환경 변수" makes new users think they must export shell vars before normal use. Implementation unchanged — `os.environ[...]` lookups remain. Doc relocation only. |

### 5.1 Glossary placement

Two glossaries — same content, two locations, to catch users wherever they enter:

1. **`README.md` § "Glossary / 용어"** — added near top, after the one-paragraph intro and before usage. ~10 entries. Short, link to USER_MANUAL for details.
2. **`docs/USER_MANUAL.md` § 0.4 "Glossary"** — same entries, slightly fuller, with cross-refs to the sections that use each term.

Glossary entries (final wording):

- **Speed bump (방지턱)** — A `[y/N]` prompt that asks before advancing. Not a security check. Cancellable. Used by `phase approve`.
- **Autopilot** — A mode that advances multiple phases without asking. Orthogonal to speed bump. Off by default.
- **Phase** — A workflow stage: `design`, `discuss`, `plan`, `execute`, `done`. Stamped by `phase approve`, advanced by `phase set`.
- **Phase gate** — The rule that certain commands only run in certain phases.
- **Halt** — The harness pauses and asks the user to take action. Not an error. Specific halts: non-TTY halt (run from a terminal), wrong-phase halt (use `phase set`), autopilot budget halt.
- **Audit log** — Append-only file at `.harness/audit.log` recording every phase change and approval. Chain-verified.
- **Release confirmation** — A typed token required by `harness release`. Separate from `phase approve`. (Internally backed by an HMAC nonce; the term "nonce" is not user-facing for this path.)
- **Approve-nonce** — Legacy term. `phase approve` no longer uses it. The `harness release` path still has an internal HMAC mechanism that users see as "release confirmation"; the word "nonce" is not user-facing for that path either. The CLI verb `approve-nonce mint` is deprecated for v0.9.0 (no-op + warning) and removed in v1.0.
- **Trust root** — A signed git tag verified at install/upgrade time. Release-path only.
- **BY_TRUST** — A CI-only harness flag for release automation. Release-path only. Normal users do not set this.
- **하네스 설정 flag (harness flag)** — Internal config knobs of the harness, set through OS env vars (e.g. `HARNESS_*`). Normal users never set these; they exist for tests, CI, and advanced overrides. See `docs/advanced/harness-flags.md`.

---

## 6. Doc restructure plan

### 6.1 USER_MANUAL.md changes

| Section | Action |
|---------|--------|
| §0 Quick overview | Add 1-paragraph "Speed bump vs autopilot" boundary statement at §0.3. |
| §0.4 (new) Glossary | Added per §5.1 above. |
| §1 일상 워크플로우 | Update `phase approve` example: replace nonce-mint steps with `[y/N]` prompt. |
| §A4 Approve-Nonce | **Renamed**: "Release confirmation". Content scoped to release path only. All phase.approve references removed. |
| §B1.1 "approve-nonce mint requires interactive TTY" | Removed. Replaced with §B1.x "phase approve requires a terminal" entry. |
| §B1.2 (nonce flow misuse) | Removed. |
| §B1.3 nonce_signature_invalid | Scoped to release path only (release errors retained). |
| §B3 (autopilot human-required) | Updated: no longer says "run approve-nonce". Now says "run `phase approve` from your terminal". |
| §C2.2 FAQ "approve만으로 부족" | Rewritten: phase.approve is now sufficient on its own. Release path keeps its own confirmation. |
| Exit-code table | Add row for `17` `EXIT_HUMAN_CONFIRMATION_REQUIRED` (alongside existing `requires_human` row, since both share numeric 17 with sub_reason disambiguation). |
| Env-var table (current §C, "환경 변수") | **Section moved out of USER_MANUAL.** Replaced with a single sentence: "고급 설정 flag는 `docs/advanced/harness-flags.md` 참고. 일반 사용자는 건드릴 일 없음." `HARNESS_NONCE_DIR` row removed (phase.approve no longer uses it; if release path still uses it, that row stays in the advanced doc only). |

### 6.2 README.md changes

| Section | Action |
|---------|--------|
| New "Glossary / 용어" section | Added near top per §5.1. |
| `phase approve` mention | Update to describe `[y/N]` flow. |
| `approve-nonce mint` mention | Remove. |
| Release section | Unchanged. |

### 6.3 Adapter prompt template changes

- File: locate by grep `nonce` in `docs/use-cases/`, `docs/agents/`, and prompt template paths.
- Remove all `approve-nonce mint` instructions.
- Add line: `If the harness prints "[y/N]", do not answer it yourself. Stop and ask the user.`

### 6.4 New advanced doc

- **New file**: `docs/advanced/harness-flags.md`
- Contents: every `HARNESS_*` flag previously listed in USER_MANUAL §C env-var table, with intro:
  > 이 문서는 하네스 설정 flag(`HARNESS_*`) 목록입니다. 평소에는 건드리지 않습니다. 테스트, CI, 디버깅, 또는 명시적인 override가 필요한 경우에만 사용합니다.
- Each entry retains the same row shape (name, value type, purpose, scope).
- `phase.approve`-only flags (none remain after this change) are not listed.
- Release-path flags (e.g. `HARNESS_BY_TRUST`, `HARNESS_NONCE_DIR` if release uses it, `HARNESS_FIXED_NOW_ISO`, etc.) are listed.
- **Code unchanged**: still `os.environ[...]` lookups. Doc relocation + section title rename only.

### 6.5 ADR

- New ADR: `docs/adr/2026-05-19-phase-approve-speed-bump.md`.
- Records: threat-model downgrade scoped to phase.approve, explicit non-supersedence of release-path provenance claims in the 2026-05-17 ADR, decision to expose `[y/N]` as the user contract.
- The 2026-05-17 ADR is **not deleted**. A "Status / Supersession" footer on it points to the new ADR for phase.approve scope.

---

## 7. Migration

- `approve-nonce mint --audience phase.approve` keeps working as a no-op + warn for v0.9.0; removed in v1.0.
- Existing `~/.harness/approval-nonces/` directory untouched (release path uses it).
- Existing `audit.log` entries with `nonce_id` fields readable unchanged. Chain verifier untouched.
- `state_repair` flow: remove any check that errors on missing `phase.approve` nonce reference. Release-path repair checks retained.
- Tests:
  - `tests/phase_approve/test_approval_nonce.py` and related nonce-coupled phase.approve tests **deleted**, replaced with TTY-prompt tests.
  - Negative-path coverage rewritten to assert exit 18 + non_tty_approval_blocked.
  - `tests/audit/test_chain_verifier.py`, `test_rotation_seam.py`: unchanged (chain logic preserved).

---

## 8. Internal contradictions self-check

1. **"Internal nonce allowed" vs "nonce removed"** (round 2 Codex LOW) — Resolved: nonce is entirely removed from `phase.approve` code path and user surface. Nonce concept retained in release path only. No internal nonce remains for `phase.approve`.
2. **Audit chain "no cryptographic chain" wording** (round 2 subagent HIGH-3) — Removed from earlier draft. This spec uses existing chain unchanged.
3. **Exit code 6 reuse for new non-TTY halt** (round 2 subagent HIGH-4) — Resolved: new code 18 added; 6 keeps its meaning.
4. **`phase approve` stamp-vs-advance semantics** (round 2 Codex MED) — Resolved: stamp only. No advance. Doc and CLI behavior aligned with existing `phase set` for advance.
5. **`done` phase release-boundary** (round 2 subagent MED-2) — Out of scope. Release path untouched.
6. **`_release_gate` single chokepoint** (round 1 + round 2 BLOCKER) — Out of scope. Release path untouched.
7. **typed-token expect-defense overclaim** (round 2 HIGH-1) — Out of scope. Release path untouched.
8. **OIDC / signed-tag removal cascade** (round 2 BLOCKER) — Out of scope. Both retained.

---

## 9. Acceptance criteria

- `harness phase approve` from a TTY → prints prompt → on `y` → audit row written → command exits 0. Verified by new integration test.
- `harness phase approve` non-TTY → exits 18 with stderr message. Verified by new test.
- `harness approve-nonce mint --audience phase.approve` → stderr deprecation warning, exits 0 no-op. Verified by test.
- `harness approve-nonce mint --audience release.*` → unchanged behavior. Existing release tests still pass.
- No occurrence of the word `nonce` in user-facing strings emitted on the `phase approve` code path. Verified by `grep` in tests.
- USER_MANUAL §0.4 glossary entry exists. Verified by anchor check (existing anchor-missing infra).
- README glossary section exists. Verified by anchor check.
- `docs/advanced/harness-flags.md` exists and lists every `HARNESS_*` flag present in the codebase. Verified by `grep -rEo 'HARNESS_[A-Z_]+' harness/ scripts/ | sort -u` vs flag list in the doc.
- USER_MANUAL no longer contains an `HARNESS_*` table. Verified by grep.
- `verify_release_tag`, `release_trust`, `release.py`, `release_smoke_test.py`, `.github/workflows/release.yml` byte-identical before and after this change (excluding doc-only edits).

---

## 10. Open questions

None at this time. Owner has confirmed scope and trade-offs across two adversarial review rounds.
