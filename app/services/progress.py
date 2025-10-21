"""Progress aggregation helpers for study metrics and exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Dict, Iterable

from sqlalchemy import func

from ..models import (
    ExamRule,
    MockExamSummary,
    NotebookEntry,
    Question,
    QuestionAttempt,
    Student,
)
from .state_management import get_questions_for_state


class ProgressAccessError(RuntimeError):
    """Raised when a student attempts to access another student's progress."""


class ProgressValidationError(RuntimeError):
    """Raised when progress operations receive invalid input."""


@dataclass(frozen=True)
class ProgressSummary:
    """Represents the study metrics for a student within a state."""

    state: str
    total: int
    done: int
    correct: int
    wrong: int
    pending: int
    last_score: int | None


def _normalise_state_code(state_code: str | None) -> str:
    code = (state_code or "").strip().upper()
    if not code:
        raise ProgressValidationError("A state code must be provided.")
    return code


def _ensure_student_persisted(student: Student) -> None:
    if student.id is None:
        raise ProgressValidationError("Student must be persisted before querying progress.")


def _enforce_self_access(student: Student, acting_student: Student | None) -> None:
    if acting_student and acting_student.id != student.id:
        raise ProgressAccessError("Students may only view their own progress data.")


def _resolve_state(student: Student, state: str | None) -> str:
    resolved = _normalise_state_code(state or student.state)
    rule_exists = ExamRule.query.filter_by(state=resolved).first()
    if not rule_exists:
        raise ProgressValidationError(f"No exam rule configured for state '{resolved}'.")
    return resolved


def _latest_attempts_by_qid(
    student: Student, *, state: str, allowed_qids: Iterable[str]
) -> Dict[str, QuestionAttempt]:
    qids = list(set(allowed_qids))
    if not qids:
        return {}
    attempts = (
        QuestionAttempt.query.join(Question)
        .filter(
            QuestionAttempt.student_id == student.id,
            QuestionAttempt.state == state,
            Question.qid.in_(qids),
        )
        .order_by(QuestionAttempt.attempted_at.desc())
        .all()
    )

    latest: Dict[str, QuestionAttempt] = {}
    for attempt in attempts:
        qid = attempt.question.qid
        if qid not in latest:
            latest[qid] = attempt
    return latest


def get_progress_summary(
    student: Student,
    *,
    state: str | None = None,
    acting_student: Student | None = None,
) -> ProgressSummary:
    """Return the current study progress metrics for the requested state."""

    _ensure_student_persisted(student)
    _enforce_self_access(student, acting_student)
    resolved_state = _resolve_state(student, state)

    available_questions = get_questions_for_state(
        resolved_state, language=student.preferred_language
    )
    available_qids = {question.qid for question in available_questions}
    latest_attempts = _latest_attempts_by_qid(
        student, state=resolved_state, allowed_qids=available_qids
    )

    done_qids = available_qids.intersection(latest_attempts.keys())
    total = len(available_qids)
    done = len(done_qids)
    correct = sum(1 for qid in done_qids if latest_attempts[qid].is_correct)
    pending = max(total - done, 0)

    wrong_total = (
        NotebookEntry.query.with_entities(func.coalesce(func.sum(NotebookEntry.wrong_count), 0))
        .filter_by(student_id=student.id, state=resolved_state)
        .scalar()
    )
    wrong = int(wrong_total or 0)

    latest_summary = (
        MockExamSummary.query.filter_by(student_id=student.id, state=resolved_state)
        .order_by(MockExamSummary.taken_at.desc())
        .first()
    )
    last_score = latest_summary.score if latest_summary else None

    return ProgressSummary(
        state=resolved_state,
        total=total,
        done=done,
        correct=correct,
        wrong=wrong,
        pending=pending,
        last_score=last_score,
    )


def export_state_progress_csv(
    student: Student,
    *,
    state: str | None = None,
    acting_student: Student | None = None,
) -> str:
    """Export the student's per-question progress for the selected state as CSV."""

    _ensure_student_persisted(student)
    _enforce_self_access(student, acting_student)
    resolved_state = _resolve_state(student, state)

    available_questions = get_questions_for_state(
        resolved_state, language=student.preferred_language
    )
    available_qids = sorted({question.qid for question in available_questions})
    latest_attempts = _latest_attempts_by_qid(
        student, state=resolved_state, allowed_qids=available_qids
    )

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=["qid", "correctness", "last_attempt_at"])
    writer.writeheader()

    for qid in available_qids:
        attempt = latest_attempts.get(qid)
        if attempt:
            status = "correct" if attempt.is_correct else "incorrect"
            last_attempt_at = attempt.attempted_at.isoformat()
        else:
            status = "pending"
            last_attempt_at = ""
        writer.writerow(
            {
                "qid": qid,
                "correctness": status,
                "last_attempt_at": last_attempt_at,
            }
        )

    return output.getvalue()


__all__ = [
    "ProgressAccessError",
    "ProgressValidationError",
    "ProgressSummary",
    "get_progress_summary",
    "export_state_progress_csv",
]
