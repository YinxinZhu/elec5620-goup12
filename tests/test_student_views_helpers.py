import pytest
from datetime import datetime, timedelta

try:
    mod = __import__("app.student.routes", fromlist=["*"])
except ModuleNotFoundError:
    try:
        mod = __import__("app.views.student", fromlist=["*"])
    except ModuleNotFoundError:
        mod = __import__("app.student", fromlist=["*"])

class _Query:
    def __init__(self, *, first_value=None, all_rows=None):
        self._first = first_value
        self._rows = all_rows or []
    def filter_by(self, **kwargs): return self
    def filter(self, *args, **kwargs): return self
    def order_by(self, *args, **kwargs): return self
    def with_entities(self, *args, **kwargs): return self
    def join(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def all(self): return self._rows
    def first(self): return self._first

class _Student:
    def __init__(self, sid=1, state="NSW"):
        self.id = sid
        self.state = state

class _Question:
    def __init__(self, qid=1, state_scope="ALL"):
        self.id = qid
        self.state_scope = state_scope

def test__normalise_variant_count():
    assert mod._normalise_variant_count(None) == mod.VARIANT_DEFAULT_COUNT
    assert mod._normalise_variant_count("3") == 3
    assert mod._normalise_variant_count("0") == mod.VARIANT_MIN_COUNT
    assert mod._normalise_variant_count("999") == mod.VARIANT_MAX_COUNT
    assert mod._normalise_variant_count("abc") == mod.VARIANT_DEFAULT_COUNT

def test__question_accessible():
    stu = _Student(state="NSW")
    assert mod._question_accessible(_Question(state_scope="ALL"), stu) is True
    assert mod._question_accessible(_Question(state_scope="NSW"), stu) is True
    assert mod._question_accessible(_Question(state_scope="VIC"), stu) is False
