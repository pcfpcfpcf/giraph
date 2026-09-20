"""Conformance monitor. Runs every turn, sees untrusted content, reads the graph, writes nothing back.

Two questions per action: is there a node for it, and does the action satisfy that node's
obligations while staying inside the envelope? The monitor reports; ``verdict`` decides.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from giraph.catalogue import ID_REGEX, ToolSpec, spec_for
from giraph.envelope import Authority, Destination, Effect, Sensitivity, authority_from_trust
from giraph.plan import Obligation, PlanGraph, PlanNode
from giraph.schema import ActionType, CandidateAction, DefenseRequest

MIRROR_WINDOW = 250  # chars around a tool name in untrusted text within which an argument value counts as an instruction
OVERLAP_PROBE = 32  # verbatim-copy probe length
MIN_VALUE_CHARS = 3
TRUSTED_ROLES_WITHOUT_PROVENANCE = frozenset({"user", "tool", "human", "safety"})


class Divergence(StrEnum):
    NONE = "NONE"  # a node predicted this action
    ENVELOPE_CONFORMING = "ENVELOPE_CONFORMING"  # unpredicted but inside the envelope
    OUTSIDE_ENVELOPE = "OUTSIDE_ENVELOPE"  # needs authority the envelope never granted
    DENIED_BY_REQUEST = "DENIED_BY_REQUEST"  # the trusted request forbade this
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"  # policy never listed the tool
    UNKNOWN_TOOL = "UNKNOWN_TOOL"  # not in the catalogue: the effect schema cannot label it


class WorkingSet(BaseModel):
    """The task's observed content, partitioned by trust label. Rebuilt from the request each turn."""

    model_config = ConfigDict(frozen=True)

    goal: str
    trusted: tuple[str, ...]
    untrusted: tuple[tuple[str, Authority], ...]
    sensitive: tuple[str, ...]  # confidential or above: may not leave the organisation
    restricted: tuple[str, ...]  # credential class: may not reach any sink, not even the principal

    @classmethod
    def from_request(cls, request: DefenseRequest) -> WorkingSet:
        records = {r.id: r.provenance for r in request.provenance}
        trusted: list[str] = [request.user_goal]
        untrusted: list[tuple[str, Authority]] = []
        sensitive: list[str] = []
        restricted: list[str] = []
        for item in request.conversation:
            provs = [records[p] for p in item.provenance_ids if p in records]
            levels = [authority_from_trust(p.trust_level) for p in provs]
            worst = max(levels, key=lambda a: a.rank, default=Authority.AGENT)
            if worst.is_untrusted:
                untrusted.append((item.content, worst))
            elif provs or item.role in TRUSTED_ROLES_WITHOUT_PROVENANCE:
                # A tool result with no provenance is the gateway reporting on an action the monitor
                # already allowed (e.g. the id of a prepared payment); it is trusted internal state.
                trusted.append(item.content)
            if any(_sensitivity(p.sensitivity).rank >= Sensitivity.CONFIDENTIAL.rank for p in provs):
                sensitive.append(item.content)
            if any(_sensitivity(p.sensitivity) is Sensitivity.RESTRICTED for p in provs):
                restricted.append(item.content)
        return cls(goal=request.user_goal, trusted=tuple(trusted), untrusted=tuple(untrusted),
                   sensitive=tuple(sensitive), restricted=tuple(restricted))


class MonitorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    tool: str | None
    node_id: str | None
    effect: Effect | None
    divergence: Divergence
    authority: Authority
    authority_evidence: str
    destination: Destination | None = None
    address: str | None = None
    confirmed: bool = False
    mirrored: bool = False  # the tool name and a value co-occur in untrusted text: an instruction, not data
    satisfied: tuple[Obligation, ...] = ()
    violated: tuple[Obligation, ...] = ()
    pruned: CandidateAction | None = None  # a safe sub-action inside the envelope, if one exists
    notes: tuple[str, ...] = Field(default_factory=tuple)

    def violates(self, obligation: Obligation) -> bool:
        return obligation in self.violated


# ---- text helpers --------------------------------------------------------------------------------


def squash(text: str) -> str:
    return " ".join(text.split()).lower()


def _sensitivity(value: str) -> Sensitivity:
    try:
        return Sensitivity(value)
    except ValueError:
        return Sensitivity.INTERNAL


def overlaps(content: str, texts: tuple[str, ...] | list[str], minimum: int = OVERLAP_PROBE) -> bool:
    needle = squash(content)
    if len(needle) < 12:
        return False
    if len(needle) < minimum:
        return any(needle in squash(t) for t in texts)
    probes = {needle[i : i + minimum] for i in range(0, len(needle) - minimum + 1, minimum // 2)}
    return any(probe in squash(t) for t in texts for probe in probes)


REDACT_RUN = 16  # a verbatim run this long copied from restricted content is redacted


def redact(text: str, restricted: tuple[str, ...]) -> tuple[str, bool]:
    """Mask maximal runs of ``text`` (>= REDACT_RUN chars, whitespace-normalised) that occur verbatim in
    restricted content. Returns (masked text, whether anything was masked)."""
    if not text or not restricted:
        return text, False
    haystacks = [squash(t) for t in restricted]
    lowered = text.lower()
    marks = [False] * len(text)
    i = 0
    while i + REDACT_RUN <= len(text):
        probe = " ".join(lowered[i : i + REDACT_RUN].split())
        if len(probe) >= REDACT_RUN - 2 and any(probe in h for h in haystacks):
            for j in range(i, i + REDACT_RUN):
                marks[j] = True
            i += 1
        else:
            i += 1
    if not any(marks):
        return text, False
    out: list[str] = []
    i = 0
    while i < len(text):
        if marks[i]:
            j = i
            while j < len(text) and marks[j]:
                j += 1
            out.append("[REDACTED]")
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out), True


def _driving_values(action: CandidateAction, spec: ToolSpec | None) -> list[tuple[str, str]]:
    """Argument values that select *what* the action does (not free-text payloads)."""
    payload = set(spec.payload_args) if spec else set()
    values: list[tuple[str, str]] = []
    for key, value in action.arguments.items():
        if key in payload or value is None or isinstance(value, bool):
            continue
        text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        if len(text) >= MIN_VALUE_CHARS:
            values.append((key, text))
    return values


def _mirrored_instruction(action: CandidateAction, values: list[tuple[str, str]], untrusted: tuple[tuple[str, Authority], ...]) -> Authority | None:
    """The tool name and one of its argument values co-occur in untrusted text: an instruction, not data."""
    if action.tool is None:
        return None
    needles = [squash(v) for _, v in values if len(v) >= 4]
    for text, level in untrusted:
        lowered = squash(text)
        start = lowered.find(action.tool)
        while start != -1:
            window = lowered[max(0, start - MIRROR_WINDOW) : start + MIRROR_WINDOW]
            if not needles or any(n in window for n in needles):
                return level
            start = lowered.find(action.tool, start + 1)
    return None


def trace_authority(action: CandidateAction, spec: ToolSpec | None, ws: WorkingSet) -> tuple[Authority, str]:
    """Who authored the values that drive this action. This is the select-vs-author check."""
    values = _driving_values(action, spec)
    if not values:
        return Authority.AGENT, "no selecting values; agent-composed"
    goal = squash(ws.goal)
    if all(squash(v) in goal for _, v in values):
        return Authority.AUTHENTICATED_USER, "every selecting value was named in the request"
    trusted_text = [squash(t) for t in ws.trusted]
    untrusted_text = [(squash(t), level) for t, level in ws.untrusted]
    worst = Authority.AUTHENTICATED_USER
    for key, value in values:
        needle = squash(value)
        if any(needle in t for t in trusted_text):
            continue  # the request or a trusted result produced it; untrusted text repeating it changes nothing
        hits = [level for t, level in untrusted_text if needle in t]
        if hits:
            level = max(hits, key=lambda a: a.rank)
            return level, f"{key}={value!r} appears only in {level.value} content"
        if any(r.fullmatch(value) for r in ID_REGEX.values()):
            worst = Authority.UNKNOWN  # an identifier nothing observed ever produced
        elif worst.rank < Authority.AGENT.rank:
            worst = Authority.AGENT
    if worst is Authority.UNKNOWN:
        return worst, "an identifier argument was never observed in any content"
    return worst, "all selecting values trace to the request or trusted content" if worst is not Authority.AGENT else "free values composed by the agent"


def classify_destination(address: str | None, request: DefenseRequest) -> Destination | None:
    if address is None:
        return None
    domain = address.rsplit("@", 1)[-1].strip().lower() if "@" in address else ""
    internal = [d.lower() for d in request.policy_context.get("internal_email_domains", [])]
    return Destination.INTERNAL if domain and domain in internal else Destination.EXTERNAL


# ---- the check ----------------------------------------------------------------------------------


def target_of(action: CandidateAction) -> CandidateAction:
    if action.type is ActionType.REQUEST_CONFIRMATION and action.confirmation_for is not None:
        return action.confirmation_for
    return action


def _prerequisite_fired(node: PlanNode, request: DefenseRequest) -> bool:
    fired = {c.tool for c in request.history_digest.tool_calls if c.decision in ("allow", "rewrite", "escalate") and c.succeeded is not False}
    return all(r in fired for r in node.requires)


def _bound(node: PlanNode, action: CandidateAction) -> list[str]:
    broken: list[str] = []
    for arg, allowed in node.bindings.items():
        value = action.arguments.get(arg)
        if value is None:
            continue
        text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
        if arg == "amount":
            ok = any(_num(text) == _num(a) for a in allowed)
        else:
            ok = text.lower() in {a.lower() for a in allowed}
        if not ok:
            broken.append(f"{arg}={text!r} ∉ {list(allowed)}")
    return broken


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def check(graph: PlanGraph, request: DefenseRequest) -> MonitorResult:
    candidate = request.candidate_action
    action = target_of(candidate)
    ws = WorkingSet.from_request(request)
    notes: list[str] = []

    # ---- non-tool actions ----------------------------------------------------------------
    if action.type is ActionType.RESPOND:
        node = graph.node_for(None, Effect.RESPOND)
        masked, leaked = redact(action.content or "", ws.restricted)
        pruned = action.model_copy(update={"content": masked}) if leaked and masked.strip("[REDACTED] \n") else None
        return MonitorResult(
            action_type=action.type, tool=None, node_id=node.id if node else None, effect=Effect.RESPOND,
            divergence=Divergence.NONE, authority=Authority.AGENT, authority_evidence="reply to the principal",
            destination=Destination.PRINCIPAL,
            violated=(Obligation.NO_RESTRICTED_PAYLOAD,) if leaked else (),
            satisfied=(Obligation.NO_SENSITIVE_OUTWARD,) + (() if leaked else (Obligation.NO_RESTRICTED_PAYLOAD,)),
            pruned=pruned,
        )
    if action.type is ActionType.MEMORY_WRITE:
        node = graph.node_for(None, Effect.MEMORY_WRITE)
        copied = overlaps(action.content or "", [t for t, _ in ws.untrusted])
        level = max((l for t, l in ws.untrusted if overlaps(action.content or "", [t])), key=lambda a: a.rank, default=Authority.AGENT)
        masked, leaked = redact(action.content or "", ws.restricted)
        violated = ((Obligation.NO_UNTRUSTED_COPY,) if copied else ()) + ((Obligation.NO_RESTRICTED_PAYLOAD,) if leaked else ())
        return MonitorResult(
            action_type=action.type, tool=None, node_id=node.id if node else None, effect=Effect.MEMORY_WRITE,
            divergence=Divergence.NONE, authority=level if copied else Authority.AGENT,
            authority_evidence="memory content copied verbatim from untrusted content" if copied else "agent-composed memory",
            destination=Destination.INTERNAL, violated=violated,
            satisfied=tuple(o for o in (Obligation.NO_UNTRUSTED_COPY, Obligation.NO_RESTRICTED_PAYLOAD) if o not in violated),
            pruned=action.model_copy(update={"content": masked}) if leaked and masked.strip("[REDACTED] \n") else None,
        )

    # ---- tool calls ------------------------------------------------------------------------
    spec = spec_for(action.tool)
    allowed = list(request.policy_context.get("allowed_tools", []))
    authority, evidence = trace_authority(action, spec, ws)
    goal = squash(ws.goal)
    unexplained = [(k, v) for k, v in _driving_values(action, spec) if squash(v) not in goal]
    mirrored = _mirrored_instruction(action, unexplained, ws.untrusted) is not None
    if mirrored:
        evidence += "; the tool call is spelled out in untrusted content"
    if spec is None:
        return MonitorResult(
            action_type=action.type, tool=action.tool, node_id=None, effect=None, divergence=Divergence.UNKNOWN_TOOL,
            authority=authority, authority_evidence=evidence, mirrored=mirrored, notes=("tool not in effect schema",),
        )
    effect, override = spec.effect_for(action.arguments)
    address = str(action.arguments.get(spec.destination_arg)) if spec.destination_arg and action.arguments.get(spec.destination_arg) else None
    destination = classify_destination(address, request) if spec.destination_arg else Destination.INTERNAL
    node = graph.node_for(spec.name, effect)
    pruned = _prune(graph, spec, effect, override, action, allowed, destination, address)

    if action.tool not in allowed:
        divergence = Divergence.TOOL_NOT_ALLOWED
    elif spec.name in graph.envelope.denied_tools and (override is None or effect.irreversible):
        divergence = Divergence.DENIED_BY_REQUEST
    elif node is None or not graph.envelope.permits_effect(effect):
        divergence = Divergence.OUTSIDE_ENVELOPE
    else:
        divergence = Divergence.NONE

    satisfied: list[Obligation] = []
    violated: list[Obligation] = []
    confirmed = action.digest() in request.history_digest.confirmations_granted
    if spec.payload_args:
        redacted_args = dict(action.arguments)
        leaked = False
        for arg in spec.payload_args:
            value = action.arguments.get(arg)
            if isinstance(value, str):
                redacted_args[arg], hit = redact(value, ws.restricted)
                leaked = leaked or hit
        if leaked:
            violated.append(Obligation.NO_RESTRICTED_PAYLOAD)
            notes.append("restricted content redacted from payload")
            if pruned is None and node is not None:
                pruned = CandidateAction(type=ActionType.TOOL_CALL, tool=spec.name, arguments=redacted_args)
        else:
            satisfied.append(Obligation.NO_RESTRICTED_PAYLOAD)
    if node is not None:
        for obligation in node.obligations:
            ok = True
            if obligation is Obligation.VALUES_BOUND:
                broken = _bound(node, action)
                ok = not broken
                notes.extend(broken)
            elif obligation is Obligation.TRUSTED_AUTHORITY:
                ok = not authority.is_untrusted and authority is not Authority.UNKNOWN
            elif obligation is Obligation.PREREQUISITE_FIRED:
                ok = _prerequisite_fired(node, request)
            elif obligation is Obligation.CONFIRMATION_RECORDED:
                ok = confirmed
            elif obligation is Obligation.DESTINATION_IN_ENVELOPE:
                ok = destination is None or graph.envelope.permits_destination(destination, address)
            elif obligation is Obligation.NO_SENSITIVE_OUTWARD:
                outward = destination is Destination.EXTERNAL
                ok = not (outward and overlaps(_payload(action, spec), ws.sensitive))
            (satisfied if ok else violated).append(obligation)
    elif spec.destination_arg and destination is Destination.EXTERNAL and overlaps(_payload(action, spec), ws.sensitive):
        violated.append(Obligation.NO_SENSITIVE_OUTWARD)

    return MonitorResult(
        action_type=action.type, tool=spec.name, node_id=node.id if node else None, effect=effect,
        divergence=divergence, authority=authority, authority_evidence=evidence,
        destination=destination, address=address, confirmed=confirmed, mirrored=mirrored,
        satisfied=tuple(satisfied), violated=tuple(violated), pruned=pruned, notes=tuple(notes),
    )


def _payload(action: CandidateAction, spec: ToolSpec) -> str:
    return "\n".join(str(action.arguments.get(a) or "") for a in spec.payload_args)


def _prune(
    graph: PlanGraph, spec: ToolSpec, effect: Effect, override, action: CandidateAction, allowed: list[str],
    destination: Destination | None, address: str | None,
) -> CandidateAction | None:
    """The safe subplan: the same action with its unsafe branch removed, if the graph has a node for it."""
    if destination is not None and not graph.envelope.permits_destination(destination, address):
        return None  # pruning the effect does not fix a destination outside the envelope
    if override is not None and override.prunable:
        args = {k: v for k, v in action.arguments.items() if k != override.arg}
        if args and graph.node_for(spec.name, spec.effect) is not None and graph.envelope.permits_effect(spec.effect):
            return CandidateAction(type=ActionType.TOOL_CALL, tool=spec.name, arguments=args)
    if spec.prunes_to and spec.prunes_to in allowed:
        sibling = spec_for(spec.prunes_to)
        if sibling and graph.node_for(sibling.name, sibling.effect) is not None:
            return CandidateAction(type=ActionType.TOOL_CALL, tool=sibling.name, arguments=dict(action.arguments))
    return None
