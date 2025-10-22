"""Progress aggregation helpers for study metrics, exports and trends."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from io import StringIO
from typing import Dict, Iterable, List, Sequence

from sqlalchemy import case, func

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


@dataclass(frozen=True)
class ProgressTrendPoint:
    """Represents aggregate completion metrics for a single day."""

    day: date
    attempted: int
    correct: int
    accuracy: float


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


def _questions_for_scope(
    student: Student, *, state: str, topic: str | None = None
) -> List[Question]:
    """Return the deduplicated question bank restricted by topic if provided."""

    available_questions = get_questions_for_state(
        state, language=student.preferred_language
    )
    topic_filter = (topic or "").strip().lower()
    if topic_filter:
        return [
            question
            for question in available_questions
            if (question.topic or "").lower() == topic_filter
        ]
    return available_questions


def _coerce_day(value: date | datetime | str) -> date:
    """Normalise SQL results into a python date object."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _latest_attempts_by_qid(
    student: Student,
    *,
    state: str,
    allowed_qids: Iterable[str],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> Dict[str, QuestionAttempt]:
    qids = list(set(allowed_qids))
    if not qids:
        return {}
    query = QuestionAttempt.query.join(Question).filter(
        QuestionAttempt.student_id == student.id,
        QuestionAttempt.state == state,
        Question.qid.in_(qids),
    )
    if start_at:
        query = query.filter(QuestionAttempt.attempted_at >= start_at)
    if end_at:
        query = query.filter(QuestionAttempt.attempted_at <= end_at)

    attempts = query.order_by(QuestionAttempt.attempted_at.desc()).all()

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
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    topic: str | None = None,
) -> ProgressSummary:
    """Return the current study progress metrics for the requested state."""

    _ensure_student_persisted(student)
    _enforce_self_access(student, acting_student)
    resolved_state = _resolve_state(student, state)

    filtered_questions = _questions_for_scope(
        student, state=resolved_state, topic=topic
    )

    available_qids = {question.qid for question in filtered_questions}
    latest_attempts = _latest_attempts_by_qid(
        student,
        state=resolved_state,
        allowed_qids=available_qids,
        start_at=start_at,
        end_at=end_at,
    )

    done_qids = available_qids.intersection(latest_attempts.keys())
    total = len(available_qids)
    done = len(done_qids)
    correct = sum(1 for qid in done_qids if latest_attempts[qid].is_correct)
    pending = max(total - done, 0)

    wrong_query = NotebookEntry.query.filter_by(
        student_id=student.id, state=resolved_state
    )
    topic_filter = (topic or "").strip().lower()
    if topic_filter:
        wrong_query = wrong_query.join(NotebookEntry.question).filter(
            func.lower(Question.topic) == topic_filter
        )
    if start_at:
        wrong_query = wrong_query.filter(NotebookEntry.last_wrong_at >= start_at)
    if end_at:
        wrong_query = wrong_query.filter(NotebookEntry.last_wrong_at <= end_at)
    wrong_total = wrong_query.with_entities(
        func.coalesce(func.sum(NotebookEntry.wrong_count), 0)
    ).scalar()
    wrong = int(wrong_total or 0)

    latest_summary_query = MockExamSummary.query.filter_by(
        student_id=student.id, state=resolved_state
    )
    if start_at:
        latest_summary_query = latest_summary_query.filter(
            MockExamSummary.taken_at >= start_at
        )
    if end_at:
        latest_summary_query = latest_summary_query.filter(
            MockExamSummary.taken_at <= end_at
        )
    latest_summary = latest_summary_query.order_by(
        MockExamSummary.taken_at.desc()
    ).first()
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
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    topic: str | None = None,
) -> str:
    """Export the student's per-question progress for the selected state as CSV."""

    _ensure_student_persisted(student)
    _enforce_self_access(student, acting_student)
    resolved_state = _resolve_state(student, state)

    scoped_questions = _questions_for_scope(
        student, state=resolved_state, topic=topic
    )
    available_qids = sorted({question.qid for question in scoped_questions})
    latest_attempts = _latest_attempts_by_qid(
        student,
        state=resolved_state,
        allowed_qids=available_qids,
        start_at=start_at,
        end_at=end_at,
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


def get_progress_trend(
    student: Student,
    *,
    state: str | None = None,
    acting_student: Student | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    topic: str | None = None,
) -> List[ProgressTrendPoint]:
    """Return per-day completion metrics for charting progress trends."""

    _ensure_student_persisted(student)
    _enforce_self_access(student, acting_student)
    resolved_state = _resolve_state(student, state)

    scoped_questions = _questions_for_scope(
        student, state=resolved_state, topic=topic
    )
    allowed_qids = {question.qid for question in scoped_questions}
    if not allowed_qids:
        return []

    query = (
        QuestionAttempt.query.join(Question)
        .with_entities(
            func.date(QuestionAttempt.attempted_at).label("attempt_date"),
            func.count(QuestionAttempt.id).label("attempted"),
            func.coalesce(
                func.sum(
                    case((QuestionAttempt.is_correct.is_(True), 1), else_=0)
                ),
                0,
            ).label("correct"),
        )
        .filter(QuestionAttempt.student_id == student.id)
        .filter(QuestionAttempt.state == resolved_state)
        .filter(Question.qid.in_(allowed_qids))
    )
    if start_at:
        query = query.filter(QuestionAttempt.attempted_at >= start_at)
    if end_at:
        query = query.filter(QuestionAttempt.attempted_at <= end_at)

    rows: Sequence[tuple] = (
        query.group_by("attempt_date").order_by("attempt_date").all()
    )

    trend: List[ProgressTrendPoint] = []
    for attempt_date, attempted_count, correct_count in rows:
        attempted_total = int(attempted_count or 0)
        correct_total = int(correct_count or 0)
        accuracy = (
            round((correct_total / attempted_total) * 100, 1)
            if attempted_total
            else 0.0
        )
        trend.append(
            ProgressTrendPoint(
                day=_coerce_day(attempt_date),
                attempted=attempted_total,
                correct=correct_total,
                accuracy=accuracy,
            )
        )

    return trend


__all__ = [
    "ProgressAccessError",
    "ProgressValidationError",
    "ProgressSummary",
    "ProgressTrendPoint",
    "get_progress_summary",
    "get_progress_trend",
    "export_state_progress_csv",
]
