"""The four outcomes. The only module that turns a monitor result into a decision.

ALLOW     conforms, or diverges but stays inside the envelope
BLOCK     needs authority the envelope never granted, and untrusted content is driving it
REWRITE   unsafe branch pruned, safe subplan kept
ESCALATE  a human could authorise this, or the checker returned unknown
"""

from __future__ import annotations

from giraph.envelope import Authority, Destination, Effect
from giraph.monitor import Divergence, MonitorResult
from giraph.plan import Obligation
from giraph.schema import ActionType, CandidateAction, Decision, DefenseDecision


def _decision(kind: Decision, risk: float, confidence: float, codes: list[str], why: str, rewritten: CandidateAction | None = None) -> DefenseDecision:
    return DefenseDecision(
        decision=kind,
        risk_score=round(min(1.0, max(0.0, risk)), 3),
        confidence=round(min(1.0, max(0.0, confidence)), 3),
        reason_codes=codes[:16],
        explanation=why[:500],
        rewritten_action=rewritten,
    )


def _authority_codes(result: MonitorResult) -> list[str]:
    codes: list[str] = []
    if result.mirrored:
        codes.append("UNTRUSTED_INSTRUCTION_SOURCE")
    elif result.authority.is_untrusted:
        codes.append("UNTRUSTED_AUTHORED_VALUE")
    elif result.authority is Authority.UNKNOWN:
        codes.append("VALUE_ORIGIN_UNKNOWN")
    return codes


def verdict(result: MonitorResult, candidate: CandidateAction) -> DefenseDecision:
    untrusted = result.authority.is_untrusted
    asking = candidate.type is ActionType.REQUEST_CONFIRMATION
    irreversible = result.effect is not None and result.effect.irreversible

    # ---- replies and memory ---------------------------------------------------------------
    if result.action_type is ActionType.RESPOND:
        return _decision(Decision.ALLOW, 0.05, 0.9, ["REPLY_TO_PRINCIPAL"], "reply to the user; no effect leaves the task")
    if result.action_type is ActionType.MEMORY_WRITE:
        if result.violates(Obligation.NO_UNTRUSTED_COPY):
            # Memory inherits trust: the recall is labelled with the level it was written under, so the
            # monitor sees it as untrusted next turn. Storing it cannot author an action; flag and allow.
            return _decision(Decision.ALLOW, 0.35, 0.7, ["UNTRUSTED_CONTENT_IN_MEMORY"],
                             "memory entry copies untrusted content; it stays labelled untrusted on recall")
        return _decision(Decision.ALLOW, 0.1, 0.7, ["AGENT_AUTHORED_MEMORY"], "agent-composed memory entry")

    # ---- structural failures: no node can ever exist ---------------------------------------
    if result.divergence is Divergence.UNKNOWN_TOOL:
        return _decision(Decision.BLOCK, 0.95, 0.95, ["UNKNOWN_TOOL_EFFECT"], f"{result.tool} has no entry in the effect schema")
    if result.violates(Obligation.NO_SENSITIVE_OUTWARD):
        return _decision(Decision.BLOCK, 0.95, 0.85, ["SENSITIVE_TO_EXTERNAL_DESTINATION", *_authority_codes(result)],
                         f"payload carries confidential content addressed to {result.address}")
    if result.divergence is Divergence.DENIED_BY_REQUEST:
        return _decision(Decision.BLOCK, 0.9, 0.9, ["DENIED_BY_REQUEST", *_authority_codes(result)],
                         f"the request explicitly excluded {result.tool}; not escalatable")
    if result.divergence is Divergence.TOOL_NOT_ALLOWED:
        if result.pruned is not None and not untrusted:
            return _decision(Decision.REWRITE, 0.6, 0.8, ["TOOL_NOT_ALLOWED", "PRUNED_TO_SAFE_SUBPLAN"],
                             f"{result.tool} is outside policy; routed to {result.pruned.tool}", result.pruned)
        return _decision(Decision.BLOCK, 0.9, 0.9, ["TOOL_NOT_ALLOWED", *_authority_codes(result)],
                         f"{result.tool} is not in the task's allowed tools")

    # ---- outside the envelope: needs authority the plan never granted ------------------
    if result.divergence is Divergence.OUTSIDE_ENVELOPE:
        what = f"{result.effect.value if result.effect else '?'} via {result.tool}"
        if untrusted:
            return _decision(Decision.BLOCK, 0.92, 0.85, ["EFFECT_OUTSIDE_ENVELOPE", *_authority_codes(result)],
                             f"{what} was never authorised and is driven by untrusted content: {result.authority_evidence}")
        if result.pruned is not None:
            return _decision(Decision.REWRITE, 0.55, 0.8, ["EFFECT_OUTSIDE_ENVELOPE", "PRUNED_TO_SAFE_SUBPLAN"],
                             f"{what} was never authorised; kept the reversible subplan via {result.pruned.tool}", result.pruned)
        if result.authority is Authority.UNKNOWN:
            return _decision(Decision.ESCALATE, 0.7, 0.5, ["EFFECT_OUTSIDE_ENVELOPE", "VALUE_ORIGIN_UNKNOWN"],
                             f"{what} was never authorised and the checker cannot trace its values")
        return _decision(Decision.ESCALATE, 0.65, 0.7, ["EFFECT_OUTSIDE_ENVELOPE"],
                         f"{what} was never authorised by the request; a human may authorise it")

    # ---- inside the envelope: check the node's obligations ----------------------------------
    codes: list[str] = []
    if result.violates(Obligation.PREREQUISITE_FIRED):
        return _decision(Decision.BLOCK, 0.85, 0.9, ["SEQUENCE_VIOLATION", *_authority_codes(result)],
                         f"{result.tool} requires an earlier prepare step that never fired")
    if result.violates(Obligation.DESTINATION_IN_ENVELOPE):
        kind = Decision.BLOCK if untrusted else Decision.ESCALATE
        return _decision(kind, 0.85 if untrusted else 0.6, 0.8, ["DESTINATION_OUTSIDE_ENVELOPE", *_authority_codes(result)],
                         f"{result.address} is not a destination the request named")
    if result.violates(Obligation.VALUES_BOUND):
        kind = Decision.BLOCK if untrusted else Decision.ESCALATE
        return _decision(kind, 0.85 if untrusted else 0.6, 0.8, ["VALUE_NOT_BOUND_TO_REQUEST", *_authority_codes(result)],
                         "an argument differs from what the request bound: " + "; ".join(result.notes)[:300])
    if result.violates(Obligation.TRUSTED_AUTHORITY):
        if irreversible:
            kind = Decision.ESCALATE if result.authority is Authority.UNKNOWN else Decision.BLOCK
            return _decision(kind, 0.9, 0.85, ["UNTRUSTED_AUTHORITY_ON_IRREVERSIBLE_EFFECT", *_authority_codes(result)],
                             f"an irreversible effect may not be driven by untrusted content: {result.authority_evidence}")
        if result.mirrored and result.effect is Effect.PREPARE:
            # Staging something on an injected instruction is reversible, but a human may later commit it blind.
            return _decision(Decision.ESCALATE, 0.6, 0.7, ["UNTRUSTED_INSTRUCTION_SOURCE", "STAGED_ON_UNTRUSTED_INSTRUCTION"],
                             f"reversible, but staged on an instruction found in untrusted content: {result.authority_evidence}")
        codes.append("UNTRUSTED_SELECTION_INSIDE_ENVELOPE")  # data may select what is read or recorded
        if result.mirrored:
            codes.append("UNTRUSTED_INSTRUCTION_SOURCE")
    if result.violates(Obligation.CONFIRMATION_RECORDED):
        if asking:
            return _decision(Decision.ALLOW, 0.3, 0.8, ["CONFIRMATION_REQUESTED", *codes], "agent is asking for the required confirmation")
        return _decision(Decision.ESCALATE, 0.55, 0.8, ["MISSING_CONFIRMATION", *codes],
                         f"{result.tool} is inside the envelope but needs a recorded human confirmation")
    if result.divergence is Divergence.ENVELOPE_CONFORMING:
        codes.append("ENVELOPE_CONFORMING_DIVERGENCE")
    else:
        codes.append("PLAN_CONFORMING")
    risk = 0.3 if "UNTRUSTED_SELECTION_INSIDE_ENVELOPE" in codes else 0.1
    return _decision(Decision.ALLOW, risk, 0.85, codes, f"{result.tool} matches node {result.node_id}; obligations satisfied")
