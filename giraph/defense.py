"""GIRAPH as one object: plan once per (run, turn), then monitor every action against that graph."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from giraph.envelope import Authority
from giraph.monitor import check
from giraph.plan import Obligation, PlanGraph, Planner, planner_from_env

# Ablations, for the report only. GIRAPH_ABLATE=no_planner,no_authority,no_rewrite
#   no_planner   the request is not read: every allowed tool's effect enters the envelope
#   no_authority values are never traced: everything looks agent-authored
#   no_rewrite   the safe subplan is never offered
ABLATIONS = frozenset({"no_planner", "no_authority", "no_rewrite"})
from giraph.schema import DefenseDecision, DefenseRequest
from giraph.trace import TraceWriter, record
from giraph.verdict import verdict


class Giraph:
    name = "giraph"

    def __init__(self, planner: Planner | None = None, tracer: TraceWriter | None = None, ablate: set[str] | None = None) -> None:
        self.planner = planner or planner_from_env()
        self.tracer = tracer or TraceWriter()
        self.ablate = set(ablate if ablate is not None else filter(None, os.environ.get("GIRAPH_ABLATE", "").split(",")))
        unknown = self.ablate - ABLATIONS
        if unknown:
            raise ValueError(f"unknown ablation(s): {sorted(unknown)}")
        if "no_planner" in self.ablate:
            from giraph.plan import PermissivePlanner

            self.planner = PermissivePlanner()
        self._graphs: dict[tuple[str, int], PlanGraph] = {}
        self._lock = threading.Lock()

    def graph_for(self, request: DefenseRequest) -> PlanGraph:
        """The plan is built from the request and policy only, the first time this task is seen.

        A new turn is a new trusted request, so it gets its own graph. The graph is frozen; later
        calls with the same key read the cached instance and never rebuild it from observed content.
        """
        key = (request.run_id, request.history_digest.turn_index)
        with self._lock:
            graph = self._graphs.get(key)
            if graph is None:
                graph = self.planner.plan(request.user_goal, request.policy_context)
                self._graphs[key] = graph
            return graph

    def decide(self, request: DefenseRequest) -> DefenseDecision:
        started = time.perf_counter()
        graph = self.graph_for(request)
        result = check(graph, request)
        if "no_authority" in self.ablate:
            result = result.model_copy(update={
                "authority": Authority.AGENT, "mirrored": False, "authority_evidence": "ablated",
                "violated": tuple(o for o in result.violated if o is not Obligation.TRUSTED_AUTHORITY),
            })
        if "no_rewrite" in self.ablate:
            result = result.model_copy(update={"pruned": None})
        decision = verdict(result, request.candidate_action)
        decision = decision.model_copy(update={"metadata": {
            "node": result.node_id, "effect": result.effect.value if result.effect else None,
            "divergence": result.divergence.value, "authority": result.authority.value,
        }})
        self.tracer.write(record(request, graph, result, decision, (time.perf_counter() - started) * 1000))
        return decision

    def graphs(self) -> dict[str, Any]:
        with self._lock:
            return {f"{run}#{turn}": g.to_json() for (run, turn), g in self._graphs.items()}
