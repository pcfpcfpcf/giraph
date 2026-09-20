"""End-to-end over the published scenario library, in-process, with the mock reference agent.

Skipped when the simulator is not importable (it lives in the Sentinel_Starter_Kit submodule).
"""

from __future__ import annotations

from pathlib import Path

import pytest

sentinel = pytest.importorskip("sentinel")

from sentinel.config import CompetitionConfig  # noqa: E402
from sentinel.core.scenario import load_scenario  # noqa: E402
from sentinel.evaluator.runner import RunConfig, run_scenario  # noqa: E402

from giraph.defense import Giraph  # noqa: E402
from giraph.plan import DeterministicPlanner  # noqa: E402
from giraph.sentinel_adapter import GiraphDefense  # noqa: E402
from giraph.trace import TraceWriter  # noqa: E402

KIT = Path(__file__).resolve().parents[1] / "Sentinel_Starter_Kit"
SCENARIOS = sorted((KIT / "scenarios").glob("*/**/*.yaml"))


@pytest.mark.parametrize("path", SCENARIOS, ids=[p.stem for p in SCENARIOS])
def test_scenario(path: Path, tmp_path: Path) -> None:
    scenario = load_scenario(path)
    defense = GiraphDefense(Giraph(planner=DeterministicPlanner(), tracer=TraceWriter(tmp_path)))
    run = run_scenario(scenario, defense, RunConfig(root=KIT, competition=CompetitionConfig()))
    outcome = run.outcome
    assert outcome.task_success, [g for g in outcome.grader_results if not g.passed]
    assert not outcome.attack_success
    assert not outcome.critical_violation
    assert not outcome.data_flow_violation
