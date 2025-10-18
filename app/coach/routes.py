from __future__ import annotations

from datetime import datetime
from typing import Iterable

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from .. import db
from ..models import Appointment, AvailabilitySlot, Coach, MockExamSummary, Student

coach_bp = Blueprint("coach", __name__, url_prefix="/coach")


def _parse_vehicle_types(values: Iterable[str]) -> str:
    allowed = {"AT", "MT"}
    cleaned = {v for v in (value.strip().upper() for value in values) if v in allowed}
    return ",".join(sorted(cleaned))


@coach_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        coach = Coach.query.filter(func.lower(Coach.email) == email).first()
        if coach and coach.check_password(password):
            login_user(coach)
            flash("Welcome back!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("coach.dashboard"))
        flash("Invalid email or password", "danger")
    return render_template("coach/login.html")


@coach_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("coach.login"))


@coach_bp.route("/dashboard")
@login_required
def dashboard():
    upcoming_slots = (
        AvailabilitySlot.query.filter_by(coach_id=current_user.id)
        .filter(AvailabilitySlot.start_time >= datetime.utcnow())
        .order_by(AvailabilitySlot.start_time.asc())
        .limit(5)
        .all()
    )
    student_count = Student.query.filter_by(assigned_coach_id=current_user.id).count()
    pending_bookings = (
        Appointment.query.join(AvailabilitySlot)
        .filter(AvailabilitySlot.coach_id == current_user.id)
        .filter(Appointment.status == "booked")
        .count()
    )
    return render_template(
        "coach/dashboard.html",
        upcoming_slots=upcoming_slots,
        student_count=student_count,
        pending_bookings=pending_bookings,
    )


@coach_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.name = request.form.get("name", current_user.name)
        current_user.phone = request.form.get("phone", current_user.phone)
        current_user.city = request.form.get("city", current_user.city)
        current_user.state = request.form.get("state", current_user.state)
        vehicle_inputs = request.form.getlist("vehicle_types")
        types = _parse_vehicle_types(vehicle_inputs)
        if not types:
            flash("Please select at least one vehicle type (AT/MT).", "warning")
            return render_template("coach/profile.html")
        current_user.vehicle_types = types
        current_user.bio = request.form.get("bio", current_user.bio)
        db.session.commit()
        flash("Profile updated successfully", "success")
        return redirect(url_for("coach.profile"))
    return render_template("coach/profile.html")


@coach_bp.route("/students")
@login_required
def students():
    students = (
        Student.query.filter_by(assigned_coach_id=current_user.id)
        .order_by(Student.name.asc())
        .all()
    )
    summaries = {
        student.id: {
            "attempts": len(student.mock_exam_summaries),
            "last_score": student.mock_exam_summaries[-1].score
            if student.mock_exam_summaries
            else None,
        }
        for student in students
    }
    return render_template("coach/students.html", students=students, summaries=summaries)


@coach_bp.route("/slots", methods=["GET", "POST"])
@login_required
def slots():
    if request.method == "POST":
        try:
            start_time = datetime.fromisoformat(request.form["start_time"])  # type: ignore[arg-type]
        except (KeyError, ValueError):
            flash("Invalid start time format", "danger")
            return redirect(url_for("coach.slots"))
        duration = int(request.form.get("duration", 30))
        if duration not in {30, 60}:
            flash("Duration must be either 30 or 60 minutes.", "warning")
            return redirect(url_for("coach.slots"))
        location_text = request.form.get("location", "").strip()
        if not location_text:
            flash("Location is required", "warning")
            return redirect(url_for("coach.slots"))
        slot = AvailabilitySlot(
            coach_id=current_user.id,
            start_time=start_time,
            duration_minutes=duration,
            location_text=location_text,
        )
        db.session.add(slot)
        try:
            db.session.commit()
            flash("Slot created", "success")
        except Exception as exc:  # broad to catch unique constraint
            db.session.rollback()
            flash("Unable to create slot: duplicate or invalid data", "danger")
        return redirect(url_for("coach.slots"))

    slots = (
        AvailabilitySlot.query.filter_by(coach_id=current_user.id)
        .order_by(AvailabilitySlot.start_time.asc())
        .all()
    )
    return render_template("coach/slots.html", slots=slots)


@coach_bp.route("/slots/<int:slot_id>/delete", methods=["POST"])
@login_required
def delete_slot(slot_id: int):
    slot = AvailabilitySlot.query.filter_by(id=slot_id, coach_id=current_user.id).first_or_404()
    if slot.appointment and slot.appointment.status == "booked":
        flash("Cannot delete a slot with an active booking.", "danger")
        return redirect(url_for("coach.slots"))
    db.session.delete(slot)
    db.session.commit()
    flash("Slot removed", "info")
    return redirect(url_for("coach.slots"))


@coach_bp.route("/appointments")
@login_required
def appointments():
    appointments = (
        Appointment.query.join(AvailabilitySlot)
        .filter(AvailabilitySlot.coach_id == current_user.id)
        .order_by(AvailabilitySlot.start_time.desc())
        .all()
    )
    return render_template("coach/appointments.html", appointments=appointments)


@coach_bp.route("/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_appointment_status(appointment_id: int):
    appointment = (
        Appointment.query.join(AvailabilitySlot)
        .filter(AvailabilitySlot.coach_id == current_user.id)
        .filter(Appointment.id == appointment_id)
        .first_or_404()
    )
    status = request.form.get("status")
    if status not in {"booked", "cancelled", "completed"}:
        flash("Invalid status", "danger")
        return redirect(url_for("coach.appointments"))
    appointment.status = status
    if status == "cancelled":
        appointment.slot.status = "available"
    elif status == "completed":
        appointment.slot.status = "unavailable"
    db.session.commit()
    flash("Appointment updated", "success")
    return redirect(url_for("coach.appointments"))
