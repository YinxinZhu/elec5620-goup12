# tests/test_mock_exam_sessions_service.py
import types
from datetime import datetime, timedelta
import pytest

# Target module under test
svc = __import__("app.services.mock_exam_sessions", fromlist=["*"])


# --------- Simple fake Query/DB infrastructure ----------
class _Query:
    """A lightweight stub mimicking SQLAlchemy Query behavior."""

    def __init__(self, first_value=None):
        self._first = first_value

    def filter_by(self, **kwargs):
        """Return self to allow chaining."""
        self._last_filter = kwargs
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        """Return the configured fake result."""
        return self._first


class _DBSessionStub:
    """A mock object that simulates db.session behavior."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        return None


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """Automatically patch the global db.session object in the tested module."""
    stub = _DBSessionStub()
    monkeypatch.setattr(svc.db, "session", stub, raising=False)
    return stub


# --------- Lightweight model stubs ----------
class _Question:
    def __init__(self, qid, state_scope="ALL", correct_option="A",
                 option_a="A1", option_b="B1", option_c="C1", option_d="D1"):
        self.id = qid
        self.state_scope = state_scope
        self.correct_option = correct_option
        self.option_a = option_a
        self.option_b = option_b
        self.option_c = option_c
        self.option_d = option_d


class _PaperQuestion:
    def __init__(self, position, question):
        self.position = position
        self.question = question
        self.question_id = question.id


class _MockExamPaper:
    def __init__(self, pid, time_limit_minutes, questions):
        self.id = pid
        self.time_limit_minutes = time_limit_minutes
        self.questions = questions


class _Student:
    def __init__(self, sid, state="NSW"):
        self.id = sid
        self.state = state


class _StudentExamAnswer:
    """Stub for StudentExamAnswer with minimal required fields."""
    query = _Query(first_value=None)

    def __init__(self, session_id, question_id, selected_option, is_correct):
        self.session_id = session_id
        self.question_id = question_id
        self.selected_option = selected_option
        self.is_correct = is_correct
        self.answered_at = datetime.utcnow()


class _StudentExamSession:
    """Stub for StudentExamSession with basic state and timing logic."""
    query = _Query(first_value=None)

    def __init__(self, student_id, state, paper_id, expires_at, total_questions):
        self.id = 999
        self.student_id = student_id
        self.state = state
        self.paper_id = paper_id
        self.expires_at = expires_at
        self.total_questions = total_questions
        self.status = "ongoing"
        self.started_at = datetime.utcnow()
        self.finished_at = None
        self.score = 0
        self.answers = []  # list of StudentExamAnswer
        self.paper = None  # attached MockExamPaper


class _ExamRule:
    query = _Query(first_value=None)

    def __init__(self, state, pass_mark):
        self.state = state
        self.pass_mark = pass_mark


class _MockExamSummary:
    """Stub summary record for exam submission."""
    def __init__(self, student_id, state, score):
        self.student_id = student_id
        self.state = state
        self.score = score


class _NotebookEntry:
    query = _Query(first_value=None)

    def __init__(self, student_id, question_id, state, wrong_count, last_wrong_at):
        self.student_id = student_id
        self.question_id = question_id
        self.state = state
        self.wrong_count = wrong_count
        self.last_wrong_at = last_wrong_at


@pytest.fixture(autouse=True)
def patch_models(monkeypatch):
    """Patch all model references used inside the service module."""
    monkeypatch.setattr(svc, "StudentExamSession", _StudentExamSession, raising=True)
    monkeypatch.setattr(svc, "StudentExamAnswer", _StudentExamAnswer, raising=True)
    monkeypatch.setattr(svc, "ExamRule", _ExamRule, raising=True)
    monkeypatch.setattr(svc, "MockExamSummary", _MockExamSummary, raising=True)
    monkeypatch.setattr(svc, "NotebookEntry", _NotebookEntry, raising=True)
    return True


# ------------------- Unit tests -------------------

def test__ensure_exam_rule_found(monkeypatch):
    """Should return a valid ExamRule if configured."""
    rule = _ExamRule(state="NSW", pass_mark=3)
    _ExamRule.query = _Query(first_value=rule)
    got = svc._ensure_exam_rule("NSW")
    assert got.pass_mark == 3


def test__ensure_exam_rule_missing_raises(monkeypatch):
    """Should raise ExamRuleMissingError if rule is missing."""
    _ExamRule.query = _Query(first_value=None)
    with pytest.raises(svc.ExamRuleMissingError):
        svc._ensure_exam_rule("NSW")


def test_session_questions_filters_and_orders():
    """Ensure only valid state questions are kept and sorted by position."""
    q1 = _Question(1, state_scope="NSW")
    q2 = _Question(2, state_scope="VIC")
    q3 = _Question(3, state_scope="ALL")
    pqs = [_PaperQuestion(2, q2), _PaperQuestion(1, q1), _PaperQuestion(3, q3)]
    paper = _MockExamPaper(7, 30, pqs)
    sess = _StudentExamSession(11, "NSW", 7, datetime.utcnow()+timedelta(minutes=30), 2)
    sess.paper = paper
    sess.answers = []
    out = svc.session_questions(sess)
    assert [x.question.id for x in out] == [1, 3]


def test_ensure_session_active_auto_finalises(monkeypatch):
    """Expired sessions should automatically call finalise_session()."""
    sess = _StudentExamSession(1, "NSW", 1, datetime.utcnow()-timedelta(seconds=1), 0)
    sess.paper = _MockExamPaper(1, 1, [])
    called = {"count": 0}

    def fake_finalise(s, auto=False):
        called["count"] += 1
        s.status = "abandoned"

    monkeypatch.setattr(svc, "finalise_session", fake_finalise)
    ret = svc.ensure_session_active(sess)
    assert called["count"] == 1
    assert ret.status == "abandoned"


def test_record_answer_create_and_update(monkeypatch, patch_db):
    """Should create a new answer if not exist, otherwise update it."""
    q = _Question(77, "ALL", correct_option="B")
    paper = _MockExamPaper(2, 20, [_PaperQuestion(1, q)])
    sess = _StudentExamSession(1, "NSW", 2, datetime.utcnow()+timedelta(minutes=20), 1)
    sess.paper = paper
    sess.answers = []
    # first submission: new answer
    _StudentExamAnswer.query = _Query(first_value=None)
    ans = svc.record_answer(sess, 77, "A")
    sess.answers.append(ans)
    assert not ans.is_correct
    # second submission: update existing answer
    _StudentExamAnswer.query = _Query(first_value=ans)
    ans2 = svc.record_answer(sess, 77, "B")
    assert ans2 is ans and ans2.is_correct


def test_finalise_session_scores_and_notebook(monkeypatch, patch_db):
    """Should calculate score and update notebook entries."""
    q1 = _Question(1, "ALL", correct_option="A")
    q2 = _Question(2, "ALL", correct_option="A")
    paper = _MockExamPaper(3, 30, [_PaperQuestion(1, q1), _PaperQuestion(2, q2)])
    sess = _StudentExamSession(7, "NSW", 3, datetime.utcnow()+timedelta(minutes=30), 2)
    sess.paper = paper
    a1 = _StudentExamAnswer(sess.id, 1, "A", True)
    a2 = _StudentExamAnswer(sess.id, 2, "B", False)
    sess.answers = [a1, a2]
    _NotebookEntry.query = _Query(first_value=None)
    svc.finalise_session(sess, auto=False)
    assert sess.status == "submitted"
    assert sess.score == 1 and sess.total_questions == 2
    # calling again should not reprocess
    svc.finalise_session(sess, auto=False)
    assert sess.score == 1


def test_finalise_session_auto_sets_abandoned(monkeypatch):
    """Should set status to 'abandoned' if auto=True."""
    q = _Question(1, "ALL", "A")
    paper = _MockExamPaper(8, 10, [_PaperQuestion(1, q)])
    sess = _StudentExamSession(9, "NSW", 8, datetime.utcnow()-timedelta(seconds=1), 1)
    sess.paper = paper
    svc.finalise_session(sess, auto=True)
    assert sess.status == "abandoned"


def test_submit_session_pass_logic(monkeypatch):
    """Should correctly determine pass/fail according to ExamRule."""
    _ExamRule.query = _Query(first_value=_ExamRule("NSW", 2))
    q1 = _Question(1, "ALL")
    paper = _MockExamPaper(6, 10, [_PaperQuestion(1, q1)])
    sess = _StudentExamSession(1, "NSW", 6, datetime.utcnow()+timedelta(minutes=10), 1)
    sess.paper = paper
    # case 1: passed
    sess.status = "submitted"
    sess.score = 2
    sess.total_questions = 2
    sub = svc.submit_session(sess)
    assert sub.passed and sub.pass_mark == 2 and sub.total == 2
    # case 2: abandoned never passes
    sess.status = "abandoned"
    sess.score = 3
    sub2 = svc.submit_session(sess)
    assert not sub2.passed
