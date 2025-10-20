"""Database maintenance helpers to keep legacy deployments compatible."""

from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

LEGACY_MOBILE_PREFIX = "040000"
MOBILE_PADDING = 4


def _generate_placeholder_mobile(student_id: int) -> str:
    """Generate a stable placeholder mobile number for legacy records."""
    return f"{LEGACY_MOBILE_PREFIX}{student_id:0{MOBILE_PADDING}d}"


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


def ensure_database_schema(engine: Engine, logger: logging.Logger | None = None) -> None:
    """Run all lightweight schema checks for legacy compatibility."""

    ensure_student_mobile_column(engine, logger)
