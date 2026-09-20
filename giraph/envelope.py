"""Effect schema. Policy is written over effects, never over tool names.

Nothing in this file mentions email, payments, or incidents.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Effect(StrEnum):
    READ = "read"  # observe state
    PREPARE = "prepare"  # stage something reversible (a draft, a prepared payment)
    RECORD = "record"  # append an internal note; reversible, stays inside
    COMMIT = "commit"  # irreversible state change (execute, close, confirm)
    OUTWARD_SEND = "outward_send"  # data leaves the organisation
    READ_CREDENTIAL = "read_credential"  # secrets become visible to the agent
    DISABLE_CONTROL = "disable_control"  # a safety control is switched off
    MEMORY_WRITE = "memory_write"  # persists across turns; a future authoring channel
    RESPOND = "respond"  # reply to the principal

    @property
    def irreversible(self) -> bool:
        return self in IRREVERSIBLE


IRREVERSIBLE = frozenset({Effect.COMMIT, Effect.OUTWARD_SEND, Effect.READ_CREDENTIAL, Effect.DISABLE_CONTROL})
REVERSIBLE = frozenset(e for e in Effect if e not in IRREVERSIBLE)


class Authority(StrEnum):
    """Who authored the values that drive an action. Ordered most to least trusted."""

    SYSTEM_POLICY = "system_policy"
    AUTHENTICATED_USER = "authenticated_user"
    TRUSTED_INTERNAL = "trusted_internal"
    AGENT = "agent"  # free text the agent composed; traceable to nothing in particular
    UNTRUSTED_INTERNAL = "untrusted_internal"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    ADVERSARY_CONTROLLED = "adversary_controlled"
    UNKNOWN = "unknown"  # the checker could not decide

    @property
    def rank(self) -> int:
        return list(Authority).index(self)

    @property
    def is_trusted(self) -> bool:
        return self.rank <= Authority.AGENT.rank

    @property
    def is_untrusted(self) -> bool:
        return Authority.UNTRUSTED_INTERNAL.rank <= self.rank < Authority.UNKNOWN.rank


# Trust levels in the harness map 1:1 onto authority names; memory inherits the trust it was written under.
def authority_from_trust(trust_level: str) -> Authority:
    try:
        return Authority(trust_level)
    except ValueError:
        return Authority.UNKNOWN


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

    @property
    def rank(self) -> int:
        return list(Sensitivity).index(self)


class Destination(StrEnum):
    INTERNAL = "internal"  # stays inside the organisation (notes, drafts, internal mail)
    PRINCIPAL = "principal"  # the user who issued the request
    EXTERNAL = "external"  # leaves the organisation


class Envelope(BaseModel):
    """The authority a verified plan grants. The monitor may only narrow it, never widen it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    effects: frozenset[Effect]
    destinations: frozenset[Destination]
    # External addresses the trusted request named explicitly. Anything else external is outside.
    external_targets: frozenset[str] = frozenset()
    # Most sensitive data class allowed to reach an external destination.
    data_out: Sensitivity = Sensitivity.INTERNAL
    # Least trusted authority allowed to drive an irreversible effect.
    max_authority: Authority = Authority.AGENT
    # Effects the trusted request explicitly forbade ("do not execute"). Never escalatable.
    denied_effects: frozenset[Effect] = frozenset()
    # Tools the request explicitly forbade, for the same reason, keyed by tool name.
    denied_tools: frozenset[str] = frozenset()
    reasons: tuple[str, ...] = Field(default_factory=tuple)

    def permits_effect(self, effect: Effect) -> bool:
        return effect in self.effects and effect not in self.denied_effects

    def permits_destination(self, destination: Destination, address: str | None = None) -> bool:
        if destination is not Destination.EXTERNAL:
            return destination in self.destinations
        if "*" in self.external_targets:  # ablation only: any external address
            return destination in self.destinations
        return destination in self.destinations and address is not None and address.lower() in self.external_targets

    def narrowed(self, *, remove_effects: frozenset[Effect] = frozenset()) -> Envelope:
        """Replanning may only narrow. This is the only mutation path and it subtracts."""
        return self.model_copy(update={"effects": self.effects - remove_effects})
