"""In-process adapter so the SENTINEL simulator can drive GIRAPH without HTTP.

Only this file imports ``sentinel``. It converts between the kit's models and GIRAPH's mirror of
the same contract by round-tripping JSON, so a schema drift fails loudly instead of silently.
"""

from __future__ import annotations

from sentinel.core.actions import DefenseDecision as KitDecision
from sentinel.defenses.interface import Defense, DefenseRequest as KitRequest

from giraph.defense import Giraph
from giraph.schema import DefenseRequest


class GiraphDefense(Defense):
    name = "giraph"

    def __init__(self, giraph: Giraph | None = None) -> None:
        self.giraph = giraph or Giraph()

    def decide(self, request: KitRequest) -> KitDecision:
        mirrored = DefenseRequest.model_validate(request.model_dump(mode="json"))
        decision = self.giraph.decide(mirrored)
        return KitDecision.model_validate(decision.model_dump(mode="json"))
