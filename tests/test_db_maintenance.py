from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import TestConfig
from app.db_maintenance import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_MOBILE_NUMBER,
    ensure_admin_support,
    ensure_database_schema,
    ensure_question_language_support,
    ensure_student_mobile_column,
)
from app.models import Coach


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


@pytest.fixture()
def coach_engine():
    engine = create_engine("sqlite://")
    Coach.__table__.create(bind=engine)
    return engine


@pytest.fixture()
def legacy_questions_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE questions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "qid VARCHAR(50) NOT NULL,"
                "prompt TEXT NOT NULL,"
                "state_scope VARCHAR(10) NOT NULL,"
                "topic VARCHAR(120) NOT NULL DEFAULT 'general',"
                "option_a VARCHAR(255) NOT NULL,"
                "option_b VARCHAR(255) NOT NULL,"
                "option_c VARCHAR(255) NOT NULL,"
                "option_d VARCHAR(255) NOT NULL,"
                "correct_option VARCHAR(1) NOT NULL,"
                "explanation TEXT NOT NULL DEFAULT '',"
                "image_url VARCHAR(500)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_question_qid_state_scope "
                "ON questions (qid, state_scope)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO questions ("
                "qid, prompt, state_scope, topic, option_a, option_b, option_c, option_d, "
                "correct_option, explanation"
                ") VALUES ("
                ":qid, 'Prompt', :state, 'general', 'A', 'B', 'C', 'D', 'A', ''"
                ")"
            ),
            {"qid": "Q1", "state": "NSW"},
        )
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


def test_ensure_admin_support_creates_table_and_account(coach_engine):
    logger = logging.getLogger("test_ensure_admin_support_creates_table_and_account")

    ensure_admin_support(coach_engine, logger)

    inspector = inspect(coach_engine)
    tables = set(inspector.get_table_names())
    assert "admins" in tables

    with coach_engine.begin() as conn:
        admin_rows = conn.execute(text("SELECT id FROM admins"))
        rows = admin_rows.fetchall()
    assert len(rows) == 1

    admin_id = rows[0].id
    with coach_engine.begin() as conn:
        coach_row = conn.execute(
            text("SELECT email, phone, password_hash FROM coaches WHERE id = :id"),
            {"id": admin_id},
        ).one()

    normalized_mobile = "".join(ch for ch in DEFAULT_ADMIN_MOBILE_NUMBER if ch.isdigit())
    assert coach_row.email == DEFAULT_ADMIN_EMAIL
    assert coach_row.phone == normalized_mobile
    assert coach_row.password_hash and coach_row.password_hash != "password123"


def test_ensure_admin_support_is_idempotent(coach_engine):
    logger = logging.getLogger("test_ensure_admin_support_is_idempotent")

    ensure_admin_support(coach_engine, logger)
    ensure_admin_support(coach_engine, logger)

    with coach_engine.begin() as conn:
        admin_count = conn.execute(text("SELECT COUNT(*) FROM admins")).scalar_one()
        normalized_mobile = "".join(ch for ch in DEFAULT_ADMIN_MOBILE_NUMBER if ch.isdigit())
        coach_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM coaches WHERE email = :email AND phone = :mobile"
            ),
            {"email": DEFAULT_ADMIN_EMAIL, "mobile": normalized_mobile},
        ).scalar_one()

    assert admin_count == 1
    assert coach_count == 1


def test_ensure_question_language_support_upgrades_schema(legacy_questions_engine):
    logger = logging.getLogger("test_ensure_question_language_support_upgrades_schema")

    ensure_question_language_support(legacy_questions_engine, logger)

    inspector = inspect(legacy_questions_engine)
    columns = {column["name"] for column in inspector.get_columns("questions")}
    assert "language" in columns

    with legacy_questions_engine.begin() as conn:
        existing = conn.execute(
            text(
                "SELECT qid, state_scope, language FROM questions ORDER BY id"
            )
        ).all()

    assert existing == [("Q1", "NSW", "ENGLISH")]

    with legacy_questions_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO questions ("
                "qid, prompt, state_scope, topic, option_a, option_b, option_c, option_d, "
                "correct_option, explanation, language"
                ") VALUES ("
                ":qid, 'Prompt', :state, 'general', 'A', 'B', 'C', 'D', 'A', '', :lang"
                ")"
            ),
            {"qid": "Q1", "state": "NSW", "lang": "HINDI"},
        )

    with pytest.raises(IntegrityError):
        with legacy_questions_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO questions ("
                    "qid, prompt, state_scope, topic, option_a, option_b, option_c, option_d, "
                    "correct_option, explanation, language"
                    ") VALUES ("
                    ":qid, 'Prompt', :state, 'general', 'A', 'B', 'C', 'D', 'A', '', :lang"
                    ")"
                ),
                {"qid": "Q1", "state": "NSW", "lang": "ENGLISH"},
            )


def test_ensure_question_language_support_is_idempotent(legacy_questions_engine):
    logger = logging.getLogger("test_ensure_question_language_support_is_idempotent")

    ensure_question_language_support(legacy_questions_engine, logger)
    ensure_question_language_support(legacy_questions_engine, logger)

    inspector = inspect(legacy_questions_engine)
    columns = {column["name"] for column in inspector.get_columns("questions")}
    assert "language" in columns


def test_ensure_database_schema_populates_core_tables(tmp_path):
    class FileConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'maintenance.db'}"

    app = create_app(FileConfig)

    with app.app_context():
        engine = db.engine
        ensure_database_schema(engine, app.logger)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

    assert {"coaches", "students"}.issubset(tables)
