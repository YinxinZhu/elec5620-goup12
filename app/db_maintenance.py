"""Database maintenance helpers to keep legacy deployments compatible."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from . import db
LEGACY_MOBILE_PREFIX = "040000"
LEGACY_COACH_PREFIX = "049000"
MOBILE_PADDING = 4

DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_PASSWORD = "password123"
DEFAULT_ADMIN_NAME = "Platform Administrator"
DEFAULT_ADMIN_MOBILE_NUMBER = "0400 999 000"
DEFAULT_ADMIN_CITY = "Sydney"
DEFAULT_ADMIN_STATE = "NSW"
DEFAULT_ADMIN_VEHICLE_TYPES = "AT,MT"
DEFAULT_ADMIN_BIO = "Auto-generated administrator account with full access."


def _digits_only(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _generate_placeholder_mobile(student_id: int) -> str:
    """Generate a stable placeholder mobile number for legacy records."""
    return f"{LEGACY_MOBILE_PREFIX}{student_id:0{MOBILE_PADDING}d}"


def _generate_placeholder_coach_mobile(coach_id: int) -> str:
    return f"{LEGACY_COACH_PREFIX}{coach_id:0{MOBILE_PADDING}d}"


def ensure_student_mobile_column(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Ensure the ``students.mobile_number`` column exists in legacy databases.

    Older SQLite databases were created before the ``mobile_number`` column was
    added to the ``students`` table. The ORM expects this column to exist, so we
    patch legacy databases in-place by adding the column, backfilling placeholder
    values, and creating the unique index that modern schemas rely on.
    """

    inspector = inspect(engine)
    tables: Iterable[str] = inspector.get_table_names()
    if "students" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("students")}
    if "mobile_number" in columns:
        return

    logger = logger or logging.getLogger(__name__)
    logger.warning(
        "Missing students.mobile_number column detected; applying legacy schema patch.")

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE students ADD COLUMN mobile_number VARCHAR(20)")
            )

            # Capture the student ids before updating to avoid interfering with the cursor.
            student_rows = list(
                connection.execute(text("SELECT id FROM students ORDER BY id"))
            )
            for row in student_rows:
                placeholder = _generate_placeholder_mobile(row.id)
                connection.execute(
                    text(
                        "UPDATE students SET mobile_number = :mobile WHERE id = :id"
                    ),
                    {"mobile": placeholder, "id": row.id},
                )

            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_students_mobile_number ON students(mobile_number)"
                )
            )
    except SQLAlchemyError:
        logger.exception(
            "Failed to patch legacy students table with mobile_number column"
        )
        raise


def ensure_coach_mobile_uniqueness(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Normalize coach mobile numbers and enforce uniqueness for legacy data."""

    inspector = inspect(engine)
    tables: Iterable[str] = inspector.get_table_names()
    if "coaches" not in tables:
        return

    logger = logger or logging.getLogger(__name__)

    from .models import Coach

    try:
        with Session(bind=engine) as session:
            seen: set[str] = set()
            coaches = session.query(Coach).all()
            for coach in coaches:
                normalized = _normalize_mobile(getattr(coach, "phone", ""))
                if not normalized or normalized in seen:
                    normalized = _generate_placeholder_coach_mobile(coach.id)
                coach.phone = normalized
                seen.add(normalized)
            session.commit()

        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_coaches_phone ON coaches(phone)"
                )
            )
    except SQLAlchemyError:
        logger.exception("Failed to enforce unique coach mobile numbers during maintenance")
        raise


def ensure_admin_support(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Guarantee the admin metadata and seed account exist for legacy databases."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "coaches" not in tables:
        return

    logger = logger or logging.getLogger(__name__)

    from .models import Admin, Coach

    if "admins" not in tables:
        logger.warning("Missing admins table detected; creating administrator schema support.")
        try:
            Admin.__table__.create(bind=engine, checkfirst=True)
        except SQLAlchemyError:
            logger.exception("Failed to create admins table during maintenance")
            raise
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

    if "admins" not in tables:
        return

    try:
        with Session(bind=engine) as session:
            has_admin = session.query(Admin).first() is not None
            if has_admin:
                session.commit()
                return

            coach = session.query(Coach).filter(
                Coach.email == DEFAULT_ADMIN_EMAIL
            ).first()

            if not coach:
                coach = Coach(
                    email=DEFAULT_ADMIN_EMAIL,
                    name=DEFAULT_ADMIN_NAME,
                    mobile_number=_digits_only(DEFAULT_ADMIN_MOBILE_NUMBER),
                    city=DEFAULT_ADMIN_CITY,
                    state=DEFAULT_ADMIN_STATE,
                    vehicle_types=DEFAULT_ADMIN_VEHICLE_TYPES,
                    bio=DEFAULT_ADMIN_BIO,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                coach.set_password(DEFAULT_ADMIN_PASSWORD)
                session.add(coach)
                session.flush()
            elif coach.admin_profile is not None:
                session.commit()
                return
            else:
                coach.mobile_number = _digits_only(DEFAULT_ADMIN_MOBILE_NUMBER)

            session.add(Admin(id=coach.id, created_at=datetime.utcnow()))
            session.commit()
            logger.info(
                "Administrator account ensured: %s (mobile %s)",
                DEFAULT_ADMIN_EMAIL,
                DEFAULT_ADMIN_MOBILE_NUMBER,
            )
    except SQLAlchemyError:
        logger.exception("Failed to ensure administrator account during maintenance")
        raise


def ensure_coach_mobile_uniqueness(
    engine: Engine, logger: logging.Logger | None = None
) -> None:
    """Ensure coach mobile numbers remain unique for legacy databases."""

    inspector = inspect(engine)
    if "coaches" not in inspector.get_table_names():
        return

    indexes = inspector.get_indexes("coaches")
    has_unique_mobile = any(
        index.get("unique") and index.get("column_names") == ["phone"]
        for index in indexes
    )
    if has_unique_mobile:
        return

    logger = logger or logging.getLogger(__name__)
    logger.warning(
        "Missing unique index on coaches.mobile_number detected; applying legacy schema patch."
    )

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_coaches_mobile_number ON coaches(phone)"
                )
            )
    except SQLAlchemyError:
        logger.exception(
            "Failed to enforce unique coach mobile numbers during maintenance"
        )
        raise


def normalize_account_mobile_numbers(
    engine: Engine, logger: logging.Logger | None = None
) -> None:
    """Normalise stored mobile numbers to digits-only strings."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "coaches" not in tables and "students" not in tables:
        return

    logger = logger or logging.getLogger(__name__)

    from .models import Coach, Student

    try:
        with Session(bind=engine) as session:
            changed = False

            if "coaches" in tables:
                for coach in session.query(Coach).yield_per(50):
                    normalized = _digits_only(coach.mobile_number)
                    if normalized and coach.mobile_number != normalized:
                        coach.mobile_number = normalized
                        changed = True

            if "students" in tables:
                for student in session.query(Student).yield_per(50):
                    normalized = _digits_only(student.mobile_number)
                    if normalized and student.mobile_number != normalized:
                        student.mobile_number = normalized
                        changed = True

            if changed:
                session.commit()
            else:
                session.rollback()
    except SQLAlchemyError:
        logger.exception("Failed to normalise mobile numbers during maintenance")
        raise


def ensure_variant_support(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Create variant question tables for upgraded deployments."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {"variant_question_groups", "variant_questions"}
    if required.issubset(tables):
        return

    logger = logger or logging.getLogger(__name__)

    from .models import VariantQuestion, VariantQuestionGroup

    try:
        VariantQuestionGroup.__table__.create(bind=engine, checkfirst=True)
        VariantQuestion.__table__.create(bind=engine, checkfirst=True)
    except SQLAlchemyError:
        logger.exception("Failed to create variant question tables during maintenance")
        raise


def ensure_core_tables(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Ensure the base SQLAlchemy models are materialised for new databases."""

    logger = logger or logging.getLogger(__name__)
    try:
        db.create_all()
    except SQLAlchemyError:
        logger.exception("Failed to create core tables during maintenance")
        raise


def ensure_database_schema(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Run all lightweight schema checks for legacy compatibility."""

    ensure_core_tables(engine, logger)
    ensure_student_mobile_column(engine, logger)
    ensure_coach_mobile_uniqueness(engine, logger)
    ensure_admin_support(engine, logger)
    normalize_account_mobile_numbers(engine, logger)
    ensure_variant_support(engine, logger)
