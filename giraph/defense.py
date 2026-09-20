"""GIRAPH as one object: plan once per (run, turn), then monitor every action against that graph."""

from __future__ import annotations

import threading
import time
from typing import Any

from giraph.monitor import check
from giraph.plan import PlanGraph, Planner, planner_from_env
from giraph.schema import DefenseDecision, DefenseRequest
from giraph.trace import TraceWriter, record
from giraph.verdict import verdict


class Giraph:
    name = "giraph"

    def __init__(self, planner: Planner | None = None, tracer: TraceWriter | None = None) -> None:
        self.planner = planner or planner_from_env()
        self.tracer = tracer or TraceWriter()
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
