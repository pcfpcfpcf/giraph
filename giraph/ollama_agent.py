"""The SENTINEL reference agent, run through Ollama instead of in-process transformers.

Same model (Qwen3-8B, 4-bit GGUF), same system prompt, same tool cards, same message layout, same
output parsing as the kit's ``HFModelAdapter`` -- all imported from it, not copied. Only *how* the
weights are executed changes, which the participant guide leaves to each team. No safety
instructions are added: the agent stays the naive thing the defense has to protect.

Declared runtime (for the report): Ollama, ``qwen3:8b`` Q4_K_M, greedy decoding, thinking off,
768-token decode budget, 12 000-char history window (the adapter's defaults).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from sentinel.agent.base import AgentContext, Feedback
from sentinel.core.actions import CandidateAction
from sentinel.models.base import ModelAdapter, ModelError, TurnHints
from sentinel.models.hf_adapter import HFModelAdapter, parse_action


class OllamaModelAdapter(ModelAdapter):
    name = "ollama"

    def __init__(
        self,
        model: str | None = None,
        url: str | None = None,
        max_new_tokens: int = 768,
        max_context_chars: int = 12_000,
        enable_thinking: bool = False,
        num_ctx: int = 8192,
        timeout_s: float = 600.0,
    ) -> None:
        self._model = model or os.environ.get("GIRAPH_AGENT_MODEL", "qwen3:8b")
        self._url = (url or os.environ.get("GIRAPH_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self._max_new_tokens = max_new_tokens
        self._max_context_chars = max_context_chars
        self._enable_thinking = enable_thinking
        self._num_ctx = num_ctx
        self._timeout = timeout_s
        self._goal = ""
        self._tools: list[dict[str, Any]] = []

    # ---- identical to HFModelAdapter -------------------------------------------------------
    def start_turn(self, goal: str, hints: TurnHints) -> None:
        self._goal = goal
        self._tools = hints.tools  # reference_plan is deliberately ignored

    def _messages(self, context: AgentContext) -> list[dict[str, str]]:
        return HFModelAdapter._messages(self, context)  # type: ignore[arg-type]

    # ---- the only difference: where the tokens come from -------------------------------------
    def propose(self, context: AgentContext) -> CandidateAction:
        try:
            response = httpx.post(
                f"{self._url}/api/chat",
                json={
                    "model": self._model,
                    "messages": self._messages(context),
                    "stream": False,
                    "think": self._enable_thinking,
                    "options": {"temperature": 0, "num_predict": self._max_new_tokens, "num_ctx": self._num_ctx},
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            text = str(response.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ModelError(f"ollama: {type(exc).__name__}: {exc}") from exc
        return parse_action(text)

    def observe(self, feedback: Feedback) -> None:
        return None
