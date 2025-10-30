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
    NotebookEntry,
    Question,
    QuestionAttempt,
    StarredQuestion,
    Student,
    StudentExamAnswer,
    StudentExamSession,
    StudentStateProgress,
    VariantQuestion,
    VariantQuestionGroup,
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
        mobile_number="0400 111 222",
        city="Sydney",
        state="NSW",
        vehicle_types="AT,MT",
        bio="Former RMS examiner with 10+ years of coaching experience.",
    )
    coach.set_password("password123")

    admin_coach = Coach(
        email="admin@example.com",
        name="Platform Administrator",
        mobile_number="0400 999 000",
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
            preferred_language="CHINESE",
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

    translated_questions: list[Question] = []
    for state, state_questions in questions_by_state.items():
        for original in state_questions[:10]:
            scenario_number = original.qid.split("-")[-1]
            translated_questions.append(
                Question(
                    qid=original.qid,
                    prompt=f"{state} 场景 {scenario_number}：{original.topic.title()} 决策（中文）。",
                    language="CHINESE",
                    state_scope=original.state_scope,
                    topic=original.topic,
                    option_a=f"选项A：{original.option_a}",
                    option_b=f"选项B：{original.option_b}",
                    option_c=f"选项C：{original.option_c}",
                    option_d=f"选项D：{original.option_d}",
                    correct_option=original.correct_option,
                    explanation=f"重点：保持{original.topic}技能。（中文提示）",
                )
            )

    questions.extend(translated_questions)

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

    attempts: list[QuestionAttempt] = []
    for offset, question in enumerate(questions_by_state["NSW"][:12], start=1):
        attempted_at = now - timedelta(days=6 - (offset // 3))
        is_correct = offset % 4 != 0
        chosen_option = (
            question.correct_option
            if is_correct
            else ("A" if question.correct_option != "A" else "B")
        )
        attempts.append(
            QuestionAttempt(
                student=students[0],
                question=question,
                state="NSW",
                is_correct=is_correct,
                chosen_option=chosen_option,
                time_spent_seconds=45 + offset * 3,
                attempted_at=attempted_at,
            )
        )

    for offset, question in enumerate(questions_by_state["NSW"][5:15], start=1):
        attempted_at = now - timedelta(days=offset % 5)
        is_correct = offset % 2 == 1
        chosen_option = (
            question.correct_option
            if is_correct
            else ("C" if question.correct_option != "C" else "D")
        )
        attempts.append(
            QuestionAttempt(
                student=students[1],
                question=question,
                state="NSW",
                is_correct=is_correct,
                chosen_option=chosen_option,
                time_spent_seconds=50 + offset * 2,
                attempted_at=attempted_at,
            )
        )

    for offset, question in enumerate(questions_by_state["VIC"][:8], start=1):
        attempted_at = now - timedelta(days=offset % 4)
        chosen_option = question.correct_option
        attempts.append(
            QuestionAttempt(
                student=students[2],
                question=question,
                state="VIC",
                is_correct=True,
                chosen_option=chosen_option,
                time_spent_seconds=55 + offset,
                attempted_at=attempted_at,
            )
        )

    notebook_entries = [
        NotebookEntry(
            student=students[0],
            question=questions_by_state["NSW"][2],
            state="NSW",
            wrong_count=2,
            last_wrong_at=now - timedelta(days=2),
        ),
        NotebookEntry(
            student=students[0],
            question=questions_by_state["NSW"][4],
            state="NSW",
            wrong_count=1,
            last_wrong_at=now - timedelta(days=1),
        ),
        NotebookEntry(
            student=students[1],
            question=questions_by_state["NSW"][7],
            state="NSW",
            wrong_count=3,
            last_wrong_at=now - timedelta(days=3),
        ),
    ]

    progress_records = [
        StudentStateProgress(
            student=students[0],
            state="NSW",
            first_visited_at=now - timedelta(days=21),
            last_active_at=now - timedelta(days=1),
        ),
        StudentStateProgress(
            student=students[0],
            state="VIC",
            first_visited_at=now - timedelta(days=18),
            last_active_at=now - timedelta(days=5),
        ),
        StudentStateProgress(
            student=students[1],
            state="NSW",
            first_visited_at=now - timedelta(days=7),
            last_active_at=now - timedelta(days=1),
        ),
    ]

    variant_group = VariantQuestionGroup(
        student=students[0],
        base_question=questions_by_state["NSW"][0],
        knowledge_point_name="Safe following distance",
        knowledge_point_summary="记住两秒规则并根据天气调整距离。",
        created_at=now - timedelta(days=3),
    )

    variant_questions = [
        VariantQuestion(
            group=variant_group,
            student=students[0],
            prompt="在雨天驾驶时保持怎样的安全跟车距离？",
            option_a="保持至少两秒的时间间隔。",
            option_b="维持一秒间隔即可。",
            option_c="紧跟前车防止其他车辆插队。",
            option_d="依赖 ABS 无需额外间隔。",
            correct_option="A",
            explanation="路面湿滑时延长跟车距离能够提供更多反应时间。",
        ),
        VariantQuestion(
            group=variant_group,
            student=students[0],
            prompt="在高速路段保持安全跟车距离的最佳做法是什么？",
            option_a="保持至少三秒间隔并根据速度调整。",
            option_b="使用巡航控制接近前车。",
            option_c="将注意力集中在后视镜上。",
            option_d="频繁变道以保持车速。",
            correct_option="A",
            explanation="高速时需要更长距离来应对突发情况。",
        ),
    ]

    starred = [
        StarredQuestion(student=students[0], question=questions_by_state["NSW"][1]),
        StarredQuestion(student=students[1], question=questions_by_state["NSW"][8]),
    ]

    session_attempt = StudentExamSession(
        student=students[0],
        state="NSW",
        paper=paper_registry["NSW"][0],
        status="submitted",
        started_at=now - timedelta(days=4, hours=2),
        finished_at=now - timedelta(days=4, hours=1, minutes=15),
        expires_at=now - timedelta(days=4) + timedelta(hours=3),
        score=40,
        total_questions=STATE_EXAM_CONFIG["NSW"]["questions"],
    )

    exam_answers = []
    for question in questions_by_state["NSW"][:5]:
        exam_answers.append(
            StudentExamAnswer(
                session=session_attempt,
                question=question,
                selected_option=question.correct_option,
                is_correct=True,
                answered_at=session_attempt.started_at + timedelta(minutes=5),
            )
        )

    summaries.extend(
        [
            MockExamSummary(
                student=students[0],
                state="NSW",
                score=95,
                taken_at=now - timedelta(days=3),
            ),
            MockExamSummary(
                student=students[1],
                state="NSW",
                score=82,
                taken_at=now - timedelta(days=2),
            ),
        ]
    )

    db.session.add_all(summaries)
    db.session.add_all(attempts)
    db.session.add_all(notebook_entries)
    db.session.add_all(progress_records)
    db.session.add(variant_group)
    db.session.add_all(variant_questions)
    db.session.add_all(starred)
    db.session.add(session_attempt)
    db.session.add_all(exam_answers)

    admin_entry = Admin(id=admin_coach.id)
    db.session.add(admin_entry)
    db.session.add(booking)
    db.session.commit()
    app.logger.info(
        "Demo data created: coach login coach@example.com / password123; admin login admin@example.com / password123"
    )
