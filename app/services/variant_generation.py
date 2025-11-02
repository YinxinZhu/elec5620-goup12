"""Helpers for generating AI-powered variant questions.

The application prefers to call the Node.js proxy that wraps an LLM. When the
proxy is disabled (for example during automated tests) we fall back to a local
deterministic generator so the rest of the stack remains functional.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence, Tuple

import requests
from flask import current_app

from ..models import Question

logger = logging.getLogger(__name__)

# Ordered scenarios ensure variant prompts stay reproducible for tests and seed data.
SCENARIO_LABELS: tuple[str, ...] = (
    "wet-weather driving",
    "night conditions",
    "high-traffic commute",
    "regional roads",
    "emergency vehicle approach",
)


class VariantProxyError(RuntimeError):
    """Raised when the external proxy cannot generate variants."""


@dataclass(frozen=True)
class VariantQuestionDraft:
    prompt: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    explanation: str


def _scenario_suffix(index: int) -> str:
    # Rotate through the scenario list instead of relying on randomness.
    return SCENARIO_LABELS[index % len(SCENARIO_LABELS)]


def _format_prompt(base_prompt: str, scenario: str, *, number: int) -> str:
    # Keep the original prompt intact while appending deterministic context.
    return f"{base_prompt} - consider the {scenario} scenario #{number}."


def _format_explanation(base_explanation: str, scenario: str) -> str:
    details = base_explanation.strip() or "Review the core road rule."
    return f"{details} This variation focuses on decisions during {scenario}."


def _generate_local_variants(
    question: Question,
    *,
    count: int,
) -> list[VariantQuestionDraft]:
    """Generate deterministic scenario variations for the supplied question."""

    if count <= 0:
        raise ValueError("count must be positive")

    drafts: list[VariantQuestionDraft] = []
    for index in range(count):
        # Deterministic index ensures repeated requests return identical drafts.
        scenario = _scenario_suffix(index)
        drafts.append(
            VariantQuestionDraft(
                prompt=_format_prompt(question.prompt, scenario, number=index + 1),
                option_a=question.option_a,
                option_b=question.option_b,
                option_c=question.option_c,
                option_d=question.option_d,
                correct_option=question.correct_option,
                explanation=_format_explanation(question.explanation, scenario),
            )
        )
    return drafts


# Shape the question into a compact string consumed by the proxy.
def _compose_question_payload(question: Question) -> str:
    language = (question.language or "ENGLISH").strip().upper()
    lines = [
        f"LANGUAGE: {language}",
        f"QUESTION: {question.prompt.strip()}",
        "OPTIONS:",
        f"A. {question.option_a.strip()}",
        f"B. {question.option_b.strip()}",
        f"C. {question.option_c.strip()}",
        f"D. {question.option_d.strip()}",
        f"ANSWER: {question.correct_option.strip().upper()}",
    ]
    explanation = (question.explanation or "").strip()
    if explanation:
        lines.append(f"EXPLANATION: {explanation}")
    return "\n".join(lines)


# Convert proxy JSON entries into VariantQuestionDraft objects.
def _map_proxy_variants(items: Sequence[dict[str, str]]) -> list[VariantQuestionDraft]:
    drafts: list[VariantQuestionDraft] = []
    for index, item in enumerate(items):
        try:
            drafts.append(
                VariantQuestionDraft(
                    prompt=str(item["prompt"]).strip(),
                    option_a=str(item["option_a"]).strip(),
                    option_b=str(item["option_b"]).strip(),
                    option_c=str(item["option_c"]).strip(),
                    option_d=str(item["option_d"]).strip(),
                    correct_option=str(item["correct_option"]).strip().upper(),
                    explanation=str(item.get("explanation", "")).strip(),
                )
            )
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise VariantProxyError(f"Variant payload missing field: {exc}") from exc
    return drafts


# Resolve connection settings for the selected agent key.
def _resolve_agent_settings(app, agent: str | None) -> tuple[str, str, str | None, int]:
    endpoints = app.config.get("VARIANT_PROXY_ENDPOINTS", {}) or {}
    if not isinstance(endpoints, dict):
        endpoints = {}
    default_agent = (app.config.get("VARIANT_PROXY_DEFAULT_AGENT") or "fast").lower()
    selected = (agent or default_agent or "").strip().lower()

    settings = endpoints.get(selected)
    if not isinstance(settings, dict):
        settings = None
    if settings is None and endpoints:
        fallback_key = default_agent if default_agent in endpoints else next(iter(endpoints))
        settings = endpoints.get(fallback_key) or {}
        selected = fallback_key
    elif settings is None:
        settings = {}
        selected = default_agent

    base_url_value = settings.get("base_url") if isinstance(settings, dict) else None
    if isinstance(base_url_value, str) and base_url_value.strip():
        base_url = base_url_value.strip()
    else:
        base_url = (
            app.config.get("VARIANT_PROXY_BASE_URL")
            or app.config.get("VARIANT_PROXY_URL")
            or "http://47.74.8.132:18899"
        )
    if not isinstance(base_url, str) or not base_url.strip():
        base_url = "http://47.74.8.132:18899"
    base_url = base_url.strip()

    token_value = settings.get("token") if isinstance(settings, dict) else None
    token = token_value.strip() if isinstance(token_value, str) and token_value.strip() else None
    if not token:
        fallback_token = app.config.get("VARIANT_PROXY_TOKEN")
        if isinstance(fallback_token, str) and fallback_token.strip():
            token = fallback_token.strip()

    timeout_value = settings.get("timeout") if isinstance(settings, dict) else None
    if timeout_value is None:
        timeout_value = app.config.get("VARIANT_PROXY_TIMEOUT", 45)
    try:
        timeout = int(timeout_value)
    except (TypeError, ValueError):
        timeout = 45

    return selected, base_url, token, timeout


# Send the question to the external proxy and parse the response.
def _request_proxy_variants(
    question: Question,
    count: int,
    *,
    agent: str | None = None,
) -> Tuple[str, str, list[VariantQuestionDraft]]:
    
    app = current_app._get_current_object()
    if count <= 0:
        raise ValueError("count must be positive")

    payload = {"question": _compose_question_payload(question), "num": count}
    headers = {"Content-Type": "application/json"}
    agent_key, base_url, token, timeout = _resolve_agent_settings(app, agent)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url.rstrip('/')}/api/generateVariant"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise VariantProxyError("Failed to reach the variant proxy.") from exc

    if response.status_code == 401:
        raise VariantProxyError("Variant proxy rejected the authentication token.")
    if response.status_code >= 500:
        raise VariantProxyError("Variant proxy encountered an internal error.")
    if response.status_code >= 400:
        raise VariantProxyError(f"Variant proxy returned status {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise VariantProxyError("Variant proxy responded with invalid JSON.") from exc

    knowledge_name = str(data.get("knowledge_point_name") or "").strip()
    knowledge_summary = str(data.get("knowledge_point_summary") or "").strip()
    variants_data = data.get("variant_questions") or []

    if not knowledge_name or not knowledge_summary or not variants_data:
        raise VariantProxyError("Variant proxy response is missing required fields.")

    drafts = _map_proxy_variants(variants_data)
    if not drafts:
        raise VariantProxyError("Variant proxy did not return any questions.")

    logger.debug(
        "Variant proxy (%s) returned %s items in %sms",
        agent_key,
        len(drafts),
        data.get("time"),
    )
    return knowledge_name, knowledge_summary, drafts



#Return knowledge metadata plus drafted variants using proxy fallback logic.
def generate_variants_with_metadata(
    question: Question,
    *,
    count: int,
    agent: str | None = None,
) -> Tuple[str, str, list[VariantQuestionDraft]]:
    
    if count <= 0:
        raise ValueError("count must be positive")

    app = current_app._get_current_object()
    if app.config.get("VARIANT_PROXY_ENABLED", True):
        try:
            return _request_proxy_variants(question, count, agent=agent)
        except VariantProxyError as exc:
            app.logger.warning("Variant proxy failed: %s - falling back to local drafts.", exc)

    knowledge_name, knowledge_summary = derive_knowledge_point(question)
    drafts = _generate_local_variants(question, count=count)
    return knowledge_name, knowledge_summary, drafts


# Public alias retained for callers that only need the local drafts.
def generate_question_variants(
    question: Question,
    *,
    count: int,
) -> list[VariantQuestionDraft]:

    return _generate_local_variants(question, count=count)


# Create a human-readable knowledge point name and summary.
def derive_knowledge_point(question: Question) -> tuple[str, str]:
    

    topic = (question.topic or "Core concepts").strip().title() or "Core Concepts"
    if question.state_scope.upper() == "ALL":
        scope_phrase = "all Australian learners"
    else:
        scope_phrase = f"{question.state_scope.upper()} learners"

    name = f"{topic} mastery"
    summary = (
        f"Strengthen understanding of {topic.lower()} requirements for {scope_phrase}. "
        "Each variation keeps the same correct option while challenging situational judgement."
    )
    return name, summary


__all__: Iterable[str] = [
    "VariantQuestionDraft",
    "VariantProxyError",
    "generate_variants_with_metadata",
    "generate_question_variants",
    "derive_knowledge_point",
]
