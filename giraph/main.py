"""HTTP surface: the SENTINEL v1 defense contract plus read-only observability endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from giraph.defense import Giraph
from giraph.schema import DefenseDecision, DefenseRequest

app = FastAPI(title="GIRAPH", docs_url=None, redoc_url=None, openapi_url=None)
giraph = Giraph()
STATIC = Path(__file__).parent / "static"


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


@app.get("/runs")
def runs() -> list[str]:
    return giraph.tracer.runs()
