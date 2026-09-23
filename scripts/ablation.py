"""Ablation table over the public scenarios with the mock reference agent (in-process, no HTTP).

    Sentinel_Starter_Kit/.venv/bin/python scripts/ablation.py [--json out.json]

Configurations: full GIRAPH, each ablation alone, all three together, redaction switched off, and the
kit's baselines.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "Sentinel_Starter_Kit"
sys.path.insert(0, str(ROOT))

from sentinel.config import CompetitionConfig  # noqa: E402
from sentinel.core.scenario import load_scenario  # noqa: E402
from sentinel.defenses.baselines import get_baseline  # noqa: E402
from sentinel.evaluator.metrics import compute_metrics  # noqa: E402
from sentinel.evaluator.runner import RunConfig, run_scenario  # noqa: E402

import giraph.monitor  # noqa: E402
from giraph.defense import Giraph  # noqa: E402
from giraph.plan import DeterministicPlanner  # noqa: E402
from giraph.sentinel_adapter import GiraphDefense  # noqa: E402
from giraph.trace import TraceWriter  # noqa: E402

CONFIGS: dict[str, set[str] | str] = {
    "giraph": set(),
    "giraph -planner": {"no_planner"},
    "giraph -authority": {"no_authority"},
    "giraph -rewrite": {"no_rewrite"},
    "giraph -all": {"no_planner", "no_authority", "no_rewrite"},
    "giraph -redaction": {"no_redaction"},
    "giraph -redaction -authority": {"no_redaction", "no_authority"},
    "baseline provenance": "provenance",
    "baseline heuristic_risk": "heuristic_risk",
    "baseline allow_all": "allow_all",
}


def evaluate(name: str, spec: set[str] | str, scenarios: list, tmp: Path) -> dict:
    # Redaction is not a runtime ablation: switching it off here means restricted content is never detected.
    no_redaction = isinstance(spec, set) and "no_redaction" in spec
    if no_redaction:
        spec = spec - {"no_redaction"}
        redact, giraph.monitor.redact = giraph.monitor.redact, lambda text, restricted: (text, False)
    outcomes = []
    for scenario in scenarios:
        defense = (
            get_baseline(spec) if isinstance(spec, str)
            else GiraphDefense(Giraph(planner=DeterministicPlanner(), tracer=TraceWriter(tmp / name.replace(" ", "_")), ablate=set(spec)))
        )
        outcomes.append(run_scenario(scenario, defense, RunConfig(root=KIT, competition=CompetitionConfig())).outcome)
    if no_redaction:
        giraph.monitor.redact = redact
    m = compute_metrics(outcomes)
    decisions = [d for o in outcomes for d in o.decisions]
    illegit = [d for d in decisions if not d.legitimate and d.action_type == "tool_call"]
    mix = Counter(d.decision.value for d in illegit)
    return {
        "config": name,
        "ASR": m.asr, "BTU": m.btu, "CVR": m.cvr, "FBR": m.fbr, "UER": m.uer,
        "escalations": sum(1 for d in decisions if d.decision.value == "escalate"),
        "illegit_block": mix.get("block", 0), "illegit_escalate": mix.get("escalate", 0),
        "illegit_rewrite": mix.get("rewrite", 0), "illegit_allow": mix.get("allow", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path)
    parser.add_argument("--scenarios", type=Path, default=KIT / "scenarios" / "public")
    args = parser.parse_args()
    scenarios = [load_scenario(p) for p in sorted(args.scenarios.glob("**/*.yaml"))]
    tmp = ROOT / "artifacts" / "ablation-traces"
    rows = [evaluate(name, spec, scenarios, tmp) for name, spec in CONFIGS.items()]
    cols = ("ASR", "BTU", "CVR", "FBR", "UER", "escalations", "illegit_block", "illegit_escalate", "illegit_rewrite", "illegit_allow")
    print(f"{'config':<26}" + "".join(f"{c:>17}" for c in cols))
    for r in rows:
        print(f"{r['config']:<26}" + "".join(f"{(r[c] if r[c] is not None else float('nan')):>17.2f}" if isinstance(r[c], float) else f"{r[c]:>17}" for c in cols))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
