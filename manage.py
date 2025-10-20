from __future__ import annotations

from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    Admin,
    Appointment,
    AvailabilitySlot,
    Coach,
    ExamRule,
    MockExamPaper,
    MockExamPaperQuestion,
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

    admin_coach = Coach(
        email="admin@example.com",
        name="DriveWise Administrator",
        phone="0400 999 000",
        city="Sydney",
        state="NSW",
        vehicle_types="AT,MT",
        bio="Platform superuser with access to all coach and student features.",
    )
    admin_coach.set_password("password123")

    students = [
        Student(
            name="Jamie Lee",
            email="jamie@example.com",
            state="NSW",
            mobile_number="0400000100",
            preferred_language="ENGLISH",
            coach=coach,
        ),
        Student(
            name="Priya Nair",
            email="priya@example.com",
            state="NSW",
            mobile_number="0400000101",
            preferred_language="ENGLISH",
            coach=coach,
        ),
        Student(
            name="Morgan Patel",
            email="morgan@example.com",
            state="VIC",
            mobile_number="0400000102",
            preferred_language="ENGLISH",
            coach=admin_coach,
        ),
    ]
    for student in students:
        student.set_password("password123")

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
        Question(
            qid="NSW-001",
            prompt="What is the speed limit in school zones?",
            state_scope="NSW",
            topic="rules",
            option_a="25 km/h",
            option_b="30 km/h",
            option_c="40 km/h",
            option_d="50 km/h",
            correct_option="C",
            explanation="School zones in NSW require a 40 km/h limit.",
        ),
        Question(
            qid="CORE-001",
            prompt="Define a safe following distance.",
            state_scope="ALL",
            topic="safety",
            option_a="One second",
            option_b="Two seconds",
            option_c="Four seconds",
            option_d="None",
            correct_option="B",
            explanation="Use the two-second rule in good conditions.",
        ),
        Question(
            qid="VIC-001",
            prompt="When must headlights be used?",
            state_scope="VIC",
            topic="rules",
            option_a="At night only",
            option_b="When visibility is low",
            option_c="Only on freeways",
            option_d="Never",
            correct_option="B",
            explanation="Headlights are required when visibility is reduced.",
        ),
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
        AvailabilitySlot(
            coach=admin_coach,
            start_time=now + timedelta(days=3, hours=1),
            duration_minutes=60,
            location_text="Online video session",
        ),
    ]

    booking = Appointment(slot=slots[0], student=students[0])
    slots[0].status = "booked"

    db.session.add(coach)
    db.session.add(admin_coach)
    db.session.add_all(students)
    db.session.add_all(summaries)
    db.session.add_all(exam_rules)
    db.session.add_all(questions)
    db.session.flush()

    paper_nsw = MockExamPaper(state="NSW", title="NSW Paper A", time_limit_minutes=45)
    paper_nsw_b = MockExamPaper(state="NSW", title="NSW Paper B", time_limit_minutes=45)
    paper_vic = MockExamPaper(state="VIC", title="VIC Paper A", time_limit_minutes=40)
    db.session.add_all([paper_nsw, paper_nsw_b, paper_vic])
    db.session.flush()

    question_lookup = {question.qid: question for question in questions}

    db.session.add_all(
        [
            MockExamPaperQuestion(paper_id=paper_nsw.id, question_id=question_lookup["NSW-001"].id, position=1),
            MockExamPaperQuestion(paper_id=paper_nsw.id, question_id=question_lookup["CORE-001"].id, position=2),
            MockExamPaperQuestion(paper_id=paper_nsw_b.id, question_id=question_lookup["NSW-001"].id, position=1),
            MockExamPaperQuestion(paper_id=paper_nsw_b.id, question_id=question_lookup["CORE-001"].id, position=2),
            MockExamPaperQuestion(paper_id=paper_vic.id, question_id=question_lookup["CORE-001"].id, position=1),
            MockExamPaperQuestion(paper_id=paper_vic.id, question_id=question_lookup["VIC-001"].id, position=2),
        ]
    )
    db.session.add_all(slots)
    db.session.flush()

    admin_entry = Admin(id=admin_coach.id)
    db.session.add(admin_entry)
    db.session.add(booking)
    db.session.commit()
    app.logger.info(
        "Demo data created: coach login coach@example.com / password123; admin login admin@example.com / password123"
    )
