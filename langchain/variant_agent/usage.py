from __future__ import annotations

from typing import Any, Dict

from langchain.callbacks.base import BaseCallbackHandler

from .models import UsageMetrics


class UsageTracker:
    # Aggregates token usage across multiple LLM calls.

    # Initialise counters for token usage categories.
    def __init__(self) -> None:
        self._input_tokens = 0
        self._output_tokens = 0
        self._reasoning_tokens = 0
        self._total_tokens = 0

    # Add usage information extracted from OpenAI metadata payloads.
    def add_from_metadata(self, metadata: Dict[str, Any]) -> None:
        usage = metadata.get("token_usage") or metadata.get("usage") or {}
        input_tokens = _to_int(
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("completion_tokens_in")
        )
        output_tokens = _to_int(
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("completion_tokens_out")
        )
        reasoning_tokens = _to_int(
            usage.get("reasoning_tokens") or usage.get("output_tokens_details", {}).get("reasoning_tokens")
        )
        total_tokens = _to_int(usage.get("total_tokens"))

        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        self._reasoning_tokens += reasoning_tokens

        if total_tokens:
            self._total_tokens += total_tokens
        else:
            combined = input_tokens + output_tokens + reasoning_tokens
            if combined:
                self._total_tokens += combined

    # Return a snapshot of the aggregated usage totals.
    def snapshot(self) -> UsageMetrics:
        return UsageMetrics(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            reasoning_tokens=self._reasoning_tokens,
            total_tokens=self._total_tokens,
        )


class UsageCallbackHandler(BaseCallbackHandler):
    # Callback that captures token usage distilled by LangChain.

    # Store a reference to the shared tracker.
    def __init__(self, tracker: UsageTracker):
        super().__init__()
        self._tracker = tracker

    # Update the tracker whenever LangChain reports LLM usage metrics.
    def on_llm_end(self, response, **kwargs):  # type: ignore[override]
        metadata = getattr(response, "llm_output", None) or {}
        if isinstance(metadata, dict):
            self._tracker.add_from_metadata(metadata)


# Safely coerce numeric token values to integers.
def _to_int(value: Any) -> int:
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return 0
        if parsed >= 0:
            return int(parsed)
    return 0

