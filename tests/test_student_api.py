from __future__ import annotations

import pytest

from app import create_app, db
from app.config import TestConfig
from app.models import (
    ExamRule,
    MockExamPaper,
    MockExamPaperQuestion,
    MockExamSummary,
    NotebookEntry,
    Question,
    StarredQuestion,
    Student,
    StudentExamSession,
    StudentStateProgress,
    VariantQuestionGroup,
)


@pytest.fixture
def seeded_app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()

        db.session.add_all(
            [
                ExamRule(state="NSW", total_questions=45, pass_mark=38, time_limit_minutes=45),
                ExamRule(state="VIC", total_questions=42, pass_mark=36, time_limit_minutes=40),
            ]
        )

        questions = [
            Question(
                qid="CORE-1",
                prompt="Shared question",
                state_scope="ALL",
                topic="core",
                option_a="A",
                option_b="B",
                option_c="C",
                option_d="D",
                correct_option="B",
                explanation="Two second rule",
                language="ENGLISH",
            ),
            Question(
                qid="NSW-1",
                prompt="NSW question",
                state_scope="NSW",
                topic="state",
                option_a="A",
                option_b="B",
                option_c="C",
                option_d="D",
                correct_option="C",
                explanation="State rule",
                language="ENGLISH",
            ),
            Question(
                qid="NSW-2",
                prompt="NSW extra",
                state_scope="NSW",
                topic="state",
                option_a="A",
                option_b="B",
                option_c="C",
                option_d="D",
                correct_option="A",
                explanation="Extra",
                language="ENGLISH",
            ),
            Question(
                qid="VIC-1",
                prompt="VIC question",
                state_scope="VIC",
                topic="state",
                option_a="A",
                option_b="B",
                option_c="C",
                option_d="D",
                correct_option="A",
                explanation="VIC",
                language="ENGLISH",
            ),
        ]
        db.session.add_all(questions)
        db.session.flush()

        paper_a = MockExamPaper(state="NSW", title="Paper A", time_limit_minutes=45)
        paper_b = MockExamPaper(state="NSW", title="Paper B", time_limit_minutes=45)
        paper_vic = MockExamPaper(state="VIC", title="Paper VIC", time_limit_minutes=40)
        db.session.add_all([paper_a, paper_b, paper_vic])
        db.session.flush()

        q_lookup = {q.qid: q for q in questions}

        db.session.add_all(
            [
                MockExamPaperQuestion(
                    paper_id=paper_a.id, question_id=q_lookup["CORE-1"].id, position=1
                ),
                MockExamPaperQuestion(
                    paper_id=paper_a.id, question_id=q_lookup["NSW-1"].id, position=2
                ),
                MockExamPaperQuestion(
                    paper_id=paper_b.id, question_id=q_lookup["CORE-1"].id, position=1
                ),
                MockExamPaperQuestion(
                    paper_id=paper_b.id, question_id=q_lookup["NSW-2"].id, position=2
                ),
                MockExamPaperQuestion(
                    paper_id=paper_vic.id, question_id=q_lookup["CORE-1"].id, position=1
                ),
                MockExamPaperQuestion(
                    paper_id=paper_vic.id, question_id=q_lookup["VIC-1"].id, position=2
                ),
            ]
        )

        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(seeded_app):
    return seeded_app.test_client()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_login_and_profile_flow(seeded_app, client):
    register_payload = {
        "mobileNumber": "0410000001",
        "password": "password123",
        "nickname": "Jamie",
        "state": "NSW",
        "preferredLanguage": "ENGLISH",
    }
    response = client.post("/api/auth/register", json=register_payload)
    assert response.status_code == 201
    token = response.get_json()["token"]

    with seeded_app.app_context():
        student = Student.query.filter_by(mobile_number="0410000001").one()
        assert student.state == "NSW"
        assert StudentStateProgress.query.filter_by(student_id=student.id, state="NSW").first()

    profile = client.get("/api/profile", headers=_auth_headers(token)).get_json()
    assert profile["nickname"] == "Jamie"
    assert profile["state"] == "NSW"

    login_resp = client.post(
        "/api/auth/login", json={"mobileNumber": "0410000001", "password": "password123"}
    )
    assert login_resp.status_code == 200
    login_token = login_resp.get_json()["token"]

    updated = client.put(
        "/api/profile",
        headers=_auth_headers(login_token),
        json={
            "nickname": "Jamie",
            "state": "VIC",
            "preferredLanguage": "CHINESE",
            "notificationPush": False,
            "notificationEmail": True,
        },
    ).get_json()
    assert updated["state"] == "VIC"
    assert updated["preferredLanguage"] == "CHINESE"

    with seeded_app.app_context():
        student = Student.query.filter_by(mobile_number="0410000001").one()
        assert student.preferred_language == "CHINESE"
        assert StudentStateProgress.query.filter_by(student_id=student.id, state="VIC").first()


def test_login_rate_limit(seeded_app, client):
    client.post(
        "/api/auth/register",
        json={
            "mobileNumber": "0410000002",
            "password": "password123",
            "nickname": "Alex",
            "state": "NSW",
            "preferredLanguage": "ENGLISH",
        },
    )

    for _ in range(5):
        resp = client.post(
            "/api/auth/login",
            json={"mobileNumber": "0410000002", "password": "badpass"},
        )
        assert resp.status_code in {401, 429}

    locked = client.post(
        "/api/auth/login",
        json={"mobileNumber": "0410000002", "password": "password123"},
    )
    assert locked.status_code == 429


def test_question_and_progress_flow(seeded_app, client):
    token = client.post(
        "/api/auth/register",
        json={
            "mobileNumber": "0410000003",
            "password": "password123",
            "nickname": "Morgan",
            "state": "NSW",
            "preferredLanguage": "ENGLISH",
        },
    ).get_json()["token"]

    list_resp = client.get("/api/questions", headers=_auth_headers(token)).get_json()
    assert len(list_resp["questions"]) >= 3
    first_question = list_resp["questions"][0]

    with seeded_app.app_context():
        db_question = db.session.get(Question, first_question["id"])
        assert db_question is not None
        wrong_option = next(option for option in ["A", "B", "C", "D"] if option != db_question.correct_option)

    attempt = client.post(
        f"/api/questions/{first_question['id']}/attempt",
        headers=_auth_headers(token),
        json={"chosenOption": wrong_option, "timeSpentSeconds": 25},
    ).get_json()
    assert set(attempt.keys()) == {"correct", "correctOption", "explanation"}
    assert attempt["correct"] is False

    client.post(
        f"/api/questions/{first_question['id']}/star",
        headers=_auth_headers(token),
        json={"action": "star"},
    )
    starred_list = client.get("/api/questions", headers=_auth_headers(token)).get_json()
    assert any(q["starred"] for q in starred_list["questions"])  # starred flag present

    notebook = client.get("/api/notebook", headers=_auth_headers(token)).get_json()
    assert any(item["questionId"] == first_question["id"] for item in notebook["starred"])
    wrong_entry = next(item for item in notebook["wrong"] if item["questionId"] == first_question["id"])
    assert wrong_entry["studentAnswer"] == wrong_option
    assert wrong_entry["correctAnswer"] != wrong_option

    delete_resp = client.delete(
        f"/api/notebook/{first_question['id']}", headers=_auth_headers(token)
    )
    assert delete_resp.status_code == 200
    notebook_after = client.get("/api/notebook", headers=_auth_headers(token)).get_json()
    assert all(item["questionId"] != first_question["id"] for item in notebook_after["wrong"])

    progress = client.get("/api/progress", headers=_auth_headers(token)).get_json()
    assert progress["total"] >= 3

    export_resp = client.get("/api/progress/export", headers=_auth_headers(token))
    assert export_resp.status_code == 200
    assert export_resp.mimetype == "text/csv"

    with seeded_app.app_context():
        student = Student.query.filter_by(mobile_number="0410000003").one()
        assert NotebookEntry.query.filter_by(student_id=student.id).count() == 0
        assert StarredQuestion.query.filter_by(student_id=student.id).count() == 1


def test_mock_exam_flow(seeded_app, client):
    token = client.post(
        "/api/auth/register",
        json={
            "mobileNumber": "0410000004",
            "password": "password123",
            "nickname": "Chris",
            "state": "NSW",
            "preferredLanguage": "ENGLISH",
        },
    ).get_json()["token"]

    papers = client.get("/api/mock-exams/papers", headers=_auth_headers(token)).get_json()["papers"]
    paper_id = papers[0]["paperId"]

    session = client.post(
        "/api/mock-exams/start",
        headers=_auth_headers(token),
        json={"paperId": paper_id},
    ).get_json()
    session_id = session["sessionId"]
    question_meta = session["questions"][0]

    client.post(
        f"/api/mock-exams/sessions/{session_id}/answer",
        headers=_auth_headers(token),
        json={"questionId": question_meta["questionId"], "selectedOption": "A"},
    )

    submit = client.post(
        f"/api/mock-exams/sessions/{session_id}/submit",
        headers=_auth_headers(token),
    ).get_json()
    assert submit["total"] >= 2
    assert "score" in submit

    details = client.get(
        f"/api/mock-exams/sessions/{session_id}", headers=_auth_headers(token)
    ).get_json()
    assert details["status"] == "submitted"
    assert all(q["correctOption"] for q in details["questions"])

    with seeded_app.app_context():
        student = Student.query.filter_by(mobile_number="0410000004").one()
        assert MockExamSummary.query.filter_by(student_id=student.id).count() == 1
        assert NotebookEntry.query.filter_by(student_id=student.id, state="NSW").count() >= 1
        session_record = db.session.get(StudentExamSession, session_id)
        assert session_record.finished_at is not None


def test_variant_generation_flow(seeded_app, client):
    token = client.post(
        "/api/auth/register",
        json={
            "mobileNumber": "0410000005",
            "password": "password123",
            "nickname": "Taylor",
            "state": "NSW",
            "preferredLanguage": "ENGLISH",
        },
    ).get_json()["token"]

    first_question = client.get("/api/questions", headers=_auth_headers(token)).get_json()["questions"][0]
    create_resp = client.post(
        f"/api/questions/{first_question['id']}/variants",
        headers=_auth_headers(token),
        json={"count": 2},
    )
    assert create_resp.status_code == 201
    group_payload = create_resp.get_json()["group"]
    assert len(group_payload["variants"]) == 2

    groups_list = client.get(
        "/api/questions/variants", headers=_auth_headers(token)
    ).get_json()["groups"]
    assert any(group["groupId"] == group_payload["groupId"] for group in groups_list)

    detail = client.get(
        f"/api/questions/variants/{group_payload['groupId']}",
        headers=_auth_headers(token),
    ).get_json()["group"]
    assert detail["groupId"] == group_payload["groupId"]

    delete_resp = client.delete(
        f"/api/questions/variants/{group_payload['groupId']}",
        headers=_auth_headers(token),
    )
    assert delete_resp.status_code == 200
    groups_after = client.get(
        "/api/questions/variants", headers=_auth_headers(token)
    ).get_json()["groups"]
    assert groups_after == []

    with seeded_app.app_context():
        assert VariantQuestionGroup.query.count() == 0
