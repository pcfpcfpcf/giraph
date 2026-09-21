"""HTTP surface: the SENTINEL v1 defense contract plus read-only observability endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from giraph.defense import Giraph
from giraph.schema import DefenseDecision, DefenseRequest

app = FastAPI(title="GIRAPH", docs_url=None, redoc_url=None, openapi_url=None)
giraph = Giraph()
STATIC = Path(__file__).parent / "static"
# Scorecards are written by the simulator (`sentinel eval`), not by us; the page reads them from where the kit puts them.
SCORECARD_DIRS = [Path(d) for d in os.environ.get("GIRAPH_SCORECARD_DIRS", "Sentinel_Starter_Kit/artifacts/scorecards:artifacts/scorecards").split(":") if d]


def _scorecard_files() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for directory in SCORECARD_DIRS:
        for path in directory.glob("*.json") if directory.is_dir() else ():
            found.setdefault(path.name, path)
    return found


@app.get("/")
def index() -> FileResponse:
    """The observability page: plan graph, envelope, and one row per decision."""
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


@app.get("/summary")
def summary() -> dict[str, Any]:
    return giraph.tracer.summary()


@app.get("/scorecards")
def scorecards() -> list[dict[str, Any]]:
    """Every `sentinel eval` scorecard on disk, newest first, summarised for a picker."""
    rows = []
    for name, path in _scorecard_files().items():
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows.append({"name": name, "mtime": path.stat().st_mtime, "split": card.get("split"), "defense": card.get("defense"),
                     "attack_mode": card.get("attack_mode"), "scenario_count": card.get("scenario_count"),
                     "official_score": card.get("score", {}).get("official_score")})
    return sorted(rows, key=lambda r: -r["mtime"])


@app.get("/scorecard/{name}")
def scorecard(name: str) -> dict[str, Any]:
    path = _scorecard_files().get(name)
    if path is None:
        raise HTTPException(404, "no such scorecard")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/runs")
def runs() -> list[dict[str, str]]:
    return giraph.tracer.runs()
