"""Per-flow aggregator and release-gate summary writer (02b-10).

Plan: .planning/phases/02b-hardening/plans/02b-10-PHASE-E-HARNESS-PLAN.md §6.5.

Reads every `trial-*.json` under `<evidence_root>/<flow>/`, computes pass
rate per flow, decides the release gate (≥80% per flow), and writes
`SUMMARY.json` + `SUMMARY.md` at the evidence root.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

PASS_THRESHOLD = 0.80
TRIALS_PER_FLOW = 50  # informational; aggregator computes from actual files


@dataclass
class FlowSummary:
    flow: str
    passed: int
    total: int
    noisy_count: int
    pass_rate: float
    gate_passed: bool
    gate_reason: str


@dataclass
class Summary:
    flows: list[FlowSummary] = field(default_factory=list)
    release_gate: str = "BLOCKED"
    blocking_flows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "flows": [asdict(f) for f in self.flows],
            "release_gate": self.release_gate,
            "blocking_flows": list(self.blocking_flows),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    def to_markdown(self) -> str:
        rows = [
            "# Phase E Low-Reasoning Release Gate",
            "",
            "| Flow | Pass | Total | Rate | Noisy | Gate |",
            "|---|---|---|---|---|---|",
        ]
        for fl in self.flows:
            pct = f"{fl.pass_rate * 100:.0f}%"
            verdict = "PASS" if fl.gate_passed else "BLOCKED"
            rows.append(
                f"| {fl.flow} | {fl.passed} | {fl.total} | {pct} | {fl.noisy_count} | {verdict} |"
            )
        rows.append("")
        rows.append(f"**RELEASE GATE: {self.release_gate}**")
        if self.blocking_flows:
            rows.append("")
            rows.append("Blocking flows: " + ", ".join(self.blocking_flows))
        rows.append("")
        return "\n".join(rows)


def _load_trial_records(flow_dir: Path) -> list[dict]:
    records = []
    for path in sorted(flow_dir.glob("trial-*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records


def aggregate_evidence(evidence_root: Path) -> Summary:
    root = Path(evidence_root)
    summary = Summary()
    if not root.is_dir():
        return summary
    for flow_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        records = _load_trial_records(flow_dir)
        if not records:
            continue
        total = len(records)
        passed = sum(1 for r in records if r.get("passed"))
        noisy = sum(1 for r in records if r.get("noisy"))
        rate = passed / total if total else 0.0
        gate_passed = rate >= PASS_THRESHOLD
        gate_reason = (
            f"{passed}/{total} ≥ {int(PASS_THRESHOLD * total)}/{total} threshold"
            if gate_passed
            else f"{passed}/{total} below {int(PASS_THRESHOLD * total)}/{total} threshold"
        )
        summary.flows.append(
            FlowSummary(
                flow=flow_dir.name,
                passed=passed,
                total=total,
                noisy_count=noisy,
                pass_rate=rate,
                gate_passed=gate_passed,
                gate_reason=gate_reason,
            )
        )
    summary.blocking_flows = [f.flow for f in summary.flows if not f.gate_passed]
    summary.release_gate = "PASS" if (summary.flows and not summary.blocking_flows) else "BLOCKED"
    return summary


def write_summary(summary: Summary, evidence_root: Path) -> tuple[Path, Path]:
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "SUMMARY.json"
    md_path = root / "SUMMARY.md"
    json_path.write_text(summary.to_json(), encoding="utf-8")
    md_path.write_text(summary.to_markdown(), encoding="utf-8")
    return (json_path, md_path)
