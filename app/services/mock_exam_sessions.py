from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import db
from ..models import (
    ExamRule,
    MockExamPaper,
    MockExamSummary,
    NotebookEntry,
    Question,
    Student,
    StudentExamAnswer,
    StudentExamSession,
)


class ExamRuleMissingError(RuntimeError):
    """Raised when an exam is attempted without a configured rule."""


class ExamSessionConflictError(RuntimeError):
    """Raised when a student tries to run multiple simultaneous sessions."""


class ExamQuestionScopeError(RuntimeError):
    """Raised when an answer references a question outside the paper scope."""


@dataclass(slots=True)
class SessionStartResult:
    session: StudentExamSession
    resumed: bool


@dataclass(slots=True)
class SessionSubmission:
    score: int
    total: int
    pass_mark: int
    passed: bool


@dataclass(slots=True)
class SessionQuestion:
    question: Question
    position: int
    answer: StudentExamAnswer | None


def _ensure_exam_rule(state: str) -> ExamRule:
    rule = ExamRule.query.filter_by(state=state).first()
    if not rule:
        raise ExamRuleMissingError(f"No exam rule configured for state '{state}'.")
    return rule


def session_questions(session: StudentExamSession) -> list[SessionQuestion]:
    ordered = sorted(session.paper.questions, key=lambda pq: pq.position)
    answer_lookup = {answer.question_id: answer for answer in session.answers}
    return [
        SessionQuestion(
            question=paper_question.question,
            position=paper_question.position,
            answer=answer_lookup.get(paper_question.question_id),
        )
        for paper_question in ordered
    ]


def ensure_session_active(session: StudentExamSession) -> StudentExamSession:
    if (
        session.status == "ongoing"
        and session.expires_at
        and datetime.utcnow() >= session.expires_at
    ):
        finalise_session(session, auto=True)
    return session


def start_session(student: Student, paper: MockExamPaper) -> SessionStartResult:
    existing = (
        StudentExamSession.query.filter_by(student_id=student.id, status="ongoing")
        .order_by(StudentExamSession.started_at.desc())
        .first()
    )
    if existing and existing.paper_id != paper.id:
        raise ExamSessionConflictError("Finish the current exam before starting a new one.")

    if existing:
        session = ensure_session_active(existing)
        if session.status in {"submitted", "abandoned"}:
            existing = None
        else:
            return SessionStartResult(session=session, resumed=True)

    now = datetime.utcnow()
    session = StudentExamSession(
        student_id=student.id,
        state=student.state,
        paper_id=paper.id,
        expires_at=now + timedelta(minutes=paper.time_limit_minutes),
        total_questions=len(paper.questions),
    )
    db.session.add(session)
    db.session.commit()
    return SessionStartResult(session=session, resumed=False)


def record_answer(session: StudentExamSession, question_id: int, selected_option: str) -> StudentExamAnswer:
    paper_question = next((pq for pq in session.paper.questions if pq.question_id == question_id), None)
    if not paper_question:
        raise ExamQuestionScopeError("Question not part of this exam.")

    question = paper_question.question
    answer = StudentExamAnswer.query.filter_by(
        session_id=session.id, question_id=question_id
    ).first()
    is_correct = selected_option == question.correct_option
    if not answer:
        answer = StudentExamAnswer(
            session_id=session.id,
            question_id=question_id,
            selected_option=selected_option,
            is_correct=is_correct,
        )
        db.session.add(answer)
    else:
        answer.selected_option = selected_option
        answer.is_correct = is_correct
        answer.answered_at = datetime.utcnow()

    db.session.commit()
    return answer


def finalise_session(session: StudentExamSession, *, auto: bool = False) -> None:
    if session.status != "ongoing":
        return

    now = datetime.utcnow()
    questions = session_questions(session)
    score = 0
    wrong_questions: list[Question] = []

    for item in questions:
        if item.answer and item.answer.is_correct:
            score += 1
        else:
            wrong_questions.append(item.question)

    session.status = "submitted" if not auto else "abandoned"
    session.finished_at = now
    session.score = score
    session.total_questions = session.total_questions or len(questions)

    summary = MockExamSummary(student_id=session.student_id, state=session.state, score=score)
    db.session.add(summary)

    for question in wrong_questions:
        entry = (
            NotebookEntry.query.filter_by(
                student_id=session.student_id, question_id=question.id, state=session.state
            ).first()
        )
        if not entry:
            entry = NotebookEntry(
                student_id=session.student_id,
                question_id=question.id,
                state=session.state,
                wrong_count=1,
                last_wrong_at=now,
            )
            db.session.add(entry)
        else:
            entry.wrong_count += 1
            entry.last_wrong_at = now

    db.session.commit()


def submit_session(session: StudentExamSession) -> SessionSubmission:
    ensure_session_active(session)
    if session.status not in {"submitted", "abandoned"}:
        finalise_session(session, auto=False)
        db.session.refresh(session)

    rule = _ensure_exam_rule(session.state)
    score = session.score or 0
    total = session.total_questions or 0
    passed = session.status == "submitted" and score >= rule.pass_mark
    return SessionSubmission(
        score=score,
        total=total,
        pass_mark=rule.pass_mark,
        passed=passed,
    )

