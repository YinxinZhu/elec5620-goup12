"""Helpers for managing multi-state exam behaviour."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_

from .. import db
from ..i18n import DEFAULT_LANGUAGE, ensure_language_code
from ..models import (
    Coach,
    ExamRule,
    Question,
    Student,
    StudentExamSession,
    StudentStateProgress,
)


class StateSwitchError(RuntimeError):
    """Base class for state switching problems."""


class StateSwitchPermissionError(StateSwitchError):
    """Raised when a user attempts to switch another student's state."""


class StateSwitchValidationError(StateSwitchError):
    """Raised when state switching input is invalid."""


def _normalise_state_code(state_code: str) -> str:
    code = (state_code or "").strip().upper()
    if not code:
        raise StateSwitchValidationError("A destination state must be provided.")
    return code


def _normalise_existing_state(state_code: str | None) -> str:
    """Return a normalised state code for existing records without validation."""

    return (state_code or "").strip().upper()


def _get_rule_or_error(state_code: str) -> ExamRule:
    rule = ExamRule.query.filter_by(state=state_code).first()
    if not rule:
        raise StateSwitchValidationError(
            f"No exam rule configured for state '{state_code}'."
        )
    return rule


def _format_rule_summary(state_code: str, rule: ExamRule) -> str:
    return (
        f"Current state: {state_code} — "
        f"{rule.total_questions} questions, pass mark {rule.pass_mark}, "
        f"time limit {rule.time_limit_minutes} minutes"
    )


def switch_student_state(
    student: Student,
    new_state: str,
    *,
    acting_student: Student | None = None,
) -> str:
    """Switch the student's active state and return the rule summary message."""

    if student.id is None:
        raise StateSwitchValidationError("Student must be persisted before switching state.")

    desired_state = _normalise_state_code(new_state)
    current_state = _normalise_existing_state(student.state)

    if acting_student and acting_student.id != student.id:
        raise StateSwitchPermissionError("Users may only change their own state.")

    active_exam = (
        StudentExamSession.query.filter_by(student_id=student.id, status="ongoing").first()
    )
    if active_exam and desired_state != current_state:
        raise StateSwitchError("State switching is disabled during an ongoing exam.")

    rule = _get_rule_or_error(desired_state)

    progress = (
        StudentStateProgress.query.filter_by(student_id=student.id)
        .filter(func.upper(StudentStateProgress.state) == desired_state)
        .first()
    )
    if not progress:
        progress = StudentStateProgress(student_id=student.id, state=desired_state)
        db.session.add(progress)
    elif progress.state != desired_state:
        progress.state = desired_state

    progress.last_active_at = datetime.utcnow()

    if student.state != desired_state:
        student.state = desired_state

    db.session.commit()
    return _format_rule_summary(desired_state, rule)


def get_questions_for_state(state_code: str, *, language: str | None = None) -> list[Question]:
    """Return the deduplicated question bank for the given state.

    We always include the default-language bank to guarantee full coverage, then
    layer any translated questions on top so that students see localised
    content where available without losing access to the wider catalogue.
    """

    state = _normalise_state_code(state_code)
    language_code = ensure_language_code(language)

    base_query = Question.query.filter(
        or_(Question.state_scope == state, Question.state_scope == "ALL")
    ).order_by(Question.qid.asc())

    default_questions = (
        base_query.filter(Question.language == DEFAULT_LANGUAGE).all()
    )

    deduped: dict[str, Question] = {
        question.qid: question for question in default_questions
    }

    if language_code != DEFAULT_LANGUAGE:
        translated_questions = (
            base_query.filter(Question.language == language_code).all()
        )
        for question in translated_questions:
            existing = deduped.get(question.qid)
            if not existing or existing.language == DEFAULT_LANGUAGE or (
                existing.state_scope == "ALL" and question.state_scope == state
            ):
                deduped[question.qid] = question

    return list(deduped.values())


def get_coaches_for_state(state_code: str) -> list[Coach]:
    """Return coaches registered in the requested state."""

    state = _normalise_state_code(state_code)
    return Coach.query.filter_by(state=state).order_by(Coach.name.asc()).all()


__all__ = [
    "StateSwitchError",
    "StateSwitchPermissionError",
    "StateSwitchValidationError",
    "switch_student_state",
    "get_questions_for_state",
    "get_coaches_for_state",
]
