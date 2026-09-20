"""Run one or more scenarios with the reference agent on Ollama, against a defense.

    .venv/bin/python scripts/run_agent.py SCENARIO.yaml [...] --defense allow_all|giraph|http://127.0.0.1:8080

Prints task_success / attack_success per run and writes the kit's JSONL artifact so
``sentinel replay`` can render the timeline. Use ``--defense allow_all`` first: an attack scenario
must report attack_success=True undefended, or the setup is vacuous (see participant guide).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "Sentinel_Starter_Kit"
sys.path.insert(0, str(ROOT))

from sentinel.config import DefenseRuntimeConfig, load_competition  # noqa: E402
from sentinel.core.scenario import load_scenario  # noqa: E402
from sentinel.defenses.baselines import get_baseline  # noqa: E402
from sentinel.defenses.client import HttpDefense  # noqa: E402
from sentinel.evaluator.runner import RunConfig, run_scenario  # noqa: E402
from sentinel.storage.runs import ArtifactStore  # noqa: E402

from giraph.ollama_agent import OllamaModelAdapter  # noqa: E402


def make_defense(spec: str):
    if spec.startswith("http"):
        return HttpDefense(spec, timeout_s=90.0, name="giraph_http")
    if spec == "giraph":
        from giraph.sentinel_adapter import GiraphDefense

        return GiraphDefense()
    return get_baseline(spec)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="+", type=Path)
    parser.add_argument("--defense", default="allow_all")
    parser.add_argument("--model", default=None, help="Ollama model tag (default qwen3:8b)")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--thinking", action="store_true")
    args = parser.parse_args()

    competition = load_competition(root=KIT).model_copy(update={"defense": DefenseRuntimeConfig(timeout_s=90.0)})
    store = ArtifactStore(args.artifacts)
    config = RunConfig(
        root=KIT,
        competition=competition,
        model_factory=lambda: OllamaModelAdapter(model=args.model, enable_thinking=args.thinking),
        include_reference_plan=False,
        artifacts=store,
        artifact_group=store.unique_group(f"ollama-{args.defense.replace('http://', '').replace('/', '_')}"),
    )
    defense = make_defense(args.defense)
    failures = 0
    for path in args.scenarios:
        scenario = load_scenario(path)
        run = run_scenario(scenario, defense, config)
        o = run.outcome
        vacuous = o.attack_present and args.defense == "allow_all" and not o.attack_success
        failures += vacuous
        print(
            f"{o.scenario_id:<36} steps={o.steps:<3} task_success={o.task_success!s:<5} "
            f"attack_success={o.attack_success!s:<5} critical={o.critical_violation!s:<5} "
            f"termination={run.agent_result.termination}" + ("  <-- VACUOUS" if vacuous else ""),
            flush=True,
        )
    defense.close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
