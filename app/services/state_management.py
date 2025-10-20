"""Helpers for managing multi-state exam behaviour."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from .. import db
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
    """Switch the student's active state and return the rule summary message.

    The caller may optionally provide ``acting_student``.  When supplied it must
    be the same student; otherwise :class:`StateSwitchPermissionError` is raised.
    The function performs the validations required by the specification and
    persists the change immediately to keep the student preferences consistent.
    """

    if student.id is None:
        raise StateSwitchValidationError("Student must be persisted before switching state.")

    desired_state = _normalise_state_code(new_state)

    if acting_student and acting_student.id != student.id:
        raise StateSwitchPermissionError("Users may only change their own state.")

    active_exam = (
        StudentExamSession.query.filter_by(student_id=student.id, status="ongoing").first()
    )
    if active_exam and desired_state != student.state:
        raise StateSwitchError("State switching is disabled during an ongoing exam.")

    rule = _get_rule_or_error(desired_state)

    if desired_state != student.state:
        student.state = desired_state
        progress = StudentStateProgress.query.filter_by(
            student_id=student.id, state=desired_state
        ).first()
        if not progress:
            progress = StudentStateProgress(student_id=student.id, state=desired_state)
            db.session.add(progress)
        progress.last_active_at = datetime.utcnow()

    db.session.commit()
    return _format_rule_summary(desired_state, rule)


def get_questions_for_state(state_code: str) -> list[Question]:
    """Return the deduplicated question bank for the given state."""

    state = _normalise_state_code(state_code)
    questions = (
        Question.query.filter(
            or_(Question.state_scope == state, Question.state_scope == "ALL")
        )
        .order_by(Question.qid.asc())
        .all()
    )

    deduped: dict[str, Question] = {}
    for question in questions:
        existing = deduped.get(question.qid)
        if not existing or (
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
