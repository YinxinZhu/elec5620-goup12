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
from sqlalchemy.exc import IntegrityError
from urllib.parse import urljoin, urlparse

from .. import db
from ..models import Admin, Appointment, AvailabilitySlot, Coach, MockExamSummary, Student

coach_bp = Blueprint("coach", __name__, url_prefix="/coach")

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


def _normalize_mobile_number(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _normalized_mobile_expression(column):
    sanitized = column
    for character in (" ", "-", "(", ")", "+"):
        sanitized = func.replace(sanitized, character, "")
    return sanitized


def _parse_vehicle_types(values: Iterable[str]) -> str:
    allowed = {"AT", "MT"}
    cleaned = {v for v in (value.strip().upper() for value in values) if v in allowed}
    return ",".join(sorted(cleaned))


def _normalize_mobile(raw_value: str) -> str:
    digits = "".join(ch for ch in raw_value if ch.isdigit())
    if digits:
        return digits
    return raw_value.strip()


def _require_admin_access():
    if not current_user.is_admin:
        flash("Only administrators may access personnel management.", "danger")
        return redirect(url_for("coach.dashboard"))
    return None


@coach_bp.before_app_request
def _restrict_student_portal_access():
    if request.blueprint != "coach":
        return None
    if request.endpoint in {"coach.login", "coach.register_student", "coach.logout"}:
        return None
    if request.endpoint is None:
        return None
    if not current_user.is_authenticated:
        return None
    if getattr(current_user, "is_student", False):
        flash("Student accounts should use the learner portal.", "warning")
        return redirect(url_for("student.dashboard"))
    return None

def _is_safe_redirect_target(target: str | None) -> bool:
    if not target:
        return False
    host_url = request.host_url
    redirect_url = urljoin(host_url, target)
    host_parts = urlparse(host_url)
    redirect_parts = urlparse(redirect_url)
    return host_parts.scheme == redirect_parts.scheme and host_parts.netloc == redirect_parts.netloc


@coach_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        mobile_input = (request.form.get("mobile_number") or "").strip()
        normalized_mobile = _normalize_mobile_number(mobile_input)
        password = request.form.get("password", "")
        next_url = request.args.get("next")
        if not _is_safe_redirect_target(next_url):
            next_url = None

        coach = None
        if normalized_mobile:
            normalized_column = _normalized_mobile_expression(Coach.mobile_number)
            coach = (
                Coach.query.filter(normalized_column == normalized_mobile)
                .order_by(Coach.id.asc())
                .first()
            )
        if coach is None and mobile_input:
            coach = (
                Coach.query.filter(Coach.mobile_number == mobile_input)
                .order_by(Coach.id.asc())
                .first()
            )

        if coach and coach.check_password(password):
            login_user(coach)
            flash("Welcome back!", "success")
            return redirect(next_url or url_for("coach.dashboard"))

        student = None
        if normalized_mobile and coach is None:
            normalized_student_column = _normalized_mobile_expression(Student.mobile_number)
            student = (
                Student.query.filter(normalized_student_column == normalized_mobile)
                .order_by(Student.id.asc())
                .first()
            )
        if student is None and coach is None and mobile_input:
            student = (
                Student.query.filter(Student.mobile_number == mobile_input)
                .order_by(Student.id.asc())
                .first()
            )

        if student and student.check_password(password):
            login_user(student)
            flash("Welcome back!", "success")
            return redirect(next_url or url_for("student.dashboard"))

        flash("Invalid mobile number or password", "danger")
    return render_template(
        "coach/login.html",
        state_choices=STATE_CHOICES,
        language_choices=LANGUAGE_CHOICES,
    )


@coach_bp.route("/register", methods=["POST"])
def register_student():
    name = (request.form.get("student_name") or "").strip()
    mobile_input = (request.form.get("student_mobile_number") or "").strip()
    mobile_number = _normalize_mobile_number(mobile_input)
    email = (request.form.get("student_email") or "").strip() or None
    password = request.form.get("student_password", "")
    confirm_password = request.form.get("student_confirm_password", "")
    state_choice = (request.form.get("student_state") or "").strip().upper()
    preferred_language = (
        (request.form.get("student_preferred_language") or "ENGLISH").strip().upper()
    )

    if not name or not mobile_number or not password:
        flash("Name, mobile number, and password are required to register.", "danger")
        return redirect(url_for("coach.login"))

    if password != confirm_password:
        flash("Passwords do not match.", "danger")
        return redirect(url_for("coach.login"))

    if state_choice not in STATE_CHOICES:
        flash("Please select a valid state or territory.", "danger")
        return redirect(url_for("coach.login"))

    if preferred_language not in LANGUAGE_CHOICES:
        flash("Please choose a supported language.", "danger")
        return redirect(url_for("coach.login"))

    normalized_coach_column = _normalized_mobile_expression(Coach.mobile_number)
    if (
        Coach.query.filter(normalized_coach_column == mobile_number)
        .order_by(Coach.id.asc())
        .first()
    ):
        flash("This mobile number is already registered to a coach or administrator.", "danger")
        return redirect(url_for("coach.login"))

    normalized_student_column = _normalized_mobile_expression(Student.mobile_number)
    if (
        Student.query.filter(normalized_student_column == mobile_number)
        .order_by(Student.id.asc())
        .first()
    ):
        flash("This mobile number is already registered to a student.", "danger")
        return redirect(url_for("coach.login"))

    if email and Student.query.filter(Student.email == email).first():
        flash("This email is already registered to a student.", "danger")
        return redirect(url_for("coach.login"))

    student = Student(
        name=name,
        mobile_number=mobile_number,
        email=email,
        state=state_choice,
        preferred_language=preferred_language,
    )
    student.set_password(password)
    db.session.add(student)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Unable to register with the provided details. Please try again.", "danger")
        return redirect(url_for("coach.login"))

    login_user(student)
    flash("Student account created successfully!", "success")
    return redirect(url_for("student.dashboard"))


@coach_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("coach.login"))


@coach_bp.route("/dashboard")
@login_required
def dashboard():
    slot_query = AvailabilitySlot.query.filter(
        AvailabilitySlot.start_time >= datetime.utcnow()
    ).order_by(AvailabilitySlot.start_time.asc())
    if current_user.is_admin:
        upcoming_slots = slot_query.limit(5).all()
        student_count = Student.query.count()
        pending_bookings = (
            Appointment.query.filter(Appointment.status == "booked").count()
        )
    else:
        upcoming_slots = (
            slot_query.filter(AvailabilitySlot.coach_id == current_user.id)
            .limit(5)
            .all()
        )
        student_count = Student.query.filter_by(
            assigned_coach_id=current_user.id
        ).count()
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
        submitted_mobile_raw = (request.form.get("mobile_number") or "").strip()
        normalized_mobile = _normalize_mobile_number(submitted_mobile_raw)
        if not normalized_mobile:
            flash("Mobile number is required.", "warning")
            return render_template("coach/profile.html", state_choices=STATE_CHOICES)

        normalized_column = _normalized_mobile_expression(Coach.mobile_number)
        duplicate_mobile = (
            Coach.query.filter(normalized_column == normalized_mobile)
            .filter(Coach.id != current_user.id)
            .first()
        )
        if duplicate_mobile:
            flash("Another account already uses that mobile number.", "danger")
            return render_template("coach/profile.html", state_choices=STATE_CHOICES)

        current_user.mobile_number = normalized_mobile
        current_user.city = request.form.get("city", current_user.city)
        state_choice = (request.form.get("state") or "").strip().upper()
        if state_choice not in STATE_CHOICES:
            flash("Please choose a valid state or territory.", "warning")
            return render_template("coach/profile.html", state_choices=STATE_CHOICES)
        current_user.state = state_choice
        vehicle_inputs = request.form.getlist("vehicle_types")
        types = _parse_vehicle_types(vehicle_inputs)
        if not types:
            flash("Please select at least one vehicle type (AT/MT).", "warning")
            return render_template("coach/profile.html", state_choices=STATE_CHOICES)
        current_user.vehicle_types = types
        current_user.bio = request.form.get("bio", current_user.bio)
        db.session.commit()
        flash("Profile updated successfully", "success")
        return redirect(url_for("coach.profile"))
    return render_template("coach/profile.html", state_choices=STATE_CHOICES)


@coach_bp.route("/students")
@login_required
def students():
    if current_user.is_admin:
        students = Student.query.order_by(Student.name.asc()).all()
    else:
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
    coach_lookup = {}
    if current_user.is_admin:
        coach_lookup = {coach.id: coach for coach in Coach.query.order_by(Coach.name).all()}
    return render_template(
        "coach/students.html",
        students=students,
        summaries=summaries,
        coach_lookup=coach_lookup,
    )


@coach_bp.route("/slots", methods=["GET", "POST"])
@login_required
def slots():
    if request.method == "POST":
        if current_user.is_admin:
            try:
                selected_coach_id = int(request.form.get("coach_id", ""))
            except (TypeError, ValueError):
                flash("Please choose a coach for the new slot.", "warning")
                return redirect(url_for("coach.slots"))
            if not db.session.get(Coach, selected_coach_id):
                flash("Selected coach could not be found.", "danger")
                return redirect(url_for("coach.slots"))
        else:
            selected_coach_id = current_user.id
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
            coach_id=selected_coach_id,
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

    slot_query = AvailabilitySlot.query.order_by(AvailabilitySlot.start_time.asc())
    if not current_user.is_admin:
        slot_query = slot_query.filter_by(coach_id=current_user.id)
    slots = slot_query.all()
    coach_choices = []
    if current_user.is_admin:
        coach_choices = Coach.query.order_by(Coach.name.asc()).all()
    return render_template("coach/slots.html", slots=slots, coach_choices=coach_choices)


@coach_bp.route("/slots/<int:slot_id>/delete", methods=["POST"])
@login_required
def delete_slot(slot_id: int):
    slot_query = AvailabilitySlot.query.filter_by(id=slot_id)
    if not current_user.is_admin:
        slot_query = slot_query.filter_by(coach_id=current_user.id)
    slot = slot_query.first_or_404()
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
    appointment_query = Appointment.query.join(AvailabilitySlot).order_by(
        AvailabilitySlot.start_time.desc()
    )
    if not current_user.is_admin:
        appointment_query = appointment_query.filter(
            AvailabilitySlot.coach_id == current_user.id
        )
    appointments = appointment_query.all()
    coach_lookup = {}
    if current_user.is_admin:
        coach_lookup = {coach.id: coach for coach in Coach.query.order_by(Coach.name).all()}
    return render_template(
        "coach/appointments.html",
        appointments=appointments,
        coach_lookup=coach_lookup,
    )


@coach_bp.route("/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_appointment_status(appointment_id: int):
    appointment_query = Appointment.query.join(AvailabilitySlot)
    if not current_user.is_admin:
        appointment_query = appointment_query.filter(
            AvailabilitySlot.coach_id == current_user.id
        )
    appointment = (
        appointment_query.filter(Appointment.id == appointment_id).first_or_404()
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


@coach_bp.route("/personnel", methods=["GET", "POST"])
@login_required
def personnel():
    redirect_response = _require_admin_access()
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        form_type = request.form.get("form_type")
        if form_type == "create":
            _handle_account_creation()
        elif form_type == "update_password":
            _handle_password_update()
        else:
            flash("Unknown action requested.", "danger")
        return redirect(url_for("coach.personnel"))

    coaches = Coach.query.order_by(Coach.name.asc()).all()
    students = Student.query.order_by(Student.name.asc()).all()
    return render_template(
        "coach/personnel.html",
        coaches=coaches,
        students=students,
        coach_choices=coaches,
        state_choices=STATE_CHOICES,
    )


def _handle_account_creation() -> None:
    role = (request.form.get("role") or "").strip().lower()
    if role not in {"coach", "student", "admin"}:
        flash("Please choose a valid account type.", "warning")
        return

    if role in {"coach", "admin"}:
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        mobile_input = (request.form.get("mobile_number") or "").strip()
        mobile_number = _normalize_mobile_number(mobile_input)
        city = (request.form.get("city") or "").strip()
        state = (request.form.get("state") or "").strip().upper()
        if state not in STATE_CHOICES:
            flash("Please choose a valid state or territory.", "warning")
            return
        vehicle_types = _parse_vehicle_types(request.form.getlist("vehicle_types"))

        if not all(
            [name, email, password, mobile_number, city, state, vehicle_types]
        ):
            flash(
                "All coach/admin fields are required, including a mobile number.",
                "warning",
            )
            return

        normalized_column = _normalized_mobile_expression(Coach.mobile_number)
        duplicate_mobile = (
            Coach.query.filter(normalized_column == mobile_number)
            .first()
        )
        if duplicate_mobile:
            flash("A coach or administrator already uses that mobile number.", "danger")
            return

        coach = Coach(
            name=name,
            email=email,
            mobile_number=mobile_number,
            city=city,
            state=state,
            vehicle_types=vehicle_types,
        )
        coach.set_password(password)
        db.session.add(coach)

        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            flash(
                "Unable to create account: duplicate email or mobile number.",
                "danger",
            )
            return

        if role == "admin":
            db.session.add(Admin(id=coach.id))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Unable to create account due to duplicate information.", "danger")
            return

        flash("Account created successfully.", "success")
        return

    # Student creation
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    mobile_input = (request.form.get("mobile_number") or "").strip()
    mobile_number = _normalize_mobile_number(mobile_input)
    state = (request.form.get("state") or "").strip().upper()
    if state not in STATE_CHOICES:
        flash("Please choose a valid state or territory.", "warning")
        return
    assigned_coach_raw = request.form.get("assigned_coach_id")
    assigned_coach = None
    if assigned_coach_raw:
        try:
            assigned_coach = db.session.get(Coach, int(assigned_coach_raw))
        except (TypeError, ValueError):
            assigned_coach = None

    if not all([name, email, password, mobile_number, state]):
        flash("All student fields are required.", "warning")
        return

    normalized_student_column = _normalized_mobile_expression(Student.mobile_number)
    duplicate_student = (
        Student.query.filter(normalized_student_column == mobile_number)
        .first()
    )
    if duplicate_student:
        flash("Another student already uses that mobile number.", "danger")
        return

    student = Student(
        name=name,
        email=email,
        mobile_number=mobile_number,
        state=state,
        preferred_language="ENGLISH",
    )
    if assigned_coach:
        student.coach = assigned_coach
    student.set_password(password)
    db.session.add(student)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Unable to create student: duplicate email or mobile number.", "danger")
        return

    flash("Account created successfully.", "success")


def _handle_password_update() -> None:
    account_type = (request.form.get("account_type") or "").strip().lower()
    account_id = request.form.get("account_id")
    new_password = request.form.get("new_password") or ""

    if account_type not in {"coach", "student", "admin"}:
        flash("Unsupported account type for password update.", "danger")
        return

    try:
        identity = int(account_id)
    except (TypeError, ValueError):
        flash("Invalid account identifier.", "danger")
        return

    if len(new_password) < 6:
        flash("Please supply a password of at least 6 characters.", "warning")
        return

    if account_type == "student":
        entity = db.session.get(Student, identity)
        if not entity:
            flash("Student account not found.", "danger")
            return
        entity.set_password(new_password)
    else:
        coach = db.session.get(Coach, identity)
        if not coach:
            flash("Coach account not found.", "danger")
            return
        if account_type == "admin" and not coach.is_admin:
            flash("Selected account is not an administrator.", "danger")
            return
        coach.set_password(new_password)

    db.session.commit()
    flash("Password updated successfully.", "success")
