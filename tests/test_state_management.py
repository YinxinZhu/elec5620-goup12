from __future__ import annotations

import csv
from datetime import datetime, timedelta
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import TestConfig
from app.models import (
    Coach,
    ExamRule,
    MockExamSummary,
    NotebookEntry,
    Question,
    QuestionAttempt,
    Student,
    StudentExamSession,
)
from app.services import (
    ProgressAccessError,
    ProgressSummary,
    ProgressValidationError,
    StateSwitchError,
    StateSwitchPermissionError,
    StateSwitchValidationError,
    export_state_progress_csv,
    get_coaches_for_state,
    get_progress_summary,
    get_questions_for_state,
    switch_student_state,
)


@pytest.fixture
def app_context():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_data(app_context):
    student = Student(name="Jamie", email="jamie@example.com", state="NSW")
    coach_nsw = Coach(
        email="nsw@example.com",
        password_hash="hash",
        name="Alex",
        phone="000",
        city="Sydney",
        state="NSW",
        vehicle_types="AT",
    )
    coach_vic = Coach(
        email="vic@example.com",
        password_hash="hash",
        name="Casey",
        phone="111",
        city="Melbourne",
        state="VIC",
        vehicle_types="MT",
    )

    db.session.add_all(
        [
            student,
            coach_nsw,
            coach_vic,
            ExamRule(state="NSW", total_questions=45, pass_mark=38, time_limit_minutes=45),
            ExamRule(state="VIC", total_questions=42, pass_mark=36, time_limit_minutes=40),
            Question(qid="q1", prompt="Shared question", state_scope="ALL"),
            Question(qid="q2", prompt="NSW question", state_scope="NSW"),
            Question(qid="q2", prompt="VIC variant", state_scope="VIC"),
        ]
    )
    db.session.commit()
    return student


@pytest.fixture
def progress_dataset(sample_data):
    student = sample_data
    now = datetime.utcnow()

    shared_question = Question.query.filter_by(qid="q1", state_scope="ALL").one()
    nsw_question = Question.query.filter_by(qid="q2", state_scope="NSW").one()

    extra_nsw_question = Question(qid="q3", prompt="Extra NSW question", state_scope="NSW")
    vic_extra_question = Question(qid="q4", prompt="Extra VIC question", state_scope="VIC")
    db.session.add_all([extra_nsw_question, vic_extra_question])
    db.session.commit()

    db.session.add_all(
        [
            QuestionAttempt(
                student_id=student.id,
                question_id=shared_question.id,
                state="NSW",
                is_correct=True,
                attempted_at=now - timedelta(days=1),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=nsw_question.id,
                state="NSW",
                is_correct=False,
                attempted_at=now - timedelta(hours=3),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=nsw_question.id,
                state="NSW",
                is_correct=True,
                attempted_at=now - timedelta(hours=1),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=vic_extra_question.id,
                state="VIC",
                is_correct=False,
                attempted_at=now - timedelta(days=2),
            ),
        ]
    )

    db.session.add_all(
        [
            NotebookEntry(
                student_id=student.id,
                question_id=nsw_question.id,
                state="NSW",
                wrong_count=2,
                last_wrong_at=now - timedelta(hours=3),
            ),
            NotebookEntry(
                student_id=student.id,
                question_id=vic_extra_question.id,
                state="VIC",
                wrong_count=1,
                last_wrong_at=now - timedelta(days=2),
            ),
        ]
    )

    db.session.add_all(
        [
            MockExamSummary(
                student_id=student.id,
                state="NSW",
                score=78,
                taken_at=now - timedelta(days=4),
            ),
            MockExamSummary(
                student_id=student.id,
                state="NSW",
                score=85,
                taken_at=now - timedelta(days=1),
            ),
            MockExamSummary(
                student_id=student.id,
                state="VIC",
                score=65,
                taken_at=now - timedelta(days=3),
            ),
        ]
    )

    db.session.commit()
    return student


def test_switching_state_updates_preferences_and_progress(sample_data):
    student = sample_data
    summary = switch_student_state(student, "VIC", acting_student=student)

    assert student.state == "VIC"
    assert "VIC" in summary
    assert "42" in summary

    questions = get_questions_for_state("VIC")
    # q1 shared + VIC-specific q2 (deduplicated against NSW variant)
    assert {q.qid for q in questions} == {"q1", "q2"}
    assert any(q.prompt == "VIC variant" for q in questions)

    coaches = get_coaches_for_state("VIC")
    assert len(coaches) == 1
    assert coaches[0].state == "VIC"


def test_switching_blocked_with_active_exam(sample_data):
    student = sample_data
    db.session.add(
        StudentExamSession(student_id=student.id, state="NSW", status="ongoing")
    )
    db.session.commit()

    with pytest.raises(StateSwitchError):
        switch_student_state(student, "VIC", acting_student=student)


def test_switch_requires_persisted_student(app_context):
    transient_student = Student(name="Temp", email="temp@example.com", state="NSW")
    with pytest.raises(StateSwitchValidationError):
        switch_student_state(transient_student, "VIC")


def test_switch_forbids_updating_other_users(sample_data):
    student = sample_data
    other_student = Student(name="Lee", email="lee@example.com", state="VIC")
    db.session.add(other_student)
    db.session.commit()

    with pytest.raises(StateSwitchPermissionError):
        switch_student_state(student, "VIC", acting_student=other_student)


def test_progress_summary_aggregates_metrics(progress_dataset):
    student = progress_dataset

    summary = get_progress_summary(student, acting_student=student)
    assert isinstance(summary, ProgressSummary)
    assert summary.state == "NSW"
    assert summary.total == 3  # q1 shared + NSW q2 + NSW q3
    assert summary.done == 2  # q1 and q2 attempted, q3 pending
    assert summary.correct == 2
    assert summary.pending == 1
    assert summary.wrong == 2
    assert summary.last_score == 85

    vic_summary = get_progress_summary(student, state="VIC", acting_student=student)
    assert vic_summary.state == "VIC"
    assert vic_summary.total == 3  # q1 shared + VIC q2 variant + VIC q4
    assert vic_summary.done == 1
    assert vic_summary.correct == 0
    assert vic_summary.wrong == 1
    assert vic_summary.pending == 2
    assert vic_summary.last_score == 65


def test_progress_summary_rejects_invalid_state(progress_dataset):
    student = progress_dataset
    with pytest.raises(ProgressValidationError):
        get_progress_summary(student, state="QLD", acting_student=student)


def test_progress_summary_enforces_self_access(progress_dataset):
    student = progress_dataset
    other_student = Student(name="Morgan", email="morgan@example.com", state="NSW")
    db.session.add(other_student)
    db.session.commit()

    with pytest.raises(ProgressAccessError):
        get_progress_summary(student, acting_student=other_student)


def test_progress_csv_export_marks_pending(progress_dataset):
    student = progress_dataset

    csv_payload = export_state_progress_csv(student, acting_student=student)
    rows = list(csv.DictReader(csv_payload.splitlines()))

    assert rows[0]["qid"] == "q1"
    assert rows[0]["correctness"] == "correct"
    assert rows[1]["qid"] == "q2"
    assert rows[1]["correctness"] == "correct"
    assert rows[2]["qid"] == "q3"
    assert rows[2]["correctness"] == "pending"
    assert rows[2]["last_attempt_at"] == ""

    vic_csv = export_state_progress_csv(student, state="VIC", acting_student=student)
    vic_rows = list(csv.DictReader(vic_csv.splitlines()))
    assert any(row["correctness"] == "incorrect" for row in vic_rows)

    other_student = Student(name="Chris", email="chris@example.com", state="NSW")
    db.session.add(other_student)
    db.session.commit()

    with pytest.raises(ProgressAccessError):
        export_state_progress_csv(student, acting_student=other_student)
