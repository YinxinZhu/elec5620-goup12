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
        phone="0400111222",
        city="Sydney",
        state="NSW",
        vehicle_types="AT,MT",
        bio="Former RMS examiner with 10+ years of coaching experience.",
    )
    coach.set_password("password123")

    admin_coach = Coach(
        email="admin@example.com",
        name="Platform Administrator",
        phone="0400999000",
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
            state="QLD",
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

    STATE_EXAM_CONFIG: dict[str, dict[str, int]] = {
        "NSW": {"questions": 45, "pass_mark": 38, "time_limit": 45, "papers": 2, "bank": 120},
        "VIC": {"questions": 42, "pass_mark": 36, "time_limit": 40, "papers": 1, "bank": 60},
        "QLD": {"questions": 45, "pass_mark": 38, "time_limit": 45, "papers": 1, "bank": 60},
        "SA": {"questions": 40, "pass_mark": 34, "time_limit": 40, "papers": 1, "bank": 60},
    }

    exam_rules = [
        ExamRule(
            state=state,
            total_questions=config["questions"],
            pass_mark=config["pass_mark"],
            time_limit_minutes=config["time_limit"],
        )
        for state, config in STATE_EXAM_CONFIG.items()
    ]

    LETTERS = ("A", "B", "C", "D")
    OPTION_SNIPPETS = (
        "Slow down smoothly to create extra space.",
        "Check mirrors and blind spots before acting.",
        "Signal intentions clearly for surrounding traffic.",
        "Maintain a generous following gap to stay safe.",
    )
    TOPICS = ("Road Rules", "Hazard Perception", "Safe Driving", "Vehicle Control", "Road Signs")

    questions: list[Question] = []
    questions_by_state: dict[str, list[Question]] = {}
    for state, config in STATE_EXAM_CONFIG.items():
        for index in range(1, config["bank"] + 1):
            topic = TOPICS[(index - 1) % len(TOPICS)]
            option_map = {
                letter: f"{snippet} (scenario {index} in {state})."
                for letter, snippet in zip(LETTERS, OPTION_SNIPPETS)
            }
            correct_letter = LETTERS[(index - 1) % len(LETTERS)]
            question = Question(
                qid=f"{state}-{index:03d}",
                prompt=f"{state} practice scenario {index}: {topic} decision.",
                state_scope=state,
                topic=topic.lower(),
                option_a=option_map["A"],
                option_b=option_map["B"],
                option_c=option_map["C"],
                option_d=option_map["D"],
                correct_option=correct_letter,
                explanation=(
                    f"{option_map[correct_letter]} This reinforces {topic.lower()} awareness."
                ),
            )
            questions.append(question)
            questions_by_state.setdefault(state, []).append(question)

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

    papers: list[MockExamPaper] = []
    paper_registry: dict[str, list[MockExamPaper]] = {}
    for state, config in STATE_EXAM_CONFIG.items():
        for paper_index in range(config["papers"]):
            suffix = chr(ord("A") + paper_index)
            paper = MockExamPaper(
                state=state,
                title=f"{state} Paper {suffix}",
                time_limit_minutes=config["time_limit"],
            )
            papers.append(paper)
            paper_registry.setdefault(state, []).append(paper)
    db.session.add_all(papers)
    db.session.flush()

    paper_questions: list[MockExamPaperQuestion] = []
    for state, paper_list in paper_registry.items():
        state_questions = questions_by_state[state]
        config = STATE_EXAM_CONFIG[state]
        per_paper = config["questions"]
        for paper_index, paper in enumerate(paper_list):
            start = paper_index * per_paper
            subset = state_questions[start : start + per_paper]
            for position, question in enumerate(subset, start=1):
                paper_questions.append(
                    MockExamPaperQuestion(
                        paper_id=paper.id,
                        question_id=question.id,
                        position=position,
                    )
                )

    db.session.add_all(paper_questions)
    db.session.add_all(slots)
    db.session.flush()

    admin_entry = Admin(id=admin_coach.id)
    db.session.add(admin_entry)
    db.session.add(booking)
    db.session.commit()
    app.logger.info(
        "Demo data created: coach login coach@example.com / password123; admin login admin@example.com / password123"
    )
