from __future__ import annotations

from datetime import datetime, time, timedelta
from math import ceil
import random

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from .. import db
from ..i18n import (
    DEFAULT_LANGUAGE,
    ensure_language_code,
    get_language_choices,
    translate_text,
)
from ..models import (
    Appointment,
    AvailabilitySlot,
    MockExamPaper,
    MockExamSummary,
    NotebookEntry,
    Question,
    Student,
    StudentExamSession,
    StudentStateProgress,
    VariantQuestion,
    VariantQuestionGroup,
)
from ..services import StateSwitchError, get_questions_for_state, switch_student_state
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
from ..services.progress import (
    ProgressAccessError,
    ProgressValidationError,
    ProgressTrendPoint,
    get_progress_summary,
    get_progress_trend,
)
from ..services.variant_generation import (
    derive_knowledge_point,
    generate_question_variants,
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

LANGUAGE_CODES: list[str] = [choice["code"] for choice in get_language_choices()]
VALID_OPTIONS = {"A", "B", "C", "D"}
PRACTICE_DEFAULT_COUNT = 5
PRACTICE_MAX_COUNT = 30
VARIANT_DEFAULT_COUNT = 3  # Default number of variants to generate
VARIANT_MIN_COUNT = 1  # Minimum variants allowed per request
VARIANT_MAX_COUNT = 5  # Maximum variants allowed per request


def _t(message: str, **values: str) -> str:
    language = ensure_language_code(getattr(g, "active_language", DEFAULT_LANGUAGE))
    return translate_text(message, language, **values)


STATUS_LABELS = {
    "booked": "Booked",
    "pending_cancel": "Pending cancellation",
    "cancelled": "Cancelled",
    "completed": "Completed",
}


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
    flash(_t("Only student accounts may access the learner portal."), "warning")
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


def _existing_variant_group(student_id: int, question_id: int) -> VariantQuestionGroup | None:
    """Return the most recent variant group for the given student/question pair."""

    return (
        VariantQuestionGroup.query.filter_by(
            student_id=student_id,
            base_question_id=question_id,
        )
        .order_by(VariantQuestionGroup.created_at.desc())
        .first()
    )


def _normalise_variant_count(raw_value: str | None) -> int:
    """Clamp the requested variant count into the accepted generation range."""

    try:
        parsed_value = int(raw_value) if raw_value is not None else VARIANT_DEFAULT_COUNT
    except ValueError:
        parsed_value = VARIANT_DEFAULT_COUNT
    return max(VARIANT_MIN_COUNT, min(parsed_value, VARIANT_MAX_COUNT))


def _question_accessible(question: Question, student: Student) -> bool:
    """Check whether the student can view or generate variants for the question."""

    return question.state_scope in {"ALL", student.state}


@student_bp.route("/dashboard")
@login_required
def dashboard():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    now = datetime.utcnow()
    upcoming_records = (
        Appointment.query.join(AvailabilitySlot)
        .filter(Appointment.student_id == student.id)
        .filter(Appointment.status.in_(["booked", "pending_cancel"]))
        .filter(AvailabilitySlot.start_time >= now)
        .order_by(AvailabilitySlot.start_time.asc())
        .all()
    )
    upcoming_appointments: list[dict[str, object]] = []
    for record in upcoming_records:
        delta = record.slot.start_time - now
        hours_until = delta.total_seconds() / 3600
        if record.status == "pending_cancel":
            cancel_mode = "pending"
        elif hours_until < 2:
            cancel_mode = "locked"
        elif hours_until < 24:
            cancel_mode = "needs_approval"
        else:
            cancel_mode = "self_service"
        upcoming_appointments.append(
            {
                "appointment": record,
                "hours_until": max(hours_until, 0.0),
                "cancel_mode": cancel_mode,
                "status_label": _t(
                    STATUS_LABELS.get(
                        record.status, record.status.replace("_", " ")
                    )
                ),
            }
        )
    latest_summary = student.mock_exam_summaries[-1] if student.mock_exam_summaries else None

    assigned_coach = student.coach
    available_slots: list[AvailabilitySlot] = []
    if assigned_coach:
        available_slots = (
            AvailabilitySlot.query.filter_by(coach_id=assigned_coach.id, status="available")
            .filter(AvailabilitySlot.start_time >= now)
            .order_by(AvailabilitySlot.start_time.asc())
            .limit(6)
            .all()
        )

    return render_template(
        "student/dashboard.html",
        upcoming_appointments=upcoming_appointments,
        latest_summary=latest_summary,
        available_slots=available_slots,
        assigned_coach=assigned_coach,
    )


@student_bp.route("/slots/<int:slot_id>/book", methods=["POST"])
@login_required
def book_slot(slot_id: int):
    student = _current_student()
    if not student:
        return _redirect_non_students()

    slot = AvailabilitySlot.query.filter_by(id=slot_id).first_or_404()

    if not student.assigned_coach_id:
        flash(_t("Assign a coach before booking a session."), "warning")
        return redirect(url_for("student.dashboard"))

    if slot.coach_id != student.assigned_coach_id:
        flash(_t("This timeslot belongs to a different coach."), "danger")
        return redirect(url_for("student.dashboard"))

    if slot.start_time < datetime.utcnow():
        flash(_t("This session is no longer available."), "warning")
        return redirect(url_for("student.dashboard"))

    if slot.status != "available" or (slot.appointment and slot.appointment.status == "booked"):
        flash(
            _t("That timeslot has already been reserved. Please choose another one."),
            "warning",
        )
        return redirect(url_for("student.dashboard"))

    appointment = Appointment(slot_id=slot.id, student_id=student.id)
    slot.status = "booked"
    db.session.add(appointment)
    db.session.commit()

    start_text = slot.start_time.strftime("%d %b %Y %H:%M")
    flash(
        _t(
            "Session booked with {coach} on {start_time}.",
            coach=slot.coach.name,
            start_time=start_text,
        ),
        "success",
    )
    return redirect(url_for("student.dashboard"))


@student_bp.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel_appointment(appointment_id: int):
    student = _current_student()
    if not student:
        return _redirect_non_students()

    appointment = (
        Appointment.query.join(AvailabilitySlot)
        .filter(Appointment.id == appointment_id)
        .filter(Appointment.student_id == student.id)
        .first_or_404()
    )

    if appointment.status not in {"booked", "pending_cancel"}:
        flash(_t("This session can no longer be modified."), "warning")
        return redirect(url_for("student.dashboard"))

    now = datetime.utcnow()
    start_time = appointment.slot.start_time
    hours_until = (start_time - now).total_seconds() / 3600

    if appointment.status == "pending_cancel":
        flash(_t("Your cancellation request is awaiting coach approval."), "info")
        return redirect(url_for("student.dashboard"))

    if hours_until < 2:
        flash(
            _t(
                "Sessions cannot be cancelled within 2 hours of the start time. Please contact your coach directly."
            ),
            "danger",
        )
        return redirect(url_for("student.dashboard"))

    if hours_until < 24:
        appointment.status = "pending_cancel"
        appointment.cancellation_requested_at = now
        db.session.commit()
        flash(
            _t(
                "Cancellation request sent. Your coach will confirm whether the session can be released."
            ),
            "info",
        )
        return redirect(url_for("student.dashboard"))

    appointment.status = "cancelled"
    appointment.cancellation_requested_at = now
    appointment.slot.status = "available"
    db.session.commit()
    flash(_t("Session cancelled. The slot is now available for rebooking."), "success")
    return redirect(url_for("student.dashboard"))


@student_bp.route("/progress", methods=["GET", "POST"], endpoint="progress")
@login_required
def progress_overview():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    def _normalise(code: str | None) -> str:
        return (code or "").strip().upper()

    def _parse_date_param(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    requested_state = _normalise(request.args.get("state"))

    progress_records = (
        StudentStateProgress.query.with_entities(
            func.upper(StudentStateProgress.state).label("state"),
            StudentStateProgress.last_active_at,
        )
        .filter_by(student_id=student.id)
        .order_by(StudentStateProgress.last_active_at.desc())
        .all()
    )

    available_states: list[str] = []
    seen: set[str] = set()
    for state_code, _last_active in progress_records:
        code = _normalise(state_code)
        if code and code not in seen:
            available_states.append(code)
            seen.add(code)

    current_state = _normalise(student.state)
    if current_state and current_state not in seen:
        available_states.insert(0, current_state)
        seen.add(current_state)

    selected_state = requested_state if requested_state in seen else None
    if not selected_state and available_states:
        selected_state = available_states[0]

    request_data = request.args if request.method == "GET" else request.form
    raw_topic = (request_data.get("topic") or "").strip()
    start_date = _parse_date_param(request_data.get("start"))
    end_date = _parse_date_param(request_data.get("end"))
    filter_error: str | None = None
    if start_date and end_date and start_date > end_date:
        filter_error = _t("Start date must be before end date.")
        start_date = end_date = None

    start_at = datetime.combine(start_date, time.min) if start_date else None
    end_at = datetime.combine(end_date, time.max) if end_date else None

    today = datetime.utcnow().date()
    trend_default_start = datetime.combine(today - timedelta(days=29), time.min)
    trend_default_end = datetime.combine(today, time.max)
    trend_start_at = start_at or trend_default_start
    trend_end_at = end_at or trend_default_end

    if request.method == "POST":
        goal_state = _normalise(request.form.get("state")) or selected_state
        try:
            goal_completion = float(request.form.get("goal_completion", 0.0))
            goal_accuracy = float(request.form.get("goal_accuracy", 0.0))
        except ValueError:
            flash(_t("Goals must be numeric values."), "danger")
        else:
            goal_completion = max(0.0, min(goal_completion, 100.0))
            goal_accuracy = max(0.0, min(goal_accuracy, 100.0))
            session["progress_goal"] = {
                "completion": goal_completion,
                "accuracy": goal_accuracy,
            }
            flash(_t("Progress goals updated."), "success")

        redirect_params = {}
        target_state = goal_state if goal_state in seen else selected_state
        if target_state:
            redirect_params["state"] = target_state
        if raw_topic:
            redirect_params["topic"] = raw_topic
        if start_date:
            redirect_params["start"] = start_date.isoformat()
        if end_date:
            redirect_params["end"] = end_date.isoformat()
        return redirect(url_for("student.progress", **redirect_params))

    summary = None
    error_message: str | None = None
    completion_pct = pending_pct = accuracy_pct = incorrect_pct = 0.0
    available_topics: list[str] = []
    trend_points: list[ProgressTrendPoint] = []
    recent_exams = []
    recent_exam_stats: dict[str, float | int | None] | None = None
    wrong_preview: list[dict[str, object]] = []

    if selected_state:
        question_bank = get_questions_for_state(
            selected_state, language=student.preferred_language
        )
        available_topics = sorted(
            {question.topic for question in question_bank if question.topic}
        )
        topic_param = raw_topic or None
        try:
            summary = get_progress_summary(
                student,
                state=selected_state,
                acting_student=student,
                start_at=start_at,
                end_at=end_at,
                topic=topic_param,
            )
            trend_points = get_progress_trend(
                student,
                state=selected_state,
                acting_student=student,
                start_at=trend_start_at,
                end_at=trend_end_at,
                topic=topic_param,
            )
        except (ProgressValidationError, ProgressAccessError) as exc:
            error_message = str(exc)

        if summary:
            def _percent(part: int, whole: int) -> float:
                if whole <= 0:
                    return 0.0
                return round((part / whole) * 100, 1)

            completion_pct = _percent(summary.done, summary.total)
            pending_pct = round(max(0.0, 100.0 - completion_pct), 1)
            accuracy_pct = _percent(summary.correct, summary.done)
            incorrect_pct = round(max(0.0, 100.0 - accuracy_pct), 1)

        if not error_message:
            exam_query = MockExamSummary.query.filter_by(
                student_id=student.id, state=selected_state
            )
            if start_at:
                exam_query = exam_query.filter(MockExamSummary.taken_at >= start_at)
            if end_at:
                exam_query = exam_query.filter(MockExamSummary.taken_at <= end_at)
            recent_exams = exam_query.order_by(
                MockExamSummary.taken_at.desc()
            ).limit(5).all()

            scores = [exam.score for exam in recent_exams if exam.score is not None]
            if scores:
                recent_exam_stats = {
                    "average_score": round(sum(scores) / len(scores), 1),
                    "best_score": max(scores),
                }

            wrong_query = NotebookEntry.query.filter_by(
                student_id=student.id, state=selected_state
            )
            topic_lower = (raw_topic or "").lower()
            if topic_lower:
                wrong_query = wrong_query.join(NotebookEntry.question).filter(
                    func.lower(Question.topic) == topic_lower
                )
            if start_at:
                wrong_query = wrong_query.filter(NotebookEntry.last_wrong_at >= start_at)
            if end_at:
                wrong_query = wrong_query.filter(NotebookEntry.last_wrong_at <= end_at)
            wrong_entries = (
                wrong_query.order_by(NotebookEntry.last_wrong_at.desc().nullslast())
                .limit(3)
                .all()
            )
            wrong_preview = [
                {
                    "qid": entry.question.qid,
                    "topic": entry.question.topic,
                    "wrong_count": entry.wrong_count,
                    "last_wrong_at": entry.last_wrong_at,
                }
                for entry in wrong_entries
            ]

    saved_goal = session.get("progress_goal") or {}
    goal_completion = float(saved_goal.get("completion", 80.0))
    goal_accuracy = float(saved_goal.get("accuracy", 80.0))
    goal_status = {
        "completion": goal_completion,
        "accuracy": goal_accuracy,
        "completion_met": summary is not None and completion_pct >= goal_completion,
        "accuracy_met": summary is not None and accuracy_pct >= goal_accuracy,
        "completion_gap": round(
            max(goal_completion - completion_pct, 0.0), 1
        )
        if summary
        else goal_completion,
        "accuracy_gap": round(max(goal_accuracy - accuracy_pct, 0.0), 1)
        if summary
        else goal_accuracy,
    }

    trend_payload = [
        {
            "day": point.day.isoformat(),
            "attempted": point.attempted,
            "correct": point.correct,
            "accuracy": point.accuracy,
        }
        for point in trend_points
    ]

    trend_summary = None
    if trend_points:
        trend_summary = {
            "average_attempted": round(
                sum(point.attempted for point in trend_points) / len(trend_points), 1
            ),
            "average_accuracy": round(
                sum(point.accuracy for point in trend_points) / len(trend_points), 1
            ),
        }

    export_params = {}
    if selected_state:
        export_params["state"] = selected_state
    if raw_topic:
        export_params["topic"] = raw_topic
    if start_date:
        export_params["start"] = start_date.isoformat()
    if end_date:
        export_params["end"] = end_date.isoformat()
    export_url = url_for("api.progress_export", **export_params) if selected_state else None

    goal_form_defaults = {
        "state": selected_state or "",
        "completion": goal_completion,
        "accuracy": goal_accuracy,
        "start": start_date.isoformat() if start_date else "",
        "end": end_date.isoformat() if end_date else "",
        "topic": raw_topic,
    }

    trend_range = {
        "start": trend_start_at.date(),
        "end": trend_end_at.date(),
    }

    return render_template(
        "student/progress.html",
        available_states=available_states,
        selected_state=selected_state,
        available_topics=available_topics,
        topic_filter=raw_topic,
        start_date=start_date,
        end_date=end_date,
        filter_error=filter_error,
        summary=summary,
        error_message=error_message,
        completion_pct=completion_pct,
        pending_pct=pending_pct,
        accuracy_pct=accuracy_pct,
        incorrect_pct=incorrect_pct,
        export_url=export_url,
        trend_points=trend_payload,
        trend_summary=trend_summary,
        trend_range=trend_range,
        recent_exams=recent_exams,
        recent_exam_stats=recent_exam_stats,
        wrong_preview=wrong_preview,
        goal_status=goal_status,
        goal_form_defaults=goal_form_defaults,
    )


@student_bp.route("/notebook")
@login_required
def notebook():
    student = _current_student()
    if not student:
        return _redirect_non_students()

    def _normalise(code: str | None) -> str:
        return (code or "").strip().upper()

    requested_state = _normalise(request.args.get("state"))

    progress_records = (
        StudentStateProgress.query.with_entities(
            func.upper(StudentStateProgress.state).label("state"),
            StudentStateProgress.last_active_at,
        )
        .filter_by(student_id=student.id)
        .order_by(StudentStateProgress.last_active_at.desc())
        .all()
    )

    available_states: list[str] = []
    seen: set[str] = set()
    for state_code, _last_active in progress_records:
        code = _normalise(state_code)
        if code and code not in seen:
            available_states.append(code)
            seen.add(code)

    current_state = _normalise(student.state)
    if current_state and current_state not in seen:
        available_states.insert(0, current_state)
        seen.add(current_state)

    selected_state = requested_state if requested_state in seen else None
    if not selected_state and available_states:
        selected_state = available_states[0]

    entries = []
    total_wrong = 0
    if selected_state:
        notebook_query = (
            NotebookEntry.query.filter_by(student_id=student.id, state=selected_state)
            .join(NotebookEntry.question)
            .order_by(NotebookEntry.last_wrong_at.desc().nullslast())
        )
        entries = notebook_query.all()
        total_wrong = sum(entry.wrong_count for entry in entries)

    return render_template(
        "student/notebook.html",
        available_states=available_states,
        selected_state=selected_state,
        entries=entries,
        total_wrong=total_wrong,
    )



# Start Variant Question AI Generation:

@student_bp.route("/variants")
@login_required
def variant_list():
    """Render the catalogue of variant question groups generated by the student."""

    student = _current_student()
    if not student:
        return _redirect_non_students()

    groups = (
        VariantQuestionGroup.query.options(
            joinedload(VariantQuestionGroup.base_question),
            joinedload(VariantQuestionGroup.variants),
        )
        .filter_by(student_id=student.id)
        .order_by(VariantQuestionGroup.created_at.desc())
        .all()
    )
    group_rows: list[dict[str, object]] = []  # Payload rows consumed by the template
    for group in groups:
        student_variants = [
            variant
            for variant in group.variants
            if variant.student_id == student.id
        ]  # Only expose variants owned by the current student
        group_rows.append(
            {
                "group": group,
                "variant_total": len(student_variants),  # Number of stored variants
            }
        )

    return render_template(
        "student/variant_list.html",
        group_rows=group_rows,
    )


@student_bp.route("/variant", methods=["GET", "POST"])
@login_required
def variant():
    """Display details for a variant set or generate a new one for a question."""

    student = _current_student()
    if not student:
        return _redirect_non_students()

    raw_question_id = request.args.get("question")
    raw_group_id = request.args.get("group")
    question_id = None  # Question identifier extracted from the query string
    group_id = None  # Variant group identifier extracted from the query string

    try:
        question_id = int(raw_question_id) if raw_question_id else None
    except (TypeError, ValueError):
        question_id = None
    try:
        group_id = int(raw_group_id) if raw_group_id else None
    except (TypeError, ValueError):
        group_id = None

    if not question_id and not group_id:
        flash(_t("Select a question to generate variants."), "warning")
        return redirect(url_for("student.variant_list"))

    group = None  # VariantQuestionGroup to display on the page
    base_question = None  # Underlying question associated with the group
    generation_mode = False  # Flag indicating whether the page should show the form

    if group_id:
        group = (
            VariantQuestionGroup.query.options(
                joinedload(VariantQuestionGroup.base_question),
                joinedload(VariantQuestionGroup.variants),
            )
            .filter_by(id=group_id, student_id=student.id)
            .first()
        )
        if not group:
            flash(_t("We could not find that variant set."), "danger")
            return redirect(url_for("student.variant_list"))
        base_question = group.base_question

    if question_id and not group:
        base_question = db.session.get(Question, question_id)
        if not base_question:
            flash(_t("The requested question does not exist."), "danger")
            return redirect(url_for("student.variant_list"))
        if not _question_accessible(base_question, student):
            flash(_t("This question is not available for your state."), "danger")
            return redirect(url_for("student.variant_list"))

        group = _existing_variant_group(student.id, base_question.id)
        if not group:
            generation_mode = True

    if request.method == "POST" and generation_mode and base_question:
        requested_count = _normalise_variant_count(
            request.form.get("variant_count")
        )  # Number of variants requested via the form
        knowledge_name, knowledge_summary = derive_knowledge_point(base_question)
        group = VariantQuestionGroup(
            student_id=student.id,
            base_question_id=base_question.id,
            knowledge_point_name=knowledge_name,
            knowledge_point_summary=knowledge_summary,
        )
        db.session.add(group)
        db.session.flush()

        drafts = generate_question_variants(
            base_question, count=requested_count
        )  # Draft variants returned by the generator
        for draft in drafts:
            variant_record = VariantQuestion(
                group_id=group.id,
                student_id=student.id,
                prompt=draft.prompt,
                option_a=draft.option_a,
                option_b=draft.option_b,
                option_c=draft.option_c,
                option_d=draft.option_d,
                correct_option=draft.correct_option,
                explanation=draft.explanation,
            )
            db.session.add(variant_record)

        db.session.commit()
        generation_mode = False
        flash(_t("Variant questions generated successfully."), "success")
        # Ensure variants relationship is populated for rendering without reload.
        db.session.refresh(group)

    variant_records: list[VariantQuestion] = []  # Variants to display beneath the question
    if group and not generation_mode:
        variant_records = sorted(
            (
                variant
                for variant in group.variants
                if variant.student_id == student.id
            ),
            key=lambda item: item.created_at,
        )  # Ensure variants render chronologically and are scoped to the student

    return render_template(
        "student/variant.html",
        base_question=base_question,
        group=group,
        variants=variant_records,
        generation_mode=generation_mode,
        variant_min_count=VARIANT_MIN_COUNT,
        variant_max_count=VARIANT_MAX_COUNT,
        variant_default_count=VARIANT_DEFAULT_COUNT,
    )

# End Variant Question AI Generation:



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
            flash(_t("Another student account already uses that email address."), "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_codes=LANGUAGE_CODES,
            )
        student.email = email

        state_choice = (request.form.get("state") or "").strip().upper()
        if state_choice not in STATE_CHOICES:
            flash(_t("Please choose a valid state or territory."), "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_codes=LANGUAGE_CODES,
            )

        language_choice = (request.form.get("preferred_language") or "").strip().upper()
        if language_choice in LANGUAGE_CODES:
            student.preferred_language = language_choice
            session["preferred_language"] = language_choice
        else:
            flash(_t("Please choose a supported language."), "danger")
            return render_template(
                "student/profile.html",
                state_choices=STATE_CHOICES,
                language_codes=LANGUAGE_CODES,
            )

        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if new_password:
            if new_password != confirm_password:
                flash(_t("Passwords do not match."), "danger")
                return render_template(
                    "student/profile.html",
                    state_choices=STATE_CHOICES,
                    language_codes=LANGUAGE_CODES,
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
                language_codes=LANGUAGE_CODES,
            )

        if switch_summary:
            flash(switch_summary, "info")
        flash(_t("Profile updated successfully!"), "success")
        return redirect(url_for("student.profile"))

    return render_template(
        "student/profile.html",
        state_choices=STATE_CHOICES,
        language_codes=LANGUAGE_CODES,
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
        flash(_t("Selected exam paper is not available for your state."), "warning")
        return redirect(url_for("student.exams"))

    allowed_states = {student.state, "ALL"}
    if not any(pq.question.state_scope in allowed_states for pq in paper.questions):
        flash(_t("This paper has no questions aligned with your state syllabus."), "warning")
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
        flash(_t("Exam paper has no questions configured."), "warning")
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
                flash(_t("Exam submitted successfully."), "success")
            except ExamRuleMissingError as exc:
                flash(str(exc), "danger")
            return redirect(url_for("student.exam_session", session_id=session_id))

        if session_obj.status != "ongoing":
            flash(_t("Exam session already finished."), "info")
            return redirect(url_for("student.exam_session", session_id=session_id))

        selected_option = (request.form.get("selected_option") or "").strip().upper()
        question_id = request.form.get("question_id")
        try:
            question_id_int = int(question_id or "0")
        except ValueError:
            question_id_int = 0

        if selected_option not in VALID_OPTIONS or not question_id_int:
            flash(_t("Please choose an answer option before saving."), "warning")
        else:
            try:
                record_answer(session_obj, question_id_int, selected_option)
                flash(_t("Answer saved."), "success")
            except ExamQuestionScopeError:
                flash(_t("Question not part of this exam."), "danger")

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
            flash(_t("No questions available for the selected criteria."), "warning")
            return redirect(url_for("student.exams"))

        selected = random.sample(questions, min(count, len(questions)))
        session["practice_questions"] = [question.id for question in selected]
        session["practice_topic"] = topic
        session.modified = True
        return redirect(url_for("student.practice"))

    question_ids: list[int] = session.get("practice_questions", [])
    if not question_ids:
        flash(_t("Start a practice session from the exam hub."), "info")
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
