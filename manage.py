from __future__ import annotations

from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    Appointment,
    AvailabilitySlot,
    Coach,
    ExamRule,
    MockExamSummary,
    Question,
    Student,
)

app = create_app()


@app.cli.command("init-db")
def init_db() -> None:
    """Initialise the database schema."""
    db.create_all()
    app.logger.info("Database tables created")


@app.cli.command("seed-demo")
def seed_demo() -> None:
    """Seed the database with demo data for coach flows."""
    db.drop_all()
    db.create_all()

    coach = Coach(
        email="coach@example.com",
        name="Alex Johnson",
        phone="0400 111 222",
        city="Sydney",
        state="NSW",
        vehicle_types="AT,MT",
        bio="Former RMS examiner with 10+ years of coaching experience.",
    )
    coach.set_password("password123")

    students = [
        Student(name="Jamie Lee", email="jamie@example.com", state="NSW", coach=coach),
        Student(name="Priya Nair", email="priya@example.com", state="NSW", coach=coach),
    ]

    summaries = [
        MockExamSummary(student=students[0], state="NSW", score=88),
        MockExamSummary(student=students[0], state="NSW", score=92),
        MockExamSummary(student=students[1], state="NSW", score=75),
    ]

    exam_rules = [
        ExamRule(state="NSW", total_questions=45, pass_mark=38, time_limit_minutes=45),
        ExamRule(state="VIC", total_questions=42, pass_mark=36, time_limit_minutes=40),
    ]

    questions = [
        Question(qid="NSW-001", prompt="What is the speed limit in school zones?", state_scope="NSW"),
        Question(qid="CORE-001", prompt="Define a safe following distance.", state_scope="ALL"),
        Question(qid="VIC-001", prompt="When must headlights be used?", state_scope="VIC"),
    ]

    now = datetime.utcnow()
    slots = [
        AvailabilitySlot(
            coach=coach,
            start_time=now + timedelta(days=1),
            duration_minutes=60,
            location_text="Sydney Olympic Park",
        ),
        AvailabilitySlot(
            coach=coach,
            start_time=now + timedelta(days=2, hours=2),
            duration_minutes=30,
            location_text="Parramatta Station",
        ),
    ]

    booking = Appointment(slot=slots[0], student=students[0])
    slots[0].status = "booked"

    db.session.add(coach)
    db.session.add_all(students)
    db.session.add_all(summaries)
    db.session.add_all(exam_rules)
    db.session.add_all(questions)
    db.session.add_all(slots)
    db.session.add(booking)
    db.session.commit()
    app.logger.info("Demo data created: coach login coach@example.com / password123")
