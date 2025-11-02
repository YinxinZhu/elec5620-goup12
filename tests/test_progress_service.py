# tests/test_progress_service.py
from datetime import datetime, timedelta, date
from io import StringIO
import csv
import pytest

# module under test
svc = __import__("app.services.progress", fromlist=["*"])


# ----------------------- Lightweight stubs -----------------------
class _Query:
    """
    A flexible fake query object that supports a subset of SQLAlchemy-like APIs used
    in the service: filter_by, filter, join, with_entities, order_by, group_by,
    first, all, and scalar.
    """
    def __init__(self, *, first_value=None, all_rows=None, scalar_value=None):
        self._first_value = first_value
        self._all_rows = all_rows
        self._scalar_value = scalar_value

    # chainable no-op transforms
    def filter_by(self, **kwargs): return self
    def filter(self, *args, **kwargs): return self
    def join(self, *args, **kwargs): return self
    def with_entities(self, *args, **kwargs): return self
    def order_by(self, *args, **kwargs): return self
    def group_by(self, *args, **kwargs): return self

    # terminal ops
    def first(self): return self._first_value
    def all(self): return self._all_rows or []
    def scalar(self): return self._scalar_value


class _Student:
    def __init__(self, sid, state="NSW", preferred_language="ENGLISH"):
        self.id = sid
        self.state = state
        self.preferred_language = preferred_language


class _Question:
    def __init__(self, qid, topic=None):
        self.qid = qid
        self.topic = topic


class _QuestionAttempt:
    query = _Query()

    def __init__(self, student_id, state, question, attempted_at, is_correct, id_=1):
        self.student_id = student_id
        self.state = state
        self.question = question
        self.attempted_at = attempted_at
        self.is_correct = is_correct
        self.id = id_


class _NotebookEntry:
    query = _Query()

    def __init__(self, student_id, question_id, state, wrong_count, last_wrong_at):
        self.student_id = student_id
        self.question_id = question_id
        self.state = state
        self.wrong_count = wrong_count
        self.last_wrong_at = last_wrong_at


class _MockExamSummary:
    query = _Query()

    def __init__(self, student_id, state, score, taken_at):
        self.student_id = student_id
        self.state = state
        self.score = score
        self.taken_at = taken_at


class _ExamRule:
    query = _Query()

    def __init__(self, state, pass_mark):
        self.state = state
        self.pass_mark = pass_mark


# ----------------------- Pytest global patches -----------------------
@pytest.fixture(autouse=True)
def patch_models(monkeypatch):
    # Patch models referenced in the service
    monkeypatch.setattr(svc, "Student", _Student, raising=True)
    monkeypatch.setattr(svc, "Question", _Question, raising=True)
    monkeypatch.setattr(svc, "QuestionAttempt", _QuestionAttempt, raising=True)
    monkeypatch.setattr(svc, "NotebookEntry", _NotebookEntry, raising=True)
    monkeypatch.setattr(svc, "MockExamSummary", _MockExamSummary, raising=True)
    monkeypatch.setattr(svc, "ExamRule", _ExamRule, raising=True)


@pytest.fixture(autouse=True)
def patch_get_questions(monkeypatch):
    """
    Patch state_management.get_questions_for_state so we fully control the bank
    of available questions (with qid/topic).
    """
    def _fake_get_questions_for_state(state, language):
        # Default: three questions across two topics
        return [
            _Question("Q1", topic="signals"),
            _Question("Q2", topic="rules"),
            _Question("Q3", topic="signals"),
        ]
    monkeypatch.setattr("app.services.progress.get_questions_for_state",
                        _fake_get_questions_for_state, raising=True)


# ----------------------- Tests (kept) -----------------------

def test_access_control_denies_other_student():
    # has ExamRule so resolve_state passes
    _ExamRule.query = _Query(first_value=_ExamRule("NSW", pass_mark=1))
    stu = _Student(1, "NSW")
    other = _Student(2, "NSW")
    with pytest.raises(svc.ProgressAccessError):
        svc.get_progress_summary(stu, acting_student=other)


def test_state_validation_missing_rule_raises():
    _ExamRule.query = _Query(first_value=None)
    stu = _Student(1, "NSW")
    with pytest.raises(svc.ProgressValidationError):
        svc.get_progress_summary(stu)


def test_blank_state_on_student_raises_via_normalise():
    # When student.state is blank and no explicit state is given
    _ExamRule.query = _Query(first_value=None)  # won't even reach this if normalise fails
    stu = _Student(1, state="")
    with pytest.raises(svc.ProgressValidationError):
        svc.get_progress_summary(stu, state=None)


def test_no_questions_returns_empty_trend(monkeypatch):
    _ExamRule.query = _Query(first_value=_ExamRule("NSW", 1))

    # No questions available for the scope
    def _qbank(state, language): return []
    monkeypatch.setattr("app.services.progress.get_questions_for_state", _qbank, raising=True)

    stu = _Student(1, "NSW")
    trend = svc.get_progress_trend(stu)
    assert trend == []
