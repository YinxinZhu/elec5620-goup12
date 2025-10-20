from __future__ import annotations

from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint, Enum
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class Coach(UserMixin, db.Model):
    __tablename__ = "coaches"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    vehicle_types = db.Column(db.String(20), nullable=False)  # comma separated AT/MT
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    slots = db.relationship("AvailabilitySlot", back_populates="coach", cascade="all, delete-orphan")
    students = db.relationship("Student", back_populates="coach")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def vehicle_type_list(self) -> list[str]:
        return [v.strip() for v in self.vehicle_types.split(",") if v.strip()]


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    state = db.Column(db.String(10), nullable=False)
    assigned_coach_id = db.Column(db.Integer, db.ForeignKey("coaches.id"))

    coach = db.relationship("Coach", back_populates="students")
    mock_exam_summaries = db.relationship(
        "MockExamSummary", back_populates="student", cascade="all, delete-orphan"
    )
    bookings = db.relationship("Appointment", back_populates="student")
    exam_sessions = db.relationship(
        "StudentExamSession", back_populates="student", cascade="all, delete-orphan"
    )
    question_attempts = db.relationship(
        "QuestionAttempt", back_populates="student", cascade="all, delete-orphan"
    )
    notebook_entries = db.relationship(
        "NotebookEntry", back_populates="student", cascade="all, delete-orphan"
    )
    state_progress = db.relationship(
        "StudentStateProgress", back_populates="student", cascade="all, delete-orphan"
    )


class MockExamSummary(db.Model):
    __tablename__ = "mock_exam_summaries"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    state = db.Column(db.String(10))
    score = db.Column(db.Integer, nullable=False)
    taken_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="mock_exam_summaries")


class ExamRule(db.Model):
    __tablename__ = "exam_rules"

    state = db.Column(db.String(10), primary_key=True)
    total_questions = db.Column(db.Integer, nullable=False)
    pass_mark = db.Column(db.Integer, nullable=False)
    time_limit_minutes = db.Column(db.Integer, nullable=False)


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    qid = db.Column(db.String(50), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    state_scope = db.Column(db.String(10), nullable=False, default="ALL")

    __table_args__ = (
        UniqueConstraint("qid", "state_scope", name="uq_question_qid_state"),
    )


class QuestionAttempt(db.Model):
    __tablename__ = "question_attempts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="question_attempts")
    question = db.relationship("Question")


class NotebookEntry(db.Model):
    __tablename__ = "notebook_entries"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    wrong_count = db.Column(db.Integer, nullable=False, default=0)
    last_wrong_at = db.Column(db.DateTime)

    student = db.relationship("Student", back_populates="notebook_entries")
    question = db.relationship("Question")

    __table_args__ = (
        UniqueConstraint("student_id", "question_id", "state", name="uq_notebook_scope"),
    )


class StudentExamSession(db.Model):
    __tablename__ = "student_exam_sessions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    status = db.Column(
        Enum("ongoing", "submitted", "abandoned", name="exam_session_status"),
        nullable=False,
        default="ongoing",
    )
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)

    student = db.relationship("Student", back_populates="exam_sessions")


class StudentStateProgress(db.Model):
    __tablename__ = "student_state_progress"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    first_visited_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="state_progress")

    __table_args__ = (
        UniqueConstraint("student_id", "state", name="uq_progress_student_state"),
    )


class AvailabilitySlot(db.Model):
    __tablename__ = "availability_slots"

    id = db.Column(db.Integer, primary_key=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("coaches.id"), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    location_text = db.Column(db.String(255), nullable=False)
    status = db.Column(
        Enum("available", "booked", "unavailable", name="slot_status"),
        default="available",
        nullable=False,
    )

    coach = db.relationship("Coach", back_populates="slots")
    appointment = db.relationship(
        "Appointment",
        back_populates="slot",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("duration_minutes IN (30, 60)", name="duration_limit"),
        UniqueConstraint("coach_id", "start_time", name="uq_coach_slot_start"),
    )

    @property
    def end_time(self) -> datetime:
        return self.start_time + timedelta(minutes=self.duration_minutes)


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("availability_slots.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    status = db.Column(
        Enum("booked", "cancelled", "completed", name="booking_status"),
        default="booked",
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    slot = db.relationship("AvailabilitySlot", back_populates="appointment")
    student = db.relationship("Student", back_populates="bookings")


class ExamRule(db.Model):
    __tablename__ = "exam_rules"

    state = db.Column(db.String(10), primary_key=True)
    total_questions = db.Column(db.Integer, nullable=False)
    pass_mark = db.Column(db.Integer, nullable=False)
    time_limit_minutes = db.Column(db.Integer, nullable=False)


class Question(db.Model):
    __tablename__ = "questions"

    id = db.Column(db.Integer, primary_key=True)
    qid = db.Column(db.String(50), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    state_scope = db.Column(db.String(10), nullable=False, default="ALL")

    __table_args__ = (
        UniqueConstraint("qid", "state_scope", name="uq_question_qid_scope"),
    )


class StudentStateProgress(db.Model):
    __tablename__ = "student_state_progress"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    total_attempts = db.Column(db.Integer, nullable=False, default=0)
    best_score = db.Column(db.Integer)
    last_active_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="state_progress")

    __table_args__ = (
        UniqueConstraint("student_id", "state", name="uq_progress_student_state"),
    )


class StudentExamSession(db.Model):
    __tablename__ = "student_exam_sessions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    status = db.Column(
        Enum("ongoing", "submitted", "abandoned", name="exam_session_status"),
        nullable=False,
        default="ongoing",
    )
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)

    student = db.relationship("Student", back_populates="exam_sessions")


__all__ = [
    "Coach",
    "Student",
    "MockExamSummary",
    "ExamRule",
    "Question",
    "QuestionAttempt",
    "NotebookEntry",
    "StudentExamSession",
    "StudentStateProgress",
    "AvailabilitySlot",
    "Appointment",
    "ExamRule",
    "Question",
    "StudentStateProgress",
    "StudentExamSession",
]
