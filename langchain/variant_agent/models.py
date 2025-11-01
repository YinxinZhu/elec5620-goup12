from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class VariantRequest(BaseModel):
    # Input payload accepted by /api/generateVariant.

    question: str = Field(..., description="Original exam question in any language.")
    num: Optional[int] = Field(
        default=3,
        ge=1,
        le=5,
        description="Number of variants requested (1-5, defaults to 3).",
    )

    # Ensure the learner question is not empty or whitespace.
    @model_validator(mode="after")
    def ensure_non_empty_question(self) -> "VariantRequest":
        if not self.question or not self.question.strip():
            raise ValueError("`question` must be a non-empty string.")
        return self


class UsageMetrics(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0


class VariantQuestion(BaseModel):
    prompt: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    explanation: str


class VariantResponse(BaseModel):
    knowledge_point_name: str
    knowledge_point_summary: str
    variant_questions: List[VariantQuestion]
    time: int
    usage: UsageMetrics

