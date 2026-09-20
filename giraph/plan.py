"""Planner: turns a trusted request into a frozen plan graph before any untrusted content is read.

Input: the user request, the policy context, the tool catalogue. Nothing else.
The planner enumerates over *types* and *effects*, never over values it has not seen in the request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from giraph.catalogue import AMOUNT_PATTERN, CATALOGUE, EMAIL_REGEX, ID_REGEX, Request, ToolSpec, spec_for
from giraph.envelope import IRREVERSIBLE, Authority, Destination, Effect, Envelope, Sensitivity


class ChosenBy(StrEnum):
    AGENT = "AGENT"  # one safe path suffices
    DATA = "DATA"  # every path must be safe; the adversary picks


class Obligation(StrEnum):
    CONFIRMATION_RECORDED = "CONFIRMATION_RECORDED"  # a human confirmation digest must exist
    PREREQUISITE_FIRED = "PREREQUISITE_FIRED"  # the prepare step ran earlier in this task
    VALUES_BOUND = "VALUES_BOUND"  # entity args must equal the request's bindings
    TRUSTED_AUTHORITY = "TRUSTED_AUTHORITY"  # driving values may not be authored by untrusted content
    NO_SENSITIVE_OUTWARD = "NO_SENSITIVE_OUTWARD"  # payload must not carry data above envelope.data_out
    DESTINATION_IN_ENVELOPE = "DESTINATION_IN_ENVELOPE"
    NO_UNTRUSTED_COPY = "NO_UNTRUSTED_COPY"  # content may not be a verbatim copy of untrusted text


class PlanNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    tool: str | None  # None for respond / memory_write nodes
    effect: Effect
    chosen_by: ChosenBy
    requested: bool  # the trusted request explicitly asked for this step
    bindings: dict[str, tuple[str, ...]] = Field(default_factory=dict)  # arg → allowed values
    data_args: tuple[str, ...] = ()  # args whose value must come from a prior tool result
    obligations: tuple[Obligation, ...] = ()
    requires: tuple[str, ...] = ()


class PlanGraph(BaseModel):
    """Verified once, then read-only. The monitor holds a reference; nothing writes back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_digest: str
    planner: str
    envelope: Envelope
    nodes: tuple[PlanNode, ...]
    entities: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def node_for(self, tool: str | None, effect: Effect | None = None) -> PlanNode | None:
        for node in self.nodes:
            if node.tool == tool and (effect is None or node.effect is effect):
                return node
        return None

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Planner(Protocol):
    name: str

    def plan(self, goal: str, policy_context: dict[str, Any]) -> PlanGraph: ...


# ---- request analysis ---------------------------------------------------------------------------

_NEGATION = re.compile(
    r"\b(?:do not|don't|dont|never|without|must not|mustn't|should not|shouldn't|not to|no need to|"
    r"avoid|refrain from|hold off(?: on)?)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\s+--\s+|\n+")
_CLAUSE_SPLIT = re.compile(r",\s+(?:and|but|then)\s+|;\s+")


class RequestAnalysis(BaseModel):
    """What the trusted request asks for, in catalogue terms. Produced by either planner."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requested: frozenset[str] = frozenset()  # "tool" or "tool:arg=value" for overrides
    negated: frozenset[str] = frozenset()
    entities: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    external_targets: frozenset[str] = frozenset()
    amounts: tuple[str, ...] = ()


def _stem(word: str) -> str:
    return re.sub(r"(ing|ed|es|s)$", "", word.lower())


def _mentions(text: str, request: Request) -> bool:
    words = {_stem(w) for w in re.findall(r"[a-z]+", text.lower())}
    if not any(_stem(v) in words for v in request.verbs):
        return False
    return not request.nouns or any(_stem(n) in words for n in request.nouns)


def _split_negation(clause: str) -> tuple[str, str]:
    """Return (affirmed text, negated text) for one clause."""
    match = _NEGATION.search(clause)
    if match is None:
        return clause, ""
    return clause[: match.start()], clause[match.end() :]


def _requests_in(spec: ToolSpec) -> list[tuple[str, Request]]:
    keys: list[tuple[str, Request]] = []
    if spec.request is not None:
        keys.append((spec.name, spec.request))
    for override in spec.overrides:
        if override.request is not None:
            for value in sorted(override.values):
                keys.append((f"{spec.name}:{override.arg}={value}", override.request))
    return keys


def analyse_request(goal: str, allowed_tools: list[str]) -> RequestAnalysis:
    """Deterministic reading of the request. Only verbs near nouns count; negation scopes to the clause."""
    requested: set[str] = set()
    negated: set[str] = set()
    clauses = [c for s in _SENTENCE_SPLIT.split(goal) for c in _CLAUSE_SPLIT.split(s) if c.strip()]
    for tool in allowed_tools:
        spec = spec_for(tool)
        if spec is None:
            continue
        for key, request in _requests_in(spec):
            for clause in clauses:
                affirmed, denied = _split_negation(clause)
                if denied and _mentions(denied, Request(request.verbs)):
                    negated.add(key)
                elif _mentions(affirmed, request):
                    requested.add(key)
    entities: dict[str, tuple[str, ...]] = {}
    for arg, regex in ID_REGEX.items():
        found = tuple(dict.fromkeys(regex.findall(goal)))
        if found:
            entities[arg] = found
    amounts = tuple(dict.fromkeys(m.replace(",", "").replace(" ", "") for m in re.findall(AMOUNT_PATTERN, goal)))
    targets = frozenset(a.lower() for a in EMAIL_REGEX.findall(goal))
    return RequestAnalysis(
        requested=frozenset(requested - negated),
        negated=frozenset(negated),
        entities=entities,
        external_targets=targets,
        amounts=amounts,
    )


# ---- graph construction --------------------------------------------------------------------------


def _obligations(spec: ToolSpec, effect: Effect, consequential: bool, requires_confirmation: bool) -> tuple[Obligation, ...]:
    obligations: list[Obligation] = [Obligation.VALUES_BOUND, Obligation.TRUSTED_AUTHORITY]
    if spec.requires:
        obligations.append(Obligation.PREREQUISITE_FIRED)
    if consequential or requires_confirmation or effect.irreversible:
        obligations.append(Obligation.CONFIRMATION_RECORDED)
    if spec.destination_arg:
        obligations.append(Obligation.DESTINATION_IN_ENVELOPE)
        obligations.append(Obligation.NO_SENSITIVE_OUTWARD)
    return tuple(obligations)


def build_graph(goal: str, policy_context: dict[str, Any], analysis: RequestAnalysis, planner: str) -> PlanGraph:
    allowed: list[str] = list(policy_context.get("allowed_tools", []))
    consequential = set(policy_context.get("consequential_tools", []))
    confirm_required = set(policy_context.get("confirmation_required_tools", []))
    notes: list[str] = []

    effects: set[Effect] = {Effect.READ, Effect.RESPOND, Effect.MEMORY_WRITE}
    denied_effects: set[Effect] = set()
    denied_tools: set[str] = set()
    nodes: list[PlanNode] = []

    for index, tool in enumerate(allowed):
        spec = spec_for(tool)
        if spec is None:
            notes.append(f"{tool}: not in catalogue, no node")
            continue
        variants: list[tuple[str, Effect]] = [(spec.name, spec.effect)]
        variants.extend((f"{spec.name}:{o.arg}={v}", o.effect) for o in spec.overrides for v in sorted(o.values))
        for key, effect in variants:
            if key in analysis.negated:
                notes.append(f"{key}: denied by request")
                if key == spec.name:
                    denied_tools.add(spec.name)
                    if effect.irreversible:
                        denied_effects.add(effect)
                continue
            requested = key in analysis.requested
            if effect.irreversible and not requested:
                notes.append(f"{key}: irreversible, not requested → outside envelope")
                continue
            if effect is Effect.DISABLE_CONTROL:
                notes.append(f"{key}: disabling a control is never planner-authorised")
                continue
            effects.add(effect)
            bindings = {arg: analysis.entities[arg] for arg in spec.args if arg in analysis.entities}
            if "amount" in spec.args and analysis.amounts:
                bindings["amount"] = analysis.amounts
            data_args = tuple(a for a in spec.args if a not in bindings and a.endswith("_id"))
            chosen = ChosenBy.DATA if data_args or spec.produces else ChosenBy.AGENT
            nodes.append(
                PlanNode(
                    id=f"N{index}" if key == spec.name else f"N{index}:{key.split(':', 1)[1]}",
                    tool=spec.name,
                    effect=effect,
                    chosen_by=chosen,
                    requested=requested or not effect.irreversible,
                    bindings=bindings,
                    data_args=data_args,
                    obligations=_obligations(spec, effect, tool in consequential, tool in confirm_required),
                    requires=spec.requires,
                )
            )

    nodes.append(
        PlanNode(id="R", tool=None, effect=Effect.RESPOND, chosen_by=ChosenBy.AGENT, requested=True,
                 obligations=(Obligation.NO_SENSITIVE_OUTWARD,))
    )
    nodes.append(
        PlanNode(id="M", tool=None, effect=Effect.MEMORY_WRITE, chosen_by=ChosenBy.AGENT, requested=True,
                 obligations=(Obligation.NO_UNTRUSTED_COPY,))
    )

    destinations = {Destination.INTERNAL, Destination.PRINCIPAL}
    if analysis.external_targets:
        destinations.add(Destination.EXTERNAL)
    # Denied effects are per-tool; the envelope-wide denial only applies when every tool with that
    # effect was denied, otherwise "do not execute" would also forbid a requested "confirm".
    envelope = Envelope(
        effects=frozenset(effects),
        destinations=frozenset(destinations),
        external_targets=analysis.external_targets,
        data_out=Sensitivity.INTERNAL,
        max_authority=Authority.AGENT,
        denied_effects=frozenset(e for e in denied_effects if e not in effects),
        denied_tools=frozenset(denied_tools),
        reasons=tuple(notes),
    )
    return PlanGraph(
        goal_digest=hashlib.sha256(goal.encode()).hexdigest()[:16],
        planner=planner,
        envelope=envelope,
        nodes=tuple(nodes),
        entities=analysis.entities,
        notes=tuple(notes),
    )


# ---- planners -----------------------------------------------------------------------------------


class DeterministicPlanner:
    name = "deterministic"

    def plan(self, goal: str, policy_context: dict[str, Any]) -> PlanGraph:
        analysis = analyse_request(goal, list(policy_context.get("allowed_tools", [])))
        return build_graph(goal, policy_context, analysis, self.name)


_LLM_PROMPT = """You are the planning stage of a security monitor for a tool-using assistant.
You see ONLY the user's request and the tools it may use. Decide, from the request alone:

1. "requested": which of these irreversible steps the user explicitly asked for.
2. "negated": which of these steps the user explicitly told the assistant NOT to do.
3. "external_targets": email addresses the user explicitly named as recipients.

Irreversible steps (use these exact keys): {keys}
Allowed tools: {tools}

Rules: only list keys from the list above. When unsure, leave a key out of "requested".
A step named under "negated" must never appear under "requested".
Answer with one JSON object and nothing else:
{{"requested": [], "negated": [], "external_targets": []}}

User request:
\"\"\"{goal}\"\"\"
"""


class _LLMAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested: list[str] = Field(default_factory=list)
    negated: list[str] = Field(default_factory=list)
    external_targets: list[str] = Field(default_factory=list)


class LLMPlanner:
    """Same graph constructor; the reading of the request comes from a local model.

    The model's answer is clamped: it may only name keys the catalogue defines for allowed tools,
    and it may only *narrow* what the deterministic reading found for negations (a negation the
    model adds is kept; a negation it drops is not). Any failure falls back to the deterministic planner.
    """

    name = "llm"

    def __init__(self, complete: Any | None = None, url: str | None = None, model: str | None = None) -> None:
        self._complete = complete or _openai_compatible(url, model)
        self._fallback = DeterministicPlanner()

    def plan(self, goal: str, policy_context: dict[str, Any]) -> PlanGraph:
        allowed = list(policy_context.get("allowed_tools", []))
        baseline = analyse_request(goal, allowed)
        keys = sorted(k for t in allowed if (s := spec_for(t)) for k, _ in _requests_in(s))
        try:
            raw = self._complete(_LLM_PROMPT.format(keys=keys, tools=allowed, goal=goal))
            answer = _LLMAnswer.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError, OSError) as exc:
            graph = self._fallback.plan(goal, policy_context)
            return graph.model_copy(update={"planner": "deterministic(fallback)", "notes": graph.notes + (f"llm planner failed: {type(exc).__name__}",)})
        valid = set(keys)
        negated = baseline.negated | (set(answer.negated) & valid)
        requested = (set(answer.requested) & valid) - negated
        targets = baseline.external_targets | frozenset(t.lower() for t in answer.external_targets if EMAIL_REGEX.fullmatch(t))
        analysis = baseline.model_copy(update={"requested": frozenset(requested), "negated": frozenset(negated), "external_targets": targets})
        return build_graph(goal, policy_context, analysis, self.name)


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return text[start : end + 1]


def _openai_compatible(url: str | None, model: str | None):
    """Chat-completions client for llama.cpp / Ollama / vLLM. Imported lazily; never used in tests."""
    import httpx

    base = (url or os.environ.get("GIRAPH_LLM_URL", "http://127.0.0.1:11434/v1")).rstrip("/")
    name = model or os.environ.get("GIRAPH_LLM_MODEL", "qwen3:8b")

    def complete(prompt: str) -> str:
        response = httpx.post(
            f"{base}/chat/completions",
            json={"model": name, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 400},
            timeout=60.0,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])

    return complete


def planner_from_env() -> Planner:
    if os.environ.get("GIRAPH_PLANNER", "deterministic").lower() == "llm":
        return LLMPlanner()
    return DeterministicPlanner()
