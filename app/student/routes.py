from __future__ import annotations

from datetime import datetime
from math import ceil
import random

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from .. import db
from ..i18n import get_language_choices
from ..models import (
    Appointment,
    AvailabilitySlot,
    MockExamPaper,
    Question,
    Student,
    StudentExamSession,
)
from ..services import StateSwitchError, switch_student_state
from ..services.mock_exam_sessions import (
    ExamQuestionScopeError,
    ExamRuleMissingError,
    ExamSessionConflictError,
    ensure_session_active,
    record_answer,
    session_questions,
    start_session,
    submit_session,
)

student_bp = Blueprint("student", __name__, url_prefix="/student")

STATE_CHOICES: list[str] = [
    "ACT",
    "NSW",
    "NT",
    "QLD",
    "SA",
    "TAS",
    "VIC",
    "WA",
]

LANGUAGE_CHOICES: list[str] = [choice["code"] for choice in get_language_choices()]
VALID_OPTIONS = {"A", "B", "C", "D"}
PRACTICE_DEFAULT_COUNT = 5
PRACTICE_MAX_COUNT = 30


def _current_student() -> Student | None:
    if not current_user.is_authenticated:
        return None
    student = current_user._get_current_object()
    if isinstance(student, Student):
        return student
    return None


def _redirect_non_students():
    if not current_user.is_authenticated:
        return redirect(url_for("coach.login"))
    flash("Only student accounts may access the learner portal.", "warning")
    return redirect(url_for("coach.dashboard"))


def _current_exam_session(student: Student) -> StudentExamSession | None:
    session_obj = (
        StudentExamSession.query.filter_by(student_id=student.id, status="ongoing")
        .order_by(StudentExamSession.started_at.desc())
        .first()
    )
    if not session_obj:
        return None
    session_obj = ensure_session_active(session_obj)
    if session_obj.status != "ongoing":
        return None
    return session_obj


@student_bp.route("/dashboard")
@login_required
def dashboard():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    upcoming_appointments = (
        Appointment.query.join(AvailabilitySlot)
        .filter(Appointment.student_id == student.id)
        .filter(AvailabilitySlot.start_time >= datetime.utcnow())
        .order_by(AvailabilitySlot.start_time.asc())
        .all()
    )
    latest_summary = student.mock_exam_summaries[-1] if student.mock_exam_summaries else None

    return render_template(
        "student/dashboard.html",
        upcoming_appointments=upcoming_appointments,
        latest_summary=latest_summary,
    )


@student_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    if request.method == "POST":
        student.name = request.form.get("name", student.name)
        email = (request.form.get("email") or "").strip() or None
        if email and Student.query.filter(Student.email == email, Student.id != student.id).first():
            flash("Another student account already uses that email address.", "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_choices=LANGUAGE_CHOICES,
            )
        student.email = email

        state_choice = (request.form.get("state") or "").strip().upper()
        if state_choice not in STATE_CHOICES:
            flash("Please choose a valid state or territory.", "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_choices=LANGUAGE_CHOICES,
            )

        language_choice = (request.form.get("preferred_language") or "").strip().upper()
        if language_choice in LANGUAGE_CHOICES:
            student.preferred_language = language_choice
            session["preferred_language"] = language_choice
        else:
            flash("Please choose a supported language.", "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_choices=LANGUAGE_CHOICES,
            )

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if new_password:
            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return render_template(
                    "student/profile.html",
                    state_choices=STATE_CHOICES,
                    language_choices=LANGUAGE_CHOICES,
                )
            student.set_password(new_password)

        switch_summary: str | None = None
        try:
            if state_choice != student.state:
                switch_summary = switch_student_state(
                    student, state_choice, acting_student=student
                )
            else:
                db.session.commit()
        except StateSwitchError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_choices=LANGUAGE_CHOICES,
            )

        if switch_summary:
            flash(switch_summary, "info")
        flash("Profile updated successfully!", "success")
        return redirect(url_for("student.profile"))

    return render_template(
        "student/profile.html",
        state_choices=STATE_CHOICES,
        language_choices=LANGUAGE_CHOICES,
    )


@student_bp.route("/exams")
@login_required
def exams():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    papers = (
        MockExamPaper.query.filter_by(state=student.state)
        .order_by(MockExamPaper.id.asc())
        .all()
    )
    active_session = _current_exam_session(student)

    topic_rows = (
        Question.query.with_entities(Question.topic)
        .filter((Question.state_scope == "ALL") | (Question.state_scope == student.state))
        .distinct()
        .order_by(Question.topic.asc())
        .all()
    )
    topics = [row[0] for row in topic_rows if row[0]]

    return render_template(
        "student/exams.html",
        papers=papers,
        active_session=active_session,
        practice_default=PRACTICE_DEFAULT_COUNT,
        practice_max=PRACTICE_MAX_COUNT,
        topics=topics,
        state=student.state,
    )


@student_bp.post("/exams/start/<int:paper_id>")
@login_required
def start_exam(paper_id: int):
    student = _current_student()
    if not student:
        return _redirect_non_students()

    paper = MockExamPaper.query.filter_by(id=paper_id, state=student.state).first()
    if not paper:
        flash("Selected exam paper is not available for your state.", "warning")
        return redirect(url_for("student.exams"))

    allowed_states = {student.state, "ALL"}
    if not any(pq.question.state_scope in allowed_states for pq in paper.questions):
        flash("This paper has no questions aligned with your state syllabus.", "warning")
        return redirect(url_for("student.exams"))

    try:
        result = start_session(student, paper)
    except ExamSessionConflictError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("student.exams"))

    session_obj = result.session
    return redirect(url_for("student.exam_session", session_id=session_obj.id))


@student_bp.route("/exams/sessions/<int:session_id>", methods=["GET", "POST"])
@login_required
def exam_session(session_id: int):
    student = _current_student()
    if not student:
        return _redirect_non_students()

    session_obj = StudentExamSession.query.filter_by(id=session_id, student_id=student.id).first_or_404()
    session_obj = ensure_session_active(session_obj)

    questions = session_questions(session_obj)
    if not questions:
        flash("Exam paper has no questions configured.", "warning")
        return redirect(url_for("student.exams"))

    try:
        requested_index = int(request.args.get("q", "1")) - 1
    except ValueError:
        requested_index = 0
    current_index = max(0, min(requested_index, len(questions) - 1))
    if request.method == "POST":
        action = request.form.get("action") or ""
        if action == "submit_exam":
            try:
                submit_session(session_obj)
                flash("Exam submitted successfully.", "success")
            except ExamRuleMissingError as exc:
                flash(str(exc), "danger")
            return redirect(url_for("student.exam_session", session_id=session_id))

        if session_obj.status != "ongoing":
            flash("Exam session already finished.", "info")
            return redirect(url_for("student.exam_session", session_id=session_id))

        selected_option = (request.form.get("selected_option") or "").strip().upper()
        question_id = request.form.get("question_id")
        try:
            question_id_int = int(question_id or "0")
        except ValueError:
            question_id_int = 0

        if selected_option not in VALID_OPTIONS or not question_id_int:
            flash("Please choose an answer option before saving.", "warning")
        else:
            try:
                record_answer(session_obj, question_id_int, selected_option)
                flash("Answer saved.", "success")
            except ExamQuestionScopeError:
                flash("Question not part of this exam.", "danger")

        try:
            navigate_to = int(request.form.get("navigate_to", current_index + 1))
        except ValueError:
            navigate_to = current_index + 1
        target_index = max(1, min(navigate_to, len(questions)))
        return redirect(url_for("student.exam_session", session_id=session_id, q=target_index))

    submission = None
    incorrect_only = False
    review_page = 1
    review_total_pages = 1
    review_questions = []
    incorrect_count = 0
    if session_obj.status in {"submitted", "abandoned"}:
        try:
            submission = submit_session(session_obj)
        except ExamRuleMissingError as exc:
            flash(str(exc), "danger")
            submission = None

    if submission:
        incorrect_items = [
            item
            for item in questions
            if not (item.answer and item.answer.is_correct)
        ]
        incorrect_count = len(incorrect_items)

        review_filter = (request.args.get("review") or "all").strip().lower()
        incorrect_only = review_filter == "incorrect"
        filtered_questions = incorrect_items if incorrect_only else questions

        total_filtered = len(filtered_questions)
        if total_filtered:
            try:
                review_page = int(request.args.get("page", "1"))
            except ValueError:
                review_page = 1
            review_page = max(1, review_page)
            review_total_pages = max(1, ceil(total_filtered / 5))
            if review_page > review_total_pages:
                review_page = review_total_pages
            start_index = (review_page - 1) * 5
            end_index = start_index + 5
            review_questions = filtered_questions[start_index:end_index]
        else:
            review_page = 1
            review_total_pages = 1
            review_questions = []
    else:
        review_questions = questions

    answered_ids = {
        payload.question.id for payload in questions if payload.answer and payload.answer.selected_option
    }

    remaining_seconds = 0
    if session_obj.status == "ongoing" and session_obj.expires_at:
        remaining_seconds = max(0, int((session_obj.expires_at - datetime.utcnow()).total_seconds()))

    return render_template(
        "student/exam_session.html",
        exam_session=session_obj,
        questions=questions,
        current_index=current_index,
        submission=submission,
        answered_ids=answered_ids,
        remaining_seconds=remaining_seconds,
        review_questions=review_questions,
        review_page=review_page,
        review_total_pages=review_total_pages,
        incorrect_count=incorrect_count,
        incorrect_only=incorrect_only,
    )


@student_bp.route("/exams/practice", methods=["GET", "POST"])
@login_required
def practice():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    if request.method == "POST":
        try:
            count = int(request.form.get("question_count", PRACTICE_DEFAULT_COUNT))
        except (TypeError, ValueError):
            count = PRACTICE_DEFAULT_COUNT
        count = max(1, min(count, PRACTICE_MAX_COUNT))
        topic = (request.form.get("topic") or "").strip()

        query = Question.query.filter(
            (Question.state_scope == "ALL") | (Question.state_scope == student.state)
        )
        if topic:
            query = query.filter(Question.topic.ilike(f"%{topic}%"))

        questions = query.all()
        if not questions:
            flash("No questions available for the selected criteria.", "warning")
            return redirect(url_for("student.exams"))

        selected = random.sample(questions, min(count, len(questions)))
        session["practice_questions"] = [question.id for question in selected]
        session["practice_topic"] = topic
        session.modified = True
        return redirect(url_for("student.practice"))

    question_ids: list[int] = session.get("practice_questions", [])
    if not question_ids:
        flash("Start a practice session from the exam hub.", "info")
        return redirect(url_for("student.exams"))

    questions = Question.query.filter(Question.id.in_(question_ids)).all()
    lookup = {question.id: question for question in questions}
    ordered_questions = [lookup[qid] for qid in question_ids if qid in lookup]

    return render_template(
        "student/practice.html",
        questions=ordered_questions,
        practice_topic=session.get("practice_topic"),
        state=student.state,
    )
