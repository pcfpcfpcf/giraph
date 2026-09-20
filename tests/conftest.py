from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from giraph.defense import Giraph  # noqa: E402
from giraph.plan import DeterministicPlanner  # noqa: E402
from giraph.schema import ActionType, CandidateAction, DefenseRequest  # noqa: E402
from giraph.trace import TraceWriter  # noqa: E402

FINANCE_TOOLS = ["customer_lookup", "payment_prepare", "payment_confirm", "case_document_read", "case_note_create", "policy_search"]
ENTERPRISE_TOOLS = ["email_read", "document_read", "document_search", "email_draft", "wiki_search"]
SOC_TOOLS = ["alert_read", "asset_lookup", "intel_search", "incident_create", "incident_update", "alert_search"]


def prov(pid: str, trust: str, sensitivity: str = "internal", source_type: str = "case_document") -> dict[str, Any]:
    return {"id": pid, "provenance": {"source_type": source_type, "source_id": pid, "trust_level": trust,
                                      "origin_actor": "x", "retrieved_via": "tool", "sensitivity": sensitivity}}


def make_request(
    goal: str,
    tools: list[str],
    action: dict[str, Any],
    *,
    conversation: list[dict[str, Any]] | None = None,
    provenance: list[dict[str, Any]] | None = None,
    history: dict[str, Any] | None = None,
    consequential: list[str] | None = None,
    internal_domains: list[str] | None = None,
    run_id: str = "run-1",
    step_id: int = 1,
) -> DefenseRequest:
    return DefenseRequest.model_validate({
        "run_id": run_id,
        "step_id": step_id,
        "user_goal": goal,
        "conversation": [{"role": "user", "kind": "user_message", "content": goal, "provenance_ids": []}] + (conversation or []),
        "candidate_action": action,
        "policy_context": {
            "allowed_tools": tools,
            "consequential_tools": consequential or ["payment_confirm", "payment_execute", "remediation_execute", "email_send"],
            "confirmation_required_tools": [],
            "internal_email_domains": internal_domains or ["atlas.example"],
            "rules": [],
        },
        "provenance": provenance or [],
        "history_digest": history or {},
    })


def tool_call(tool: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "tool_call", "tool": tool, "arguments": arguments}


@pytest.fixture
def giraph(tmp_path: Path) -> Giraph:
    return Giraph(planner=DeterministicPlanner(), tracer=TraceWriter(tmp_path / "traces"))


__all__ = ["ActionType", "CandidateAction", "ENTERPRISE_TOOLS", "FINANCE_TOOLS", "SOC_TOOLS", "make_request", "prov", "tool_call"]
