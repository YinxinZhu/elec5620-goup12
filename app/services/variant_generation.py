"""Utility helpers for generating variant practice questions locally.

The production system integrates with an AI agent to draft follow-up questions
based on an existing prompt. Within the test harness we deterministically
produce scenario-based variants so that the API and persistence layers can be
validated without external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..models import Question

# Ordered scenarios ensure variant prompts stay reproducible for tests and seed data.
SCENARIO_LABELS: tuple[str, ...] = (
    "wet-weather driving",
    "night conditions",
    "high-traffic commute",
    "regional roads",
    "emergency vehicle approach",
)


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
    return f"{base_prompt} — consider the {scenario} scenario #{number}."


def _format_explanation(base_explanation: str, scenario: str) -> str:
    details = base_explanation.strip() or "Review the core road rule."
    return f"{details} This variation focuses on decisions during {scenario}."


def generate_question_variants(
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


def derive_knowledge_point(question: Question) -> tuple[str, str]:
    """Create a human-readable knowledge point name and summary."""

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
    "generate_question_variants",
    "derive_knowledge_point",
]
