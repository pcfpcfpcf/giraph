"""Observability: one JSONL record per decision, written live. Nothing here influences a decision."""

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from giraph.monitor import MonitorResult, WorkingSet, redact
from giraph.plan import PlanGraph
from giraph.schema import DefenseDecision, DefenseRequest


def _masked(value: Any, restricted: tuple[str, ...]) -> Any:
    return redact(value, restricted)[0] if isinstance(value, str) else value


def record(request: DefenseRequest, graph: PlanGraph, result: MonitorResult, decision: DefenseDecision, latency_ms: float) -> dict[str, Any]:
    """The trace is a sink like any other: credential-class content is masked before it is written."""
    action = request.candidate_action
    restricted = WorkingSet.from_request(request).restricted
    return {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "run_id": request.run_id,
        "turn": request.history_digest.turn_index,
        "step": request.step_id,
        "goal": request.user_goal,
        "action": {"type": action.type.value, "tool": action.tool,
                   "arguments": {k: _masked(v, restricted) for k, v in action.arguments.items()},
                   "content": _masked(action.content or "", restricted)[:200] or None, "final": action.final,
                   "confirmation_for": action.confirmation_for.tool if action.confirmation_for else None},
        "graph": {"digest": graph.goal_digest, "planner": graph.planner,
                  "envelope": sorted(e.value for e in graph.envelope.effects),
                  "denied": sorted(graph.envelope.denied_tools)},
        "node": result.node_id,
        "effect": result.effect.value if result.effect else None,
        "divergence": result.divergence.value,
        "authority": {"level": result.authority.value, "evidence": _masked(result.authority_evidence, restricted), "mirrored": result.mirrored},
        "destination": {"kind": result.destination.value if result.destination else None, "address": result.address},
        "obligations": {"satisfied": [o.value for o in result.satisfied], "violated": [o.value for o in result.violated]},
        "decision": decision.decision.value,
        "risk": decision.risk_score,
        "confidence": decision.confidence,
        "reason_codes": decision.reason_codes,
        "explanation": _masked(decision.explanation, restricted),
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

    def summary(self) -> dict[str, Any]:
        """Aggregate view over every run seen by this process: decision mix, latency, reason codes, one row per run."""
        with self._lock:
            runs = {run_id: list(entries) for run_id, entries in sorted(self._memory.items())}
        entries = [e for es in runs.values() for e in es]
        kinds = ("allow", "rewrite", "escalate", "block")
        decisions = dict.fromkeys(kinds, 0)
        by_effect: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(kinds, 0))
        codes: dict[str, int] = defaultdict(int)
        violated: dict[str, int] = defaultdict(int)
        for e in entries:
            decisions[e["decision"]] = decisions.get(e["decision"], 0) + 1
            by_effect[e["effect"] or "—"][e["decision"]] += 1
            for c in e["reason_codes"]:
                codes[c] += 1
            for o in e["obligations"]["violated"]:
                violated[o] += 1
        latencies = sorted(e["latency_ms"] for e in entries)
        pct = (lambda q: latencies[min(len(latencies) - 1, int(q * len(latencies)))]) if latencies else (lambda q: None)
        rows = []
        for run_id, es in runs.items():
            mix = {d: sum(1 for e in es if e["decision"] == d) for d in kinds}
            rows.append({"run_id": run_id, "goal": es[0].get("goal", ""), "planner": es[0]["graph"]["planner"],
                         "decisions": len(es), "mix": mix, "max_risk": max(e["risk"] for e in es),
                         "turns": len({e["turn"] for e in es})})
        return {"runs": len(runs), "decisions": len(entries), "mix": decisions,
                "latency_ms": {"median": pct(0.5), "p95": pct(0.95)},
                "planners": sorted({e["graph"]["planner"] for e in entries}),
                "by_effect": {k: by_effect[k] for k in sorted(by_effect)},
                "reason_codes": sorted(codes.items(), key=lambda kv: -kv[1]),
                "violated": sorted(violated.items(), key=lambda kv: -kv[1]),
                "rows": rows}

    def runs(self) -> list[dict[str, str]]:
        """One row per run, in memory or on disk: its id and the user goal it was planned for (from the first record)."""
        with self._lock:
            rows = {run_id: entries[0].get("goal", "") for run_id, entries in self._memory.items() if entries}
        if self.directory.exists():
            for path in self.directory.glob("*.jsonl"):
                if path.stem not in rows:
                    try:
                        with path.open(encoding="utf-8") as fh:
                            rows[path.stem] = json.loads(fh.readline() or "{}").get("goal", "")
                    except (OSError, ValueError):
                        continue
        return [{"run_id": run_id, "goal": goal} for run_id, goal in sorted(rows.items())]
