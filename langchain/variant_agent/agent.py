from __future__ import annotations

import json
import time
from typing import Any, Dict, TypedDict

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from openai import BadRequestError

from .config import Settings
from .models import VariantResponse
from .tools import build_tools
from .usage import UsageCallbackHandler, UsageTracker


class AgentResult(TypedDict):
    payload: Dict[str, Any]
    usage: Dict[str, int]
    elapsed_ms: int
    intermediate_steps: Any


# Factory that wraps the LangChain agent workflow.
class VariantGenerationAgent:
    # Initialise the agent with configuration and dedicated planner/tool LLMs.
    def __init__(self, settings: Settings):
        self._settings = settings
        self._base_llm_kwargs = {
            "model": settings.openai_model,
            "max_tokens": 2048,
        }
        if settings.openai_temperature is not None:
            self._base_llm_kwargs["temperature"] = settings.openai_temperature
        self._base_llm_kwargs["openai_api_key"] = settings.openai_api_key
        if settings.openai_base_url:
            self._base_llm_kwargs["openai_api_base"] = settings.openai_base_url

        self._streaming_enabled = bool(settings.openai_stream)
        self._init_llms(self._streaming_enabled)

    # Run the agent toolkit to generate variant questions for an input prompt.
    def generate(self, original_question: str, num_variants: int) -> AgentResult:
        if num_variants < 1 or num_variants > 5:
            raise ValueError("`num` must be between 1 and 5.")
        usage_tracker = UsageTracker()
        # Build tool instances that share the tool LLM so token usage is centralised.
        tools = build_tools(
            tool_llm=self._tool_llm,
            usage_tracker=usage_tracker,
            log_intermediate=self._settings.log_intermediate,
        )

        prompt = self._build_prompt()
        # Construct a runnable agent chain with OpenAI tool-calling support.
        agent_runnable = create_openai_tools_agent(self._planner_llm, tools, prompt)

        executor = AgentExecutor(
            agent=agent_runnable,
            tools=tools,
            verbose=self._settings.log_intermediate,
            max_iterations=12,
            return_intermediate_steps=True,
            stream_runnable=False,
        )

        callbacks = [UsageCallbackHandler(usage_tracker)]
        start = time.perf_counter()
        # Kick off the agent loop, seeding context inputs for the workflow.
        try:
            result = executor.invoke(
                {
                    "input": "Begin the variant generation workflow.",
                    "original_question": original_question,
                    "target_count": num_variants,
                },
                config={"callbacks": callbacks},
            )
        except BadRequestError as exc:
            if self._streaming_enabled and self._should_retry_without_streaming(exc):
                if self._settings.log_intermediate:
                    print("[agent] Streaming unsupported; retrying without streaming.")
                self._init_llms(False)
                return self.generate(original_question, num_variants)
            raise

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        output_text = result.get("output", "")
        payload = self._parse_agent_output(output_text)

        if not payload:
            raise RuntimeError("Agent failed to return a valid JSON payload.")

        # Normalise structure and enforce expected variant count.
        payload = self._post_process_payload(payload, num_variants)
        payload["time"] = elapsed_ms
        payload["usage"] = usage_tracker.snapshot().model_dump()

        return AgentResult(
            payload=payload,
            usage=payload["usage"],
            elapsed_ms=elapsed_ms,
            intermediate_steps=result.get("intermediate_steps"),
        )

    # Build planner/tool LLM instances with the desired streaming configuration.
    def _init_llms(self, streaming: bool) -> None:
        init_kwargs = self._base_llm_kwargs.copy()
        init_kwargs["streaming"] = streaming
        # LLM for planning/thinking.
        self._planner_llm = ChatOpenAI(**init_kwargs)
        # Separate LLM instance for tool calls (avoids throttling shared state).
        self._tool_llm = ChatOpenAI(**init_kwargs)
        self._streaming_enabled = streaming

    # Build the system + human prompt that constrains the agent workflow.
    def _build_prompt(self) -> ChatPromptTemplate:
        system_message = (
            "You are LangChain Agent DK-Variant tasked with generating alternative Australian DKT exam "
            "questions. Follow this strict workflow:\n"
            "1. Always call `analyze_topic` first to understand the knowledge point.\n"
            "2. Call `plan_variations` to decide how many variants to create (exactly as requested).\n"
            "3. For each planned variation, call `generate_question` to create a new single-choice question "
            "with four options A-D that matches the language of the original question.\n"
            "4. Immediately call `validate_question` on each generated question. If the validation is invalid, "
            "fix the issue by generating a revised question and re-validating.\n"
            "5. When all variants are ready, produce a final JSON object with keys "
            "`knowledge_point_name`, `knowledge_point_summary`, and `variant_questions` "
            "(array of objects each with `prompt`, `option_a`, `option_b`, `option_c`, `option_d`, "
            "`correct_option`, `explanation`). Do not include any other text.\n"
            "Respect the requested variant count. Maintain the same language (English, Chinese, etc.) as "
            "the learner's question. Never mention that you are using tools."
        )

        human_template = (
            "{input}\n\n"
            "Original question:\n"
            "{original_question}\n\n"
            "Required number of variants: {target_count}\n"
            "Proceed with the workflow and return the final JSON response."
        )

        return ChatPromptTemplate.from_messages(
            [
                ("system", system_message),
                ("human", human_template),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )

    # Parse the agent's textual response into a Python dictionary.
    def _parse_agent_output(self, output_text: Any) -> Dict[str, Any]:
        if isinstance(output_text, dict):
            return output_text
        if not isinstance(output_text, str):
            return {}
        text = output_text.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return {}
        return {}

    # Ensure the payload contains the requested number of variants with clean fields.
    def _post_process_payload(self, payload: Dict[str, Any], num_variants: int) -> Dict[str, Any]:
        knowledge_point_name = payload.get("knowledge_point_name") or ""
        knowledge_point_summary = payload.get("knowledge_point_summary") or ""
        variants = payload.get("variant_questions") or []
        if not isinstance(variants, list):
            variants = []

        normalised_variants = []
        for item in variants:
            # Skip malformed entries and coerce each field into the expected structure.
            if not isinstance(item, dict):
                continue
            normalised = {
                "prompt": item.get("prompt", "").strip(),
                "option_a": item.get("option_a", "").strip(),
                "option_b": item.get("option_b", "").strip(),
                "option_c": item.get("option_c", "").strip(),
                "option_d": item.get("option_d", "").strip(),
                "correct_option": (item.get("correct_option") or "").strip().upper()[:1],
                "explanation": item.get("explanation", "").strip(),
            }
            if normalised["correct_option"] not in {"A", "B", "C", "D"}:
                raise RuntimeError("Agent produced an invalid correct option label.")
            if not normalised["prompt"]:
                raise RuntimeError("Agent returned an empty prompt.")
            normalised_variants.append(normalised)

        if len(normalised_variants) > num_variants:
            normalised_variants = normalised_variants[:num_variants]

        if len(normalised_variants) < num_variants:
            raise RuntimeError(
                f"Agent returned {len(normalised_variants)} variants but {num_variants} were requested."
            )

        return {
            "knowledge_point_name": knowledge_point_name,
            "knowledge_point_summary": knowledge_point_summary,
            "variant_questions": normalised_variants,
        }


    # Detect OpenAI errors that indicate streaming is not permitted.
    def _should_retry_without_streaming(self, exc: BadRequestError) -> bool:
        error_message = ""
        try:
            error_message = exc.body.get("error", {}).get("message", "")  # type: ignore[attr-defined]
        except Exception:
            error_message = ""
        combined = f"{error_message} {exc}".lower()
        return "stream" in combined and ("verify" in combined or "unsupported" in combined)


# Convert dict payload into the typed VariantResponse model.
def build_variant_response(data: Dict[str, Any]) -> VariantResponse:
    return VariantResponse.model_validate(data)
