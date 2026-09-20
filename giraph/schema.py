"""Wire contract with the SENTINEL harness (``POST /v1/decision``). Mirrors the kit's models so
GIRAPH has no import dependency on the simulator."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ArgValue = str | int | float | bool | None
REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class ActionType(StrEnum):
    RESPOND = "respond"
    TOOL_CALL = "tool_call"
    MEMORY_WRITE = "memory_write"
    REQUEST_CONFIRMATION = "request_confirmation"


class CandidateAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ActionType
    tool: str | None = None
    arguments: dict[str, ArgValue] = Field(default_factory=dict)
    content: str | None = None
    final: bool = False
    confirmation_for: CandidateAction | None = None

    def digest(self) -> str:
        """Identical to the harness digest so confirmations line up."""
        payload: dict[str, Any] = {
            "type": self.type.value,
            "tool": self.tool,
            "arguments": {k: _canonical(v) for k, v in sorted(self.arguments.items())},
            "content": self.content if self.type is not ActionType.TOOL_CALL else None,
        }
        if self.confirmation_for is not None:
            payload["confirmation_for"] = self.confirmation_for.digest()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()[:24]

    def text_payload(self) -> str:
        parts: list[str] = []
        if self.content:
            parts.append(self.content)
        parts.extend(str(v) for v in self.arguments.values() if v is not None)
        if self.confirmation_for is not None:
            parts.append(self.confirmation_for.text_payload())
        return "\n".join(parts)


def _canonical(value: ArgValue) -> ArgValue:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class ProvenanceView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    source_type: str
    source_id: str
    trust_level: str
    origin_actor: str
    retrieved_via: str
    sensitivity: str = "internal"


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    provenance: ProvenanceView


class ConversationItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    role: str
    kind: str
    content: str
    provenance_ids: list[str] = Field(default_factory=list)


class ToolCallSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    step_id: int
    tool: str
    decision: str
    succeeded: bool | None = None


class HistoryDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    steps_taken: int = 0
    turn_index: int = 0
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    confirmations_granted: list[str] = Field(default_factory=list)
    blocked_count: int = 0
    escalated_count: int = 0
    least_trusted_seen: str | None = None
    most_sensitive_seen: str | None = None


class DefenseRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    run_id: str
    step_id: int
    user_goal: str
    conversation: list[ConversationItem] = Field(default_factory=list)
    observation: Any | None = None
    candidate_action: CandidateAction
    policy_context: dict[str, Any] = Field(default_factory=dict)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    history_digest: HistoryDigest = Field(default_factory=HistoryDigest)


class Decision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"
    REWRITE = "rewrite"


class DefenseDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    risk_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list, max_length=16)
    explanation: str | None = Field(default=None, max_length=500)
    rewritten_action: CandidateAction | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reason_codes")
    @classmethod
    def _codes(cls, codes: list[str]) -> list[str]:
        for code in codes:
            if not REASON_CODE.fullmatch(code):
                raise ValueError(f"invalid reason code {code!r}")
        return codes

    @model_validator(mode="after")
    def _rewrite(self) -> Self:
        if (self.decision is Decision.REWRITE) != (self.rewritten_action is not None):
            raise ValueError("rewritten_action iff decision is rewrite")
        return self
