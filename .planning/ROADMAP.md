# Roadmap

## Phases

- [x] **Milestone 1: Security strip** - sec-1 ~ sec-7b: HMAC key, cli_deprecated, fs_fence, autopilot_guard, audit_verify_cli, SSH-signed tag verification, trust_origin, release_trust.
- [x] **Milestone 2: Minimal workflow strip** - items 1-5, 7, 8: state_migrate, verify_adrs_accepted, scripts/smoke/, smoke_lifecycle, audit_chain verify/walk, autopilot/budget/halt-diary, infra hygiene.
- [x] **Milestone 3: Post-strip coherence** - items 1-5: failing-test repair + trust_origin residue strip (ADR-0002 alignment) + profile audit (no cull) + target_smoke_test usage check (live) + manifest/skeleton sweep (clean). -113 LOC.
- [ ] **Milestone 4: Audit + state-trust strip** - ADR-0004/0005: delete audit_chain.py, simplify audit.py to JSONL, strip state_trust.py, trim phase_txn recovery.
- [ ] **Milestone 5: Approval simplification** - G6 grill: trim phase_approve identity (687 → ~300 LOC); replace approver allowlist with first-run TTY confirm.
- [ ] **Milestone 6: Artifact contract** - G7: docs/ARTIFACTS.md generated from manifest; graveyard for removed artifacts; UX diff print on managed-block conflict.
- [ ] **Milestone 7: skill-pack audit** - G1: audit 18 packs for usage; cull unused.
