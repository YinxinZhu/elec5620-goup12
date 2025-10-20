from __future__ import annotations

from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy import Boolean, CheckConstraint, Date, Enum, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class AccountUserMixin(UserMixin):
    """Base mixin that encodes the account type within the session id."""

    def get_id(self) -> str:  # pragma: no cover - exercised via login manager
        role = "admin" if getattr(self, "is_admin", False) else "coach"
        return f"{role}:{self.id}"

    @property
    def is_admin(self) -> bool:
        return False


class Coach(AccountUserMixin, db.Model):
    __tablename__ = "coaches"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), unique=True, nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    vehicle_types = db.Column(db.String(20), nullable=False)  # comma separated AT/MT
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    slots = db.relationship("AvailabilitySlot", back_populates="coach", cascade="all, delete-orphan")
    admin_profile = db.relationship("Admin", back_populates="coach", uselist=False)
    students = db.relationship("Student", back_populates="coach")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def vehicle_type_list(self) -> list[str]:
        return [v.strip() for v in self.vehicle_types.split(",") if v.strip()]

    @property
    def is_admin(self) -> bool:
        return self.admin_profile is not None


class Admin(db.Model):
    __tablename__ = "admins"

    id = db.Column(db.Integer, db.ForeignKey("coaches.id"), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    coach = db.relationship("Coach", back_populates="admin_profile")

    @property
    def email(self) -> str:
        return self.coach.email

    def set_password(self, password: str) -> None:
        self.coach.set_password(password)

    def check_password(self, password: str) -> bool:
        return self.coach.check_password(password)


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True)
    mobile_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(10), nullable=False)
    preferred_language = db.Column(db.String(20), nullable=False, default="ENGLISH")
    target_exam_date = db.Column(Date)
    avatar_url = db.Column(db.String(500))
    notification_push_enabled = db.Column(Boolean, nullable=False, default=True)
    notification_email_enabled = db.Column(Boolean, nullable=False, default=True)
    profile_version = db.Column(db.Integer, nullable=False, default=1)
    profile_updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_login_at = db.Column(db.DateTime)
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
    auth_tokens = db.relationship(
        "StudentAuthToken", back_populates="student", cascade="all, delete-orphan"
    )
    starred_questions = db.relationship(
        "StarredQuestion", back_populates="student", cascade="all, delete-orphan"
    )
    login_windows = db.relationship(
        "StudentLoginRateLimit", back_populates="student", cascade="all, delete-orphan"
    )
    variant_groups = db.relationship(
        "VariantQuestionGroup", back_populates="student", cascade="all, delete-orphan"
    )
    variant_questions = db.relationship(
        "VariantQuestion", back_populates="student", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def issue_token(self, *, expires_at: datetime | None = None) -> "StudentAuthToken":
        from secrets import token_urlsafe

        expiry = expires_at or datetime.utcnow() + timedelta(days=7)
        token = StudentAuthToken(
            token=token_urlsafe(32), student=self, expires_at=expiry, revoked=False
        )
        db.session.add(token)
        return token


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
    topic = db.Column(db.String(120), nullable=False, default="general")
    option_a = db.Column(db.String(255), nullable=False, default="Option A")
    option_b = db.Column(db.String(255), nullable=False, default="Option B")
    option_c = db.Column(db.String(255), nullable=False, default="Option C")
    option_d = db.Column(db.String(255), nullable=False, default="Option D")
    correct_option = db.Column(db.String(1), nullable=False, default="A")
    explanation = db.Column(db.Text, nullable=False, default="")
    image_url = db.Column(db.String(500))

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
    chosen_option = db.Column(db.String(1), nullable=False)
    time_spent_seconds = db.Column(db.Integer, nullable=False, default=0)
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
    paper_id = db.Column(db.Integer, db.ForeignKey("mock_exam_papers.id"), nullable=False)
    status = db.Column(
        Enum("ongoing", "submitted", "abandoned", name="exam_session_status"),
        nullable=False,
        default="ongoing",
    )
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    finished_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    score = db.Column(db.Integer)
    total_questions = db.Column(db.Integer)

    student = db.relationship("Student", back_populates="exam_sessions")
    paper = db.relationship("MockExamPaper", back_populates="sessions")
    answers = db.relationship(
        "StudentExamAnswer", back_populates="session", cascade="all, delete-orphan"
    )


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


class StudentAuthToken(db.Model):
    __tablename__ = "student_auth_tokens"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)

    student = db.relationship("Student", back_populates="auth_tokens")


class StudentLoginRateLimit(db.Model):
    __tablename__ = "student_login_windows"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    mobile_number = db.Column(db.String(20), unique=True, nullable=False)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    window_started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="login_windows")


class StarredQuestion(db.Model):
    __tablename__ = "starred_questions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="starred_questions")
    question = db.relationship("Question")

    __table_args__ = (
        UniqueConstraint("student_id", "question_id", name="uq_starred_student_question"),
    )


class VariantQuestionGroup(db.Model):
    __tablename__ = "variant_question_groups"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    base_question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    knowledge_point_name = db.Column(db.String(255), nullable=False)
    knowledge_point_summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="variant_groups")
    base_question = db.relationship("Question")
    variants = db.relationship(
        "VariantQuestion", back_populates="group", cascade="all, delete-orphan"
    )


class VariantQuestion(db.Model):
    __tablename__ = "variant_questions"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(
        db.Integer, db.ForeignKey("variant_question_groups.id"), nullable=False
    )
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    group = db.relationship("VariantQuestionGroup", back_populates="variants")
    student = db.relationship("Student", back_populates="variant_questions")


class MockExamPaper(db.Model):
    __tablename__ = "mock_exam_papers"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    time_limit_minutes = db.Column(db.Integer, nullable=False)

    questions = db.relationship(
        "MockExamPaperQuestion", back_populates="paper", cascade="all, delete-orphan"
    )
    sessions = db.relationship(
        "StudentExamSession", back_populates="paper", cascade="all, delete-orphan"
    )


class MockExamPaperQuestion(db.Model):
    __tablename__ = "mock_exam_paper_questions"

    id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("mock_exam_papers.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False)

    paper = db.relationship("MockExamPaper", back_populates="questions")
    question = db.relationship("Question")

    __table_args__ = (
        UniqueConstraint("paper_id", "question_id", name="uq_paper_question"),
        UniqueConstraint("paper_id", "position", name="uq_paper_position"),
    )


class StudentExamAnswer(db.Model):
    __tablename__ = "student_exam_answers"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("student_exam_sessions.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("questions.id"), nullable=False)
    selected_option = db.Column(db.String(1), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    answered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    session = db.relationship("StudentExamSession", back_populates="answers")
    question = db.relationship("Question")

    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_session_question"),
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


__all__ = [
    "Coach",
    "Admin",
    "Student",
    "MockExamSummary",
    "ExamRule",
    "Question",
    "QuestionAttempt",
    "NotebookEntry",
    "StudentExamSession",
    "StudentStateProgress",
    "StudentAuthToken",
    "StudentLoginRateLimit",
    "StarredQuestion",
    "MockExamPaper",
    "MockExamPaperQuestion",
    "StudentExamAnswer",
    "AvailabilitySlot",
    "Appointment",
]
