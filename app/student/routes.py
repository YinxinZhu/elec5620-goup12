from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Appointment, AvailabilitySlot, Student
from ..services import StateSwitchError, switch_student_state

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

LANGUAGE_CHOICES: list[str] = ["ENGLISH", "CHINESE"]


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
