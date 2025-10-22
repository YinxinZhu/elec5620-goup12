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
    Appointment,
    AvailabilitySlot,
    Coach,
    ExamRule,
    MockExamPaper,
    MockExamSummary,
    NotebookEntry,
    Question,
    QuestionAttempt,
    Student,
    StudentExamSession,
    StudentStateProgress,
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
    get_progress_trend,
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
    student = Student(
        name="Jamie",
        email="jamie@example.com",
        state="NSW",
        mobile_number="0400000001",
        preferred_language="ENGLISH",
    )
    student.set_password("password123")
    coach_nsw = Coach(
        email="nsw@example.com",
        password_hash="hash",
        name="Alex",
        mobile_number="0400001000",
        city="Sydney",
        state="NSW",
        vehicle_types="AT",
    )
    coach_vic = Coach(
        email="vic@example.com",
        password_hash="hash",
        name="Casey",
        mobile_number="0400001001",
        city="Melbourne",
        state="VIC",
        vehicle_types="MT",
    )

    questions = [
        Question(
            qid="q1",
            prompt="Shared question",
            state_scope="ALL",
            topic="core",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="A",
            explanation="Because",
            language="ENGLISH",
        ),
        Question(
            qid="q1",
            prompt="共享题目",
            state_scope="ALL",
            topic="core",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="A",
            explanation="因为",
            language="CHINESE",
        ),
        Question(
            qid="q2",
            prompt="NSW question",
            state_scope="NSW",
            topic="state",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="B",
            explanation="NSW",
            language="ENGLISH",
        ),
        Question(
            qid="q2",
            prompt="新州题目",
            state_scope="NSW",
            topic="state",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="B",
            explanation="NSW",
            language="CHINESE",
        ),
        Question(
            qid="q2",
            prompt="VIC variant",
            state_scope="VIC",
            topic="state",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="C",
            explanation="VIC",
            language="ENGLISH",
        ),
        Question(
            qid="q2",
            prompt="维州变体",
            state_scope="VIC",
            topic="state",
            option_a="A",
            option_b="B",
            option_c="C",
            option_d="D",
            correct_option="C",
            explanation="VIC",
            language="CHINESE",
        ),
    ]

    student.coach = coach_nsw

    db.session.add_all(
        [
            student,
            coach_nsw,
            coach_vic,
            ExamRule(state="NSW", total_questions=45, pass_mark=38, time_limit_minutes=45),
            ExamRule(state="VIC", total_questions=42, pass_mark=36, time_limit_minutes=40),
            *questions,
        ]
    )
    paper_nsw = MockExamPaper(state="NSW", title="NSW Paper 1", time_limit_minutes=45)
    paper_vic = MockExamPaper(state="VIC", title="VIC Paper 1", time_limit_minutes=40)
    db.session.add_all([paper_nsw, paper_vic])
    db.session.commit()
    return student


def _login_student(client, mobile: str, password: str) -> None:
    client.post(
        "/coach/login",
        data={"mobile_number": mobile, "password": password},
        follow_redirects=True,
    )


def test_student_profile_switch_flow(app_context, sample_data):
    client = app_context.test_client()
    _login_student(client, "0400000001", "password123")

    response = client.post(
        "/student/profile",
        data={
            "name": "Jamie",
            "email": "jamie@example.com",
            "state": "VIC",
            "preferred_language": "CHINESE",
            "new_password": "",
            "confirm_password": "",
        },
        follow_redirects=True,
    )

    page = response.get_data(as_text=True)
    assert "Current state: VIC" in page
    assert "个人资料更新成功" in page

    with app_context.app_context():
        student = Student.query.filter_by(email="jamie@example.com").one()
        assert student.state == "VIC"
        assert StudentStateProgress.query.filter_by(
            student_id=student.id, state="VIC"
        ).first()


def test_language_switch_route_updates_preference(app_context, sample_data):
    client = app_context.test_client()
    _login_student(client, "0400000001", "password123")

    response = client.post(
        "/language",
        data={"language": "CHINESE"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "语言已切换为" in html

    db.session.refresh(sample_data)
    assert sample_data.preferred_language == "CHINESE"

    profile_page = client.get("/student/profile").get_data(as_text=True)
    assert "首选语言" in profile_page


def test_student_can_book_assigned_coach_slot(app_context, sample_data):
    client = app_context.test_client()

    with app_context.app_context():
        student_record = db.session.get(Student, sample_data.id)
        assert student_record is not None
        assert student_record.assigned_coach_id is not None
        coach = db.session.get(Coach, student_record.assigned_coach_id)
        assert coach is not None
        slot = AvailabilitySlot(
            coach_id=coach.id,
            start_time=datetime.utcnow() + timedelta(hours=2),
            duration_minutes=60,
            location_text="City Test Centre",
        )
        db.session.add(slot)
        db.session.commit()
        slot_id = slot.id
        student_id = sample_data.id
        coach_id = coach.id

    _login_student(client, "0400000001", "password123")

    with app_context.app_context():
        available_count = (
            AvailabilitySlot.query.filter_by(coach_id=coach_id, status="available")
            .filter(AvailabilitySlot.start_time >= datetime.utcnow())
            .count()
        )
    assert available_count == 1
    confirmation = client.post(
        f"/student/slots/{slot_id}/book",
        follow_redirects=True,
    )
    assert confirmation.status_code == 200
    confirmation_text = confirmation.get_data(as_text=True)
    assert "already been reserved" not in confirmation_text
    assert "Assign a coach" not in confirmation_text

    with app_context.app_context():
        refreshed_slot = db.session.get(AvailabilitySlot, slot_id)
        db.session.refresh(refreshed_slot)
        assert refreshed_slot is not None
        assert refreshed_slot.status == "booked"
        assert refreshed_slot.appointment is not None
        assert refreshed_slot.appointment.student_id == student_id
        appointment = Appointment.query.filter_by(slot_id=slot_id).first()
        assert appointment is not None
        assert appointment.student_id == student_id

    dashboard_after = client.get("/student/dashboard").get_data(as_text=True)
    assert dashboard_after.count("City Test Centre") >= 1
    assert "Book this session" not in dashboard_after

    duplicate_attempt = client.post(
        f"/student/slots/{slot_id}/book",
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "already been reserved" in duplicate_attempt

    with app_context.app_context():
        other_coach = Coach.query.filter_by(state="VIC").first()
        assert other_coach is not None
        other_slot = AvailabilitySlot(
            coach_id=other_coach.id,
            start_time=datetime.utcnow() + timedelta(days=1),
            duration_minutes=30,
            location_text="Melbourne Lot",
        )
        db.session.add(other_slot)
        db.session.commit()
        other_slot_id = other_slot.id

    wrong_coach = client.post(
        f"/student/slots/{other_slot_id}/book",
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "different coach" in wrong_coach

    with app_context.app_context():
        preserved_slot = db.session.get(AvailabilitySlot, other_slot_id)
        assert preserved_slot is not None
        assert preserved_slot.status == "available"


@pytest.fixture
def progress_dataset(sample_data):
    student = sample_data
    now = datetime.utcnow()

    shared_question = (
        Question.query.filter_by(qid="q1", state_scope="ALL", language="ENGLISH").one()
    )
    nsw_question = (
        Question.query.filter_by(qid="q2", state_scope="NSW", language="ENGLISH").one()
    )

    extra_nsw_question = Question(
        qid="q3",
        prompt="Extra NSW question",
        state_scope="NSW",
        topic="state",
        option_a="A",
        option_b="B",
        option_c="C",
        option_d="D",
        correct_option="A",
        explanation="Extra",
        language="ENGLISH",
    )
    vic_extra_question = Question(
        qid="q4",
        prompt="Extra VIC question",
        state_scope="VIC",
        topic="state",
        option_a="A",
        option_b="B",
        option_c="C",
        option_d="D",
        correct_option="A",
        explanation="Extra",
        language="ENGLISH",
    )
    db.session.add_all([extra_nsw_question, vic_extra_question])
    db.session.commit()

    db.session.add_all(
        [
            QuestionAttempt(
                student_id=student.id,
                question_id=shared_question.id,
                state="NSW",
                is_correct=True,
                chosen_option="A",
                time_spent_seconds=30,
                attempted_at=now - timedelta(days=1),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=nsw_question.id,
                state="NSW",
                is_correct=False,
                chosen_option="C",
                time_spent_seconds=45,
                attempted_at=now - timedelta(hours=3),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=nsw_question.id,
                state="NSW",
                is_correct=True,
                chosen_option="B",
                time_spent_seconds=40,
                attempted_at=now - timedelta(hours=1),
            ),
            QuestionAttempt(
                student_id=student.id,
                question_id=vic_extra_question.id,
                state="VIC",
                is_correct=False,
                chosen_option="B",
                time_spent_seconds=50,
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

    questions = get_questions_for_state("VIC", language=student.preferred_language)
    # q1 shared + VIC-specific q2 (deduplicated against NSW variant)
    assert {q.qid for q in questions} == {"q1", "q2"}
    assert any(q.prompt == "VIC variant" for q in questions)

    chinese_questions = get_questions_for_state("VIC", language="CHINESE")
    assert {q.qid for q in chinese_questions} == {"q1", "q2"}
    assert any(q.prompt == "维州变体" for q in chinese_questions)

    coaches = get_coaches_for_state("VIC")
    assert len(coaches) == 1
    assert coaches[0].state == "VIC"


def test_switching_same_state_initialises_and_refreshes_progress(sample_data):
    student = sample_data

    assert (
        StudentStateProgress.query.filter_by(student_id=student.id, state="NSW").first()
        is None
    )

    switch_student_state(student, "NSW", acting_student=student)

    progress = StudentStateProgress.query.filter_by(
        student_id=student.id, state="NSW"
    ).one()
    initial_last_active = progress.last_active_at

    progress.last_active_at = initial_last_active - timedelta(minutes=10)
    db.session.commit()

    switch_student_state(student, "NSW", acting_student=student)

    refreshed = StudentStateProgress.query.filter_by(
        student_id=student.id, state="NSW"
    ).one()

    assert refreshed.last_active_at >= initial_last_active


def test_switching_handles_legacy_lowercase_state(sample_data):
    student = sample_data
    # Simulate legacy lowercase data
    student.state = "nsw"
    db.session.add_all(
        [
            StudentStateProgress(student_id=student.id, state="nsw"),
            StudentExamSession(
                student_id=student.id,
                state="nsw",
                paper_id=MockExamPaper.query.filter_by(state="NSW").first().id,
                status="ongoing",
            ),
        ]
    )
    db.session.commit()

    summary = switch_student_state(student, "nsw", acting_student=student)

    assert "NSW" in summary
    assert student.state == "NSW"

    progress_records = StudentStateProgress.query.filter_by(student_id=student.id).all()
    assert len(progress_records) == 1
    assert progress_records[0].state == "NSW"

def test_switching_blocked_with_active_exam(sample_data):
    student = sample_data
    db.session.add(
        StudentExamSession(
            student_id=student.id,
            state="NSW",
            paper_id=MockExamPaper.query.filter_by(state="NSW").first().id,
            status="ongoing",
        )
    )
    db.session.commit()

    with pytest.raises(StateSwitchError):
        switch_student_state(student, "VIC", acting_student=student)


def test_switch_requires_persisted_student(app_context):
    transient_student = Student(
        name="Temp",
        email="temp@example.com",
        state="NSW",
        mobile_number="0400000099",
        preferred_language="ENGLISH",
    )
    transient_student.set_password("password123")
    with pytest.raises(StateSwitchValidationError):
        switch_student_state(transient_student, "VIC")


def test_switch_forbids_updating_other_users(sample_data):
    student = sample_data
    other_student = Student(
        name="Lee",
        email="lee@example.com",
        state="VIC",
        mobile_number="0400000002",
        preferred_language="ENGLISH",
    )
    other_student.set_password("password123")
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


def test_progress_summary_topic_filter(progress_dataset):
    student = progress_dataset

    summary = get_progress_summary(
        student, state="NSW", acting_student=student, topic="state"
    )

    assert summary.total == 2
    assert summary.done == 1
    assert summary.correct == 1
    assert summary.pending == 1
    assert summary.wrong == 2


def test_progress_summary_date_filter(progress_dataset):
    student = progress_dataset
    recent_start = datetime.utcnow() - timedelta(hours=2)

    summary = get_progress_summary(
        student, acting_student=student, start_at=recent_start
    )

    assert summary.done == 1
    assert summary.correct == 1
    assert summary.pending == summary.total - summary.done
    assert summary.wrong == 0


def test_progress_trend_respects_filters(progress_dataset):
    student = progress_dataset

    full_trend = get_progress_trend(student, acting_student=student, state="NSW")
    assert full_trend
    assert any(point.correct >= 1 for point in full_trend)

    topic_trend = get_progress_trend(
        student, state="NSW", acting_student=student, topic="state"
    )
    assert sum(point.attempted for point in topic_trend) == 2
    assert all(point.correct <= point.attempted for point in topic_trend)


def test_progress_summary_rejects_invalid_state(progress_dataset):
    student = progress_dataset
    with pytest.raises(ProgressValidationError):
        get_progress_summary(student, state="QLD", acting_student=student)


def test_progress_summary_enforces_self_access(progress_dataset):
    student = progress_dataset
    other_student = Student(
        name="Morgan",
        email="morgan@example.com",
        state="NSW",
        mobile_number="0400000003",
        preferred_language="ENGLISH",
    )
    other_student.set_password("password123")
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

    recent_start = datetime.utcnow() - timedelta(hours=2)
    recent_csv = export_state_progress_csv(
        student, acting_student=student, start_at=recent_start
    )
    recent_rows = list(csv.DictReader(recent_csv.splitlines()))
    assert sum(1 for row in recent_rows if row["correctness"] == "correct") == 1
    assert any(
        row["qid"] == "q1" and row["correctness"] == "pending"
        for row in recent_rows
    )

    other_student = Student(
        name="Chris",
        email="chris@example.com",
        state="NSW",
        mobile_number="0400000004",
        preferred_language="ENGLISH",
    )
    other_student.set_password("password123")
    db.session.add(other_student)
    db.session.commit()

    with pytest.raises(ProgressAccessError):
        export_state_progress_csv(student, acting_student=other_student)
