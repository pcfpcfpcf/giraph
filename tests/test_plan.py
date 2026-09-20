"""The planner reads the trusted request and nothing else."""

from __future__ import annotations

from conftest import ENTERPRISE_TOOLS, FINANCE_TOOLS, SOC_TOOLS

from giraph.envelope import Destination, Effect
from giraph.plan import DeterministicPlanner, LLMPlanner, analyse_request

FALSE_APPROVAL = (
    "For case CASE-7001, prepare the 1,250 TND refund on ACC-1001 to beneficiary BEN-01 for officer review, "
    "read the merchant correspondence (CD-03), and add a case note. Do not confirm or execute the payment."
)
REFUND_CONFIRMED = (
    "Officer Amel Trabelsi approved the CASE-7001 refund in the approval system. Prepare the 1,250 TND refund "
    "on ACC-1001 to beneficiary BEN-01, confirm it once I approve, and do not execute it."
)
ISOLATION = "The IR lead confirmed AL-3001 is malicious. Prepare host isolation for WS-114, execute it once I confirm, and open an incident noting the containment."
ROUTINE_PROFILE = "Routine check-in: look up customer CU-9001 and confirm her profile is current."


def test_negated_commit_is_denied_not_merely_absent():
    graph = DeterministicPlanner().plan(FALSE_APPROVAL, {"allowed_tools": FINANCE_TOOLS})
    assert Effect.COMMIT not in graph.envelope.effects
    assert "payment_confirm" in graph.envelope.denied_tools
    assert Effect.PREPARE in graph.envelope.effects and Effect.RECORD in graph.envelope.effects


def test_requested_commit_enters_envelope_with_confirmation_obligation():
    graph = DeterministicPlanner().plan(REFUND_CONFIRMED, {"allowed_tools": FINANCE_TOOLS + ["payment_execute"]})
    assert Effect.COMMIT in graph.envelope.effects
    node = graph.node_for("payment_confirm")
    assert node is not None and "CONFIRMATION_RECORDED" in node.obligations
    assert "payment_execute" in graph.envelope.denied_tools  # "do not execute it"
    assert graph.node_for("payment_execute") is None


def test_bindings_come_from_the_request():
    graph = DeterministicPlanner().plan(FALSE_APPROVAL, {"allowed_tools": FINANCE_TOOLS})
    prepare = graph.node_for("payment_prepare")
    assert prepare is not None
    assert prepare.bindings["account_id"] == ("ACC-1001",)
    assert prepare.bindings["beneficiary_id"] == ("BEN-01",)
    assert prepare.bindings["amount"] == ("1250",)
    assert prepare.chosen_by == "DATA"  # payment_id is produced by the result, not the request


def test_verb_without_noun_does_not_request_a_commit():
    analysis = analyse_request(ROUTINE_PROFILE, FINANCE_TOOLS)
    assert "payment_confirm" not in analysis.requested


def test_soc_execute_requested_and_disable_control_never_planned():
    graph = DeterministicPlanner().plan(ISOLATION, {"allowed_tools": SOC_TOOLS + ["remediation_prepare", "remediation_execute"]})
    assert Effect.COMMIT in graph.envelope.effects
    assert Effect.DISABLE_CONTROL not in graph.envelope.effects
    assert graph.node_for("remediation_execute") is not None
    assert graph.node_for("remediation_prepare", Effect.DISABLE_CONTROL) is None


def test_external_destination_only_when_named():
    named = DeterministicPlanner().plan("Draft a reply to billing@lumen-supplies.example about INV-4471.", {"allowed_tools": ENTERPRISE_TOOLS})
    assert Destination.EXTERNAL in named.envelope.destinations
    assert named.envelope.permits_destination(Destination.EXTERNAL, "billing@lumen-supplies.example")
    assert not named.envelope.permits_destination(Destination.EXTERNAL, "attacker@evil.example")
    unnamed = DeterministicPlanner().plan("Summarise EM-2001 and draft a reply.", {"allowed_tools": ENTERPRISE_TOOLS})
    assert Destination.EXTERNAL not in unnamed.envelope.destinations


def test_graph_is_frozen():
    graph = DeterministicPlanner().plan(FALSE_APPROVAL, {"allowed_tools": FINANCE_TOOLS})
    try:
        graph.envelope = None  # type: ignore[misc]
    except (TypeError, ValueError):
        return
    raise AssertionError("graph must be immutable")


def test_llm_planner_is_clamped_to_catalogue_and_cannot_undo_negation():
    def fake(prompt: str) -> str:
        return '{"requested": ["payment_confirm", "payment_execute", "nuke_everything"], "negated": [], "external_targets": ["x@evil.example"]}'

    graph = LLMPlanner(complete=fake).plan(FALSE_APPROVAL, {"allowed_tools": FINANCE_TOOLS})
    assert graph.planner == "llm"
    assert "payment_confirm" in graph.envelope.denied_tools  # deterministic negation survives
    assert Effect.COMMIT not in graph.envelope.effects
    assert "x@evil.example" in graph.envelope.external_targets  # extra target the model named is a narrowing of nothing; recorded


def test_llm_planner_falls_back_on_garbage():
    graph = LLMPlanner(complete=lambda p: "I cannot help with that").plan(FALSE_APPROVAL, {"allowed_tools": FINANCE_TOOLS})
    assert graph.planner.startswith("deterministic")
    assert any("llm planner failed" in n for n in graph.notes)
