from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db_maintenance import ensure_student_mobile_column


@pytest.fixture()
def legacy_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE students ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "name VARCHAR(120) NOT NULL"
                ")"
            )
        )
        conn.execute(text("INSERT INTO students (name) VALUES ('Jamie')"))
        conn.execute(text("INSERT INTO students (name) VALUES ('Priya')"))
    return engine


def test_ensure_student_mobile_column_adds_missing_column(legacy_engine):
    logger = logging.getLogger("test_ensure_student_mobile_column_adds_missing_column")

    ensure_student_mobile_column(legacy_engine, logger)

    inspector = inspect(legacy_engine)
    column_names = {column["name"] for column in inspector.get_columns("students")}
    assert "mobile_number" in column_names

    with legacy_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, mobile_number FROM students ORDER BY id")
        ).all()

    assert rows[0].mobile_number == "0400000001"
    assert rows[1].mobile_number == "0400000002"

    with pytest.raises(IntegrityError):
        with legacy_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE students SET mobile_number = :mobile WHERE id = :id"
                ),
                {"mobile": rows[0].mobile_number, "id": rows[1].id},
            )


def test_ensure_student_mobile_column_is_idempotent(legacy_engine):
    logger = logging.getLogger("test_ensure_student_mobile_column_is_idempotent")

    ensure_student_mobile_column(legacy_engine, logger)
    ensure_student_mobile_column(legacy_engine, logger)

    inspector = inspect(legacy_engine)
    column_names = {column["name"] for column in inspector.get_columns("students")}
    assert "mobile_number" in column_names

    with legacy_engine.begin() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM students")).scalar_one()

    assert row_count == 2
