"""Tool catalogue: the one place tool names are mapped onto effects.

This table is part of the trusted computing base. A mislabelled tool is a hole. Keep it short
enough to audit in one sitting. Everything downstream reasons over ``Effect`` only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from giraph.envelope import Effect

# Argument names → entity ID pattern. Used to bind plan values from the trusted request.
ID_PATTERNS: dict[str, str] = {
    "customer_id": r"CU-\d{4}",
    "account_id": r"ACC-\d{4}",
    "beneficiary_id": r"BEN-\d{2,4}",
    "case_id": r"CASE-\d{4}",
    "doc_id": r"(?:CD|DOC)-\d{2,4}",
    "payment_id": r"PAY-\d{4}",
    "email_id": r"EM-\d{4}",
    "ticket_id": r"TCK-\d{3,4}",
    "alert_id": r"AL-\d{4}",
    "asset_id": r"(?:WS|SRV|FW)-\d{2,4}",
    "incident_id": r"INC-\d{4}",
    "remediation_id": r"REM-\d{4}",
}
EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
# Standalone numbers only: never digits that are part of an identifier or a date.
AMOUNT_PATTERN = r"(?<![\w\-./])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w\-./])|(?<![\w\-./])\d+(?:\.\d+)?(?![\w\-./])"


@dataclass(frozen=True)
class Request:
    """How a trusted request would ask for this effect: a verb, optionally near a noun."""

    verbs: tuple[str, ...]
    nouns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Override:
    """An argument value that changes the tool's effect (closing a ticket is not updating it)."""

    arg: str
    values: frozenset[str]
    effect: Effect
    request: Request | None = None
    prunable: bool = True  # dropping the argument leaves a valid call with the tool's base effect


@dataclass(frozen=True)
class ToolSpec:
    name: str
    effect: Effect
    request: Request | None = None
    overrides: tuple[Override, ...] = ()
    destination_arg: str | None = None  # argument holding an address that decides the destination
    payload_args: tuple[str, ...] = ()  # free-text arguments that carry data outward
    produces: tuple[str, ...] = ()  # argument names whose values this tool's result creates
    requires: tuple[str, ...] = ()  # tools that must have fired earlier in the same task
    prunes_to: str | None = None  # a reversible sibling the same arguments can be routed to
    args: tuple[str, ...] = field(default_factory=tuple)

    def effect_for(self, arguments: dict[str, object]) -> tuple[Effect, Override | None]:
        for override in self.overrides:
            value = arguments.get(override.arg)
            if isinstance(value, str) and value in override.values:
                return override.effect, override
        return self.effect, None


_T = ToolSpec
_CLOSE = Request(verbs=("close", "resolve"))
_PAY_NOUNS = ("payment", "refund", "transfer", "settlement", "it")

CATALOGUE: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        # ---- enterprise --------------------------------------------------------------------
        _T("email_search", Effect.READ, args=("query", "limit")),
        _T("email_read", Effect.READ, args=("email_id",)),
        _T(
            "email_draft",
            Effect.PREPARE,
            destination_arg="to",
            payload_args=("subject", "body"),
            args=("to", "subject", "body"),
        ),
        _T(
            "email_send",
            Effect.OUTWARD_SEND,
            request=Request(verbs=("send", "forward", "email"), nouns=()),
            destination_arg="to",
            payload_args=("subject", "body"),
            prunes_to="email_draft",
            args=("to", "subject", "body"),
        ),
        _T("document_search", Effect.READ, args=("query", "limit")),
        _T("document_read", Effect.READ, args=("doc_id",)),
        _T("wiki_search", Effect.READ, args=("query", "limit")),
        _T("ticket_read", Effect.READ, args=("ticket_id",)),
        _T(
            "ticket_update",
            Effect.RECORD,
            overrides=(
                Override("status", frozenset({"closed", "resolved"}), Effect.COMMIT, Request(_CLOSE.verbs, ("ticket",))),
            ),
            payload_args=("note",),
            args=("ticket_id", "status", "note", "assignee"),
        ),
        # ---- finance -----------------------------------------------------------------------
        _T("customer_lookup", Effect.READ, args=("customer_id",)),
        _T("account_summary", Effect.READ, args=("account_id",)),
        _T("case_document_read", Effect.READ, args=("case_id", "doc_id")),
        _T("case_note_create", Effect.RECORD, payload_args=("text",), args=("case_id", "text")),
        _T("policy_search", Effect.READ, args=("query",)),
        _T(
            "payment_prepare",
            Effect.PREPARE,
            produces=("payment_id",),
            args=("account_id", "beneficiary_id", "amount", "reference"),
        ),
        _T(
            "payment_confirm",
            Effect.COMMIT,
            request=Request(verbs=("confirm", "approve"), nouns=_PAY_NOUNS),
            requires=("payment_prepare",),
            args=("payment_id",),
        ),
        _T(
            "payment_execute",
            Effect.COMMIT,
            request=Request(verbs=("execute", "release", "pay"), nouns=_PAY_NOUNS),
            requires=("payment_confirm",),
            args=("payment_id",),
        ),
        # ---- soc ---------------------------------------------------------------------------
        _T("alert_search", Effect.READ, args=("query",)),
        _T("alert_read", Effect.READ, args=("alert_id",)),
        _T("asset_lookup", Effect.READ, args=("asset_id",)),
        _T("intel_search", Effect.READ, args=("query",)),
        _T(
            "incident_create",
            Effect.RECORD,
            payload_args=("title", "summary"),
            args=("alert_id", "title", "severity", "summary"),
        ),
        _T(
            "incident_update",
            Effect.RECORD,
            overrides=(Override("status", frozenset({"closed"}), Effect.COMMIT, Request(_CLOSE.verbs, ("incident",))),),
            payload_args=("note",),
            args=("incident_id", "status", "note"),
        ),
        _T(
            "remediation_prepare",
            Effect.PREPARE,
            overrides=(Override("action", frozenset({"disable_monitoring"}), Effect.DISABLE_CONTROL, prunable=False),),
            produces=("remediation_id",),
            args=("asset_id", "action", "justification"),
        ),
        _T(
            "remediation_execute",
            Effect.COMMIT,
            request=Request(
                verbs=("execute", "isolate", "apply", "run", "contain"),
                nouns=("isolation", "remediation", "host", "containment", "it"),
            ),
            requires=("remediation_prepare",),
            args=("remediation_id",),
        ),
    )
}

# Any argument name that names an entity binds to the request through its ID pattern.
ID_REGEX: dict[str, re.Pattern[str]] = {arg: re.compile(p) for arg, p in ID_PATTERNS.items()}
EMAIL_REGEX = re.compile(EMAIL_PATTERN)


def spec_for(tool: str | None) -> ToolSpec | None:
    return CATALOGUE.get(tool) if tool else None
