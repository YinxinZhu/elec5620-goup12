from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langchain_core.pydantic_v1 import BaseModel, Field, conint
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from .prompts import (
    KNOWLEDGE_POINT_PROMPT,
    VARIANT_GENERATION_PROMPT,
    VARIANT_VALIDATION_PROMPT,
    VARIATION_PLAN_PROMPT,
)
from .usage import UsageTracker


class AnalyzeTopicInput(BaseModel):
    original_question: str = Field(..., description="Original learner question.")


class PlanVariationsInput(BaseModel):
    knowledge_point_name: str
    knowledge_point_summary: str
    variant_count: conint(ge=1, le=5) = Field(
        ..., description="Number of variants to produce (between 1 and 5)."
    )
    original_question: str


class GenerateVariantInput(BaseModel):
    knowledge_point_name: str
    knowledge_point_summary: str
    variation_type: str
    focus: str
    original_question: str


class ValidateVariantInput(BaseModel):
    prompt: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    explanation: str


def build_tools(
    tool_llm: ChatOpenAI,
    usage_tracker: UsageTracker,
    log_intermediate: bool = False,
) -> List[StructuredTool]:
    """Create LangChain tools used by the variant generation agent."""

    def analyze_topic(original_question: str) -> Dict[str, Any]:
        response = _invoke(tool_llm, KNOWLEDGE_POINT_PROMPT, usage_tracker, original_question=original_question)
        payload = _extract_json(response, default={})
        if log_intermediate:
            print("[tool] analyze_topic ->", json.dumps(payload, ensure_ascii=False))
        return payload

    def plan_variations(
        knowledge_point_name: str,
        knowledge_point_summary: str,
        variant_count: int,
        original_question: str,
    ) -> Dict[str, Any]:
        if not 1 <= variant_count <= 5:
            raise ValueError("Variant count must be between 1 and 5.")
        response = _invoke(
            tool_llm,
            VARIATION_PLAN_PROMPT,
            usage_tracker,
            knowledge_point_name=knowledge_point_name,
            knowledge_point_summary=knowledge_point_summary,
            variant_count=variant_count,
            original_question=original_question,
        )
        payload = _extract_json(response, default={"variations": []})
        if log_intermediate:
            print("[tool] plan_variations ->", json.dumps(payload, ensure_ascii=False))
        return payload

    def generate_question(
        knowledge_point_name: str,
        knowledge_point_summary: str,
        variation_type: str,
        focus: str,
        original_question: str,
    ) -> Dict[str, Any]:
        response = _invoke(
            tool_llm,
            VARIANT_GENERATION_PROMPT,
            usage_tracker,
            knowledge_point_name=knowledge_point_name,
            knowledge_point_summary=knowledge_point_summary,
            variation_type=variation_type,
            focus=focus,
            original_question=original_question,
        )
        payload = _extract_json(response, default={})
        if log_intermediate:
            print("[tool] generate_question ->", json.dumps(payload, ensure_ascii=False))
        return payload

    def validate_question(
        prompt: str,
        option_a: str,
        option_b: str,
        option_c: str,
        option_d: str,
        correct_option: str,
        explanation: str,
    ) -> Dict[str, Any]:
        response = _invoke(
            tool_llm,
            VARIANT_VALIDATION_PROMPT,
            usage_tracker,
            prompt=prompt,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_option=correct_option,
            explanation=explanation,
        )
        payload = _extract_json(response, default={"is_valid": True, "feedback": ""})
        if log_intermediate:
            print("[tool] validate_question ->", json.dumps(payload, ensure_ascii=False))
        return payload

    return [
        StructuredTool.from_function(
            name="analyze_topic",
            func=analyze_topic,
            args_schema=AnalyzeTopicInput,
            description="Identify the knowledge point for the original learner question.",
        ),
        StructuredTool.from_function(
            name="plan_variations",
            func=plan_variations,
            args_schema=PlanVariationsInput,
            description="Plan out how each variant will differ while testing the same knowledge.",
        ),
        StructuredTool.from_function(
            name="generate_question",
            func=generate_question,
            args_schema=GenerateVariantInput,
            description="Generate a single new multiple-choice question variant.",
        ),
        StructuredTool.from_function(
            name="validate_question",
            func=validate_question,
            args_schema=ValidateVariantInput,
            description="Validate that a generated variant is coherent and follows the rules.",
        ),
    ]


def _invoke(
    llm: ChatOpenAI,
    prompt: Any,
    usage_tracker: UsageTracker,
    **kwargs: Any,
):
    messages = prompt.format_messages(**kwargs)
    response = llm.invoke(messages)
    metadata = getattr(response, "response_metadata", {}) or {}
    if isinstance(metadata, dict):
        usage_tracker.add_from_metadata(metadata)
    return response


def _extract_json(response: Any, default: Any) -> Any:
    raw_content = getattr(response, "content", "") or ""

    if isinstance(raw_content, list):
        raw_content = "".join(str(part) for part in raw_content)

    if isinstance(raw_content, str):
        raw_content = raw_content.strip()
        if not raw_content:
            return default

        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            match = _find_json_block(raw_content)
            if match:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    pass
    return default


def _find_json_block(text: str) -> str | None:
    """Extract the first likely JSON object from free-form text."""
    stack = []
    start = None
    for idx, char in enumerate(text):
        if char == "{":
            if not stack:
                start = idx
            stack.append(char)
        elif char == "}":
            if stack:
                stack.pop()
                if not stack and start is not None:
                    return text[start : idx + 1]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None
