"""Observability: one JSONL record per decision, written live. Nothing here influences a decision."""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from giraph.monitor import MonitorResult
from giraph.plan import PlanGraph
from giraph.schema import DefenseDecision, DefenseRequest


def record(request: DefenseRequest, graph: PlanGraph, result: MonitorResult, decision: DefenseDecision, latency_ms: float) -> dict[str, Any]:
    action = request.candidate_action
    return {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "run_id": request.run_id,
        "turn": request.history_digest.turn_index,
        "step": request.step_id,
        "action": {"type": action.type.value, "tool": action.tool, "arguments": action.arguments,
                   "content": (action.content or "")[:200] or None, "final": action.final,
                   "confirmation_for": action.confirmation_for.tool if action.confirmation_for else None},
        "graph": {"digest": graph.goal_digest, "planner": graph.planner,
                  "envelope": sorted(e.value for e in graph.envelope.effects),
                  "denied": sorted(graph.envelope.denied_tools)},
        "node": result.node_id,
        "effect": result.effect.value if result.effect else None,
        "divergence": result.divergence.value,
        "authority": {"level": result.authority.value, "evidence": result.authority_evidence, "mirrored": result.mirrored},
        "destination": {"kind": result.destination.value if result.destination else None, "address": result.address},
        "obligations": {"satisfied": [o.value for o in result.satisfied], "violated": [o.value for o in result.violated]},
        "decision": decision.decision.value,
        "risk": decision.risk_score,
        "confidence": decision.confidence,
        "reason_codes": decision.reason_codes,
        "explanation": decision.explanation,
        "rewritten_to": decision.rewritten_action.tool if decision.rewritten_action else None,
        "latency_ms": round(latency_ms, 2),
    }


class TraceWriter:
    """Appends to ``<dir>/<run_id>.jsonl`` and keeps an in-memory copy for the API."""

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = Path(directory or os.environ.get("GIRAPH_TRACE_DIR", "traces"))
        self._lock = threading.Lock()
        self._memory: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def write(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._memory[entry["run_id"]].append(entry)
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                with (self.directory / f"{entry['run_id']}.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError:
                pass  # tracing must never take the defense down

    def read(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if run_id in self._memory and self._memory[run_id]:
                return list(self._memory[run_id])
            target = self.directory / f"{run_id}.jsonl"
            if target.exists():
                try:
                    entries = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
                    self._memory[run_id] = entries
                    return list(entries)
                except Exception:
                    pass
            return []

    def runs(self) -> list[str]:
        disk_runs: set[str] = set()
        if self.directory.exists():
            try:
                for p in self.directory.glob("*.jsonl"):
                    disk_runs.add(p.stem)
            except OSError:
                pass
        with self._lock:
            return sorted(set(self._memory.keys()) | disk_runs)
