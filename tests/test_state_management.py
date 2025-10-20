from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import TestConfig
from app.models import Coach, ExamRule, Question, Student, StudentExamSession
from app.services import (
    StateSwitchError,
    StateSwitchPermissionError,
    StateSwitchValidationError,
    get_coaches_for_state,
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
