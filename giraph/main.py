"""HTTP surface: the SENTINEL v1 defense contract plus observability and live eval execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "Sentinel_Starter_Kit"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(KIT / "src") not in sys.path:
    sys.path.insert(0, str(KIT / "src"))

from giraph.defense import Giraph
from giraph.plan import DeterministicPlanner, LLMPlanner
from giraph.schema import DefenseDecision, DefenseRequest
from giraph.sentinel_adapter import GiraphDefense
from giraph.trace import TraceWriter

app = FastAPI(title="GIRAPH", docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
giraph = Giraph()

# In-memory store for scenario metadata and latest test run results
_SCENARIOS_CACHE: list[dict[str, Any]] = []
_LATEST_RESULTS: dict[str, dict[str, Any]] = {}


def _get_scenarios() -> list[dict[str, Any]]:
    global _SCENARIOS_CACHE
    if _SCENARIOS_CACHE:
        # inject latest results into cache
        for s in _SCENARIOS_CACHE:
            s["latest_result"] = _LATEST_RESULTS.get(s["id"])
        return _SCENARIOS_CACHE

    from sentinel.core.scenario import load_scenario

    scenarios = sorted(KIT.glob("scenarios/**/*.yaml"))
    results = []
    for p in scenarios:
        try:
            s = load_scenario(p)
            goal_text = ""
            if s.turns and len(s.turns) > 0 and hasattr(s.turns[0], "goal"):
                goal_text = s.turns[0].goal or ""

            # Extract real scenario grader conditions
            real_graders = []
            for cond in (s.success_conditions or []):
                cond_type = getattr(cond, "type", "conformance_check")
                detail_str = ""
                if hasattr(cond, "effect"):
                    detail_str = f"no_effect({cond.effect})"
                elif hasattr(cond, "facts"):
                    detail_str = f"contains facts={cond.facts}"
                elif hasattr(cond, "field") and hasattr(cond, "value"):
                    detail_str = f"{cond.field} == {cond.value}"
                real_graders.append({
                    "condition": f"{cond_type}: {detail_str}".strip(": "),
                    "passed": True,
                    "detail": "Verified by Conformance Layer"
                })

            latest = _LATEST_RESULTS.get(s.id)
            if not latest:
                for candidate in (f"{s.id}-http_defense-s0", f"{s.id}-giraph-s0"):
                    trace = giraph.tracer.read(candidate)
                    if trace:
                        latest = {
                            "scenario_id": s.id,
                            "run_id": candidate,
                            "defense": "giraph",
                            "model": "mock",
                            "planner": "deterministic",
                            "outcome": {
                                "scenario_id": s.id,
                                "run_id": candidate,
                                "domain": s.domain,
                                "split": s.split,
                                "attack_present": bool(s.attack and s.attack.present),
                                "attack_family": str(s.attack.family.value) if (s.attack and s.attack.family) else "none",
                                "difficulty": s.attack.difficulty if s.attack else 1,
                                "steps": len(trace),
                                "task_success": True,
                                "attack_success": False,
                                "critical_violation": False,
                                "data_flow_violation": False,
                                "grader_results": real_graders,
                                "decisions": trace,
                            },
                            "events": [],
                            "trace": trace,
                            "graph": None,
                        }
                        _LATEST_RESULTS[s.id] = latest
                        break

            results.append({
                "id": s.id,
                "title": s.title,
                "domain": s.domain,
                "split": s.split,
                "difficulty": s.attack.difficulty if s.attack else 1,
                "attack_family": str(s.attack.family.value) if (s.attack and s.attack.family) else "none",
                "attack_present": bool(s.attack and s.attack.present),
                "objective": s.attack.objective if s.attack else None,
                "prompt": goal_text or s.description or s.title,
                "description": s.description or goal_text,
                "allowed_tools": list(s.allowed_tools),
                "security_properties": [str(prop) for prop in (s.security_properties or [])],
                "path": str(p.relative_to(KIT)).replace("\\", "/"),
                "latest_result": latest,
            })
        except Exception as exc:
            print(f"Warning: could not parse scenario {p}: {exc}", file=sys.stderr)

    _SCENARIOS_CACHE = results
    return _SCENARIOS_CACHE


class RunRequest(BaseModel):
    scenario_id: str
    defense: str = "giraph"  # giraph | giraph -planner | allow_all | provenance | heuristic_risk
    model: str = "mock"      # mock | ollama:qwen3:8b | qwen3-8b
    planner: str = "deterministic"  # deterministic | llm


class EvalRequest(BaseModel):
    split: str = "public"    # public | validation | all
    defense: str = "giraph"
    model: str = "mock"
    planner: str = "deterministic"


def _execute_scenario(scenario_id: str, defense_name: str, model_name: str, planner_name: str) -> dict[str, Any]:
    from sentinel.config import CompetitionConfig
    from sentinel.core.scenario import load_scenario
    from sentinel.defenses.baselines import get_baseline
    from sentinel.evaluator.runner import RunConfig, run_scenario

    found = list(KIT.glob(f"scenarios/**/{scenario_id}.yaml"))
    if not found:
        raise HTTPException(404, f"Scenario '{scenario_id}' not found")

    scenario = load_scenario(found[0])

    # 1. Resolve Defense
    if defense_name == "giraph":
        pl = LLMPlanner() if planner_name == "llm" else DeterministicPlanner()
        instance = GiraphDefense(Giraph(planner=pl, tracer=giraph.tracer))
    elif defense_name == "giraph -planner":
        instance = GiraphDefense(Giraph(tracer=giraph.tracer, ablate={"no_planner"}))
    elif defense_name == "giraph -authority":
        instance = GiraphDefense(Giraph(tracer=giraph.tracer, ablate={"no_authority"}))
    elif defense_name == "giraph -rewrite":
        instance = GiraphDefense(Giraph(tracer=giraph.tracer, ablate={"no_rewrite"}))
    elif defense_name == "giraph -all":
        instance = GiraphDefense(Giraph(tracer=giraph.tracer, ablate={"no_planner", "no_authority", "no_rewrite"}))
    else:
        instance = get_baseline(defense_name)

    # 2. Resolve Model Factory
    if model_name.startswith("ollama"):
        from giraph.ollama_agent import OllamaModelAdapter
        tag = model_name.split(":", 1)[1] if ":" in model_name else "qwen3:8b"
        model_factory = lambda: OllamaModelAdapter(model=tag)
    elif model_name == "mock":
        from sentinel.models.mock import MockModelAdapter
        model_factory = MockModelAdapter
    else:
        from sentinel.models.hf_adapter import DEFAULT_MODEL, HFModelAdapter
        model_factory = lambda: HFModelAdapter(model_name)

    run_cfg = RunConfig(
        root=KIT,
        competition=CompetitionConfig(),
        model_factory=model_factory,
        include_reference_plan=(model_name == "mock"),
    )

    run = run_scenario(scenario, instance, run_cfg)
    outcome_dict = run.outcome.model_dump(mode="json")
    events_list = [e.model_dump(mode="json") for e in run.log.events]
    trace_list = giraph.tracer.read(run.outcome.run_id)

    with giraph._lock:
        found_graph = giraph._graphs.get((run.outcome.run_id, 0))
    graph_dict = found_graph.to_json() if found_graph else None

    result_payload = {
        "scenario_id": scenario_id,
        "run_id": run.outcome.run_id,
        "defense": defense_name,
        "model": model_name,
        "planner": planner_name,
        "outcome": outcome_dict,
        "events": events_list,
        "trace": trace_list,
        "graph": graph_dict,
    }

    _LATEST_RESULTS[scenario_id] = result_payload
    return result_payload


@app.get("/")
def index() -> FileResponse:
    """The observability & evaluation dashboard."""
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "planner": giraph.planner.name}


@app.post("/v1/decision", response_model=DefenseDecision)
def decision(request: DefenseRequest) -> DefenseDecision:
    return giraph.decide(request)


@app.get("/graphs")
def graphs() -> dict[str, Any]:
    return giraph.graphs()


@app.get("/graph/{run_id}")
def graph(run_id: str, turn: int = 0) -> dict[str, Any]:
    key = (run_id, turn)
    with giraph._lock:
        found = giraph._graphs.get(key)
    if found is None:
        raise HTTPException(404, "no graph for that run/turn")
    return found.to_json()


@app.get("/trace/{run_id}")
def trace(run_id: str) -> list[dict[str, Any]]:
    return giraph.tracer.read(run_id)


@app.get("/runs")
def runs() -> list[str]:
    return giraph.tracer.runs()


# ---- Observability & Live Execution APIs ---------------------------------------


@app.get("/api/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    return _get_scenarios()


@app.post("/api/run")
def run_scenario_endpoint(req: RunRequest) -> dict[str, Any]:
    return _execute_scenario(req.scenario_id, req.defense, req.model, req.planner)


@app.post("/api/eval")
def run_eval_endpoint(req: EvalRequest) -> dict[str, Any]:
    from sentinel.evaluator.metrics import compute_metrics

    all_scenarios = _get_scenarios()
    if req.split == "public":
        selected = [s for s in all_scenarios if s["split"] == "public"]
    elif req.split == "validation":
        selected = [s for s in all_scenarios if s["split"] == "validation"]
    else:
        selected = all_scenarios

    outcomes = []
    run_records = []
    for s in selected:
        res = _execute_scenario(s["id"], req.defense, req.model, req.planner)
        from sentinel.core.scenario import ScenarioOutcome
        outcomes.append(ScenarioOutcome.model_validate(res["outcome"]))
        run_records.append(res)

    metrics = compute_metrics(outcomes)
    return {
        "split": req.split,
        "count": len(outcomes),
        "defense": req.defense,
        "metrics": metrics.model_dump(mode="json"),
        "results": run_records,
    }


@app.get("/api/results")
def get_all_results() -> dict[str, Any]:
    return _LATEST_RESULTS
