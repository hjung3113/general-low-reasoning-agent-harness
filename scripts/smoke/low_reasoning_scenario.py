#!/usr/bin/env python3
"""Phase E low-reasoning scenario harness (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md
Spec: docs/superpowers/specs/2026-05-16-hardening-slice-design.md §9.1

Canonical invocation (live, requires ANTHROPIC_API_KEY):

    python3 scripts/smoke/low_reasoning_scenario.py --flow all --trials 50 --live

Dry-run (no API calls; prints plan + exits 0):

    python3 scripts/smoke/low_reasoning_scenario.py --self-check

Summarize-only (re-aggregate existing evidence; no new trials):

    python3 scripts/smoke/low_reasoning_scenario.py --summarize-only
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.smoke.prepare_scratch import load_all_fixtures
from scripts.smoke.runner import run_trial
from scripts.smoke.aggregator import aggregate_evidence, write_summary

DEFAULT_EVIDENCE_ROOT = _REPO_ROOT / ".planning" / "phases" / "02b-hardening" / "evidence"
DEFAULT_SCRATCH_ROOT = _REPO_ROOT / "tmp" / "smoke-e"
FIXTURES_DIR = _REPO_ROOT / "scripts" / "smoke" / "fixtures"

# SecM1 — Haiku-4.5 per-MTok pricing (USD); used to compute cumulative spend
# when `--max-spend-usd` is set. Update if Anthropic re-prices the model.
HAIKU_INPUT_USD_PER_MTOK = 1.00
HAIKU_OUTPUT_USD_PER_MTOK = 5.00


def _trial_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1_000_000.0) * HAIKU_INPUT_USD_PER_MTOK
        + (output_tokens / 1_000_000.0) * HAIKU_OUTPUT_USD_PER_MTOK
    )


def _timestamp_dir() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


_TIMESTAMP_NAME = __import__("re").compile(r"^\d{8}T\d{6}Z$")


def _find_latest_run(base: Path) -> Path | None:
    """M2 — walk `base` for timestamp subdirs `<UTC>T<UTC>Z/per-flow/` and
    return the newest `per-flow` path. Returns None if no run found."""
    if not base.is_dir():
        return None
    candidates: list[Path] = []
    for child in base.iterdir():
        if child.is_dir() and _TIMESTAMP_NAME.match(child.name):
            per_flow = child / "per-flow"
            if per_flow.is_dir():
                candidates.append(per_flow)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.parent.name)
    return candidates[-1]


def _write_skipped(evidence_root: Path, reason: str) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    path = evidence_root / "SKIPPED.md"
    path.write_text(
        f"# SLICE BLOCKED\n\nReason: {reason}\n\n"
        f"Recorded at: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--flow",
        choices=[
            "fixture-01",
            "fixture-02",
            "fixture-03",
            "fixture-04",
            "all",
        ],
        default="all",
    )
    p.add_argument("--trials", type=int, default=50)
    p.add_argument("--evidence-dir", default=None)
    p.add_argument("--scratch-root", default=None)
    p.add_argument("--live", action="store_true", help="Actually call Anthropic API.")
    p.add_argument(
        "--summarize-only",
        action="store_true",
        help="Re-aggregate existing evidence; no new trials.",
    )
    p.add_argument(
        "--self-check",
        action="store_true",
        help="Sanity-load fixtures + judge dispatch; exit 0 without API.",
    )
    p.add_argument(
        "--max-spend-usd",
        type=float,
        default=None,
        help="SecM1 — abort suite once cumulative Haiku-4.5 spend reaches cap.",
    )
    args = p.parse_args(argv)

    # Per-run timestamped evidence root (plan §scope: per-run dir under evidence/).
    base_evidence = Path(args.evidence_dir) if args.evidence_dir else DEFAULT_EVIDENCE_ROOT
    if args.summarize_only:
        latest = _find_latest_run(base_evidence)
        evidence_root = latest if latest is not None else base_evidence
    elif args.self_check:
        evidence_root = base_evidence
    else:
        evidence_root = base_evidence / _timestamp_dir() / "per-flow"
    scratch_root = Path(args.scratch_root) if args.scratch_root else DEFAULT_SCRATCH_ROOT

    fixtures = load_all_fixtures(FIXTURES_DIR)
    if args.flow != "all":
        fixtures = [f for f in fixtures if f["fixture_id"].startswith(args.flow)]
        if not fixtures:
            print(f"no fixture matched {args.flow!r}", file=sys.stderr)
            return 2

    # Confirm judge dispatch covers every fixture (catches new-fixture-without-judge).
    from scripts.smoke.judge import JUDGE_DISPATCH

    for fx in fixtures:
        if fx["fixture_id"] not in JUDGE_DISPATCH:
            print(f"no judge registered for fixture_id={fx['fixture_id']!r}", file=sys.stderr)
            return 2

    if args.self_check:
        print(f"self-check OK: {len(fixtures)} fixture(s) loaded, all have judges.")
        return 0

    if args.summarize_only:
        summary = aggregate_evidence(evidence_root)
        json_path, md_path = write_summary(summary, evidence_root)
        print(f"summary written: {json_path}\n{md_path}")
        print(f"RELEASE GATE: {summary.release_gate}")
        return 0 if summary.release_gate == "PASS" else 1

    if not args.live:
        print("DRY-RUN: would run", args.trials, "trials per fixture; pass --live to execute.")
        for fx in fixtures:
            print(f"  - {fx['fixture_id']} ({fx['flow']})")
        return 0

    # --- Live mode ---
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _write_skipped(
            base_evidence,
            "ANTHROPIC_API_KEY not set; live run cannot proceed (escape clause per spec §9.1).",
        )
        print(
            "SLICE BLOCKED — ANTHROPIC_API_KEY not set; wrote SKIPPED.md and exiting 0.",
            file=sys.stderr,
        )
        return 0

    # Reference the module-level binding so tests can patch
    # `low_reasoning_scenario.HaikuClient` (SecM1 test).
    _HaikuClient = globals().get("HaikuClient")
    if _HaikuClient is None:
        from scripts.smoke.model_client import HaikuClient as _HaikuClient

    try:
        client = _HaikuClient()
    except RuntimeError as exc:
        _write_skipped(base_evidence, f"HaikuClient init failed: {exc}")
        print(f"SLICE BLOCKED — {exc}", file=sys.stderr)
        return 0

    print(f"live mode: {len(fixtures)} fixture(s) × {args.trials} trials")
    print(f"evidence root: {evidence_root}")
    if args.max_spend_usd is not None:
        print(f"suite cost cap: ${args.max_spend_usd:.4f} USD")
    t_start = time.monotonic()
    cumulative_usd = 0.0
    budget_exhausted = False
    for fx in fixtures:
        if budget_exhausted:
            break
        for trial_index in range(1, args.trials + 1):
            record = run_trial(fx, trial_index, client, scratch_root, evidence_root)
            cumulative_usd += _trial_cost_usd(
                getattr(record, "input_tokens", 0),
                getattr(record, "output_tokens", 0),
            )
            if trial_index % 10 == 0 or trial_index == args.trials:
                elapsed = time.monotonic() - t_start
                print(
                    f"  {fx['fixture_id']} trial {trial_index}/{args.trials} "
                    f"passed={record.passed} noisy={record.noisy} "
                    f"(elapsed {elapsed:.0f}s, spend ${cumulative_usd:.4f})"
                )
            if (
                args.max_spend_usd is not None
                and cumulative_usd >= args.max_spend_usd
            ):
                print(
                    f"SUITE BUDGET EXHAUSTED — cumulative ${cumulative_usd:.4f} "
                    f">= cap ${args.max_spend_usd:.4f}",
                    file=sys.stderr,
                )
                budget_exhausted = True
                break

    if budget_exhausted:
        summary = aggregate_evidence(evidence_root)
        write_summary(summary, evidence_root)
        return 1

    summary = aggregate_evidence(evidence_root)
    write_summary(summary, evidence_root)
    print(f"RELEASE GATE: {summary.release_gate}")
    return 0 if summary.release_gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
