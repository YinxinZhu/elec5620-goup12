from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any

from flask import Response, current_app, g, jsonify, request
from .. import db
from ..models import (
    ExamRule,
    MockExamPaper,
    MockExamSummary,
    NotebookEntry,
    Question,
    QuestionAttempt,
    StarredQuestion,
    Student,
    StudentAuthToken,
    StudentExamAnswer,
    StudentExamSession,
    StudentLoginRateLimit,
)
from ..services.progress import (
    ProgressAccessError,
    ProgressValidationError,
    export_state_progress_csv,
    get_progress_summary,
)
from ..services.state_management import (
    StateSwitchError,
    StateSwitchValidationError,
    get_questions_for_state,
    switch_student_state,
)
from . import api_bp

PHONE_REGEX = re.compile(r"^\+?\d{8,15}$")
VALID_LANGUAGES = {"ENGLISH", "CHINESE"}
VALID_OPTIONS = {"A", "B", "C", "D"}


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _extract_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _require_auth(func):
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        token_value = _extract_token()
        if not token_value:
            return _json_error("Authentication token required.", 401)
        token = StudentAuthToken.query.filter_by(token=token_value, revoked=False).first()
        if not token or token.expires_at <= datetime.utcnow():
            return _json_error("Invalid or expired token.", 401)
        g.current_student = token.student
        g.current_token = token
        return func(*args, **kwargs)

    return wrapper


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _ensure_exam_rule(state: str) -> ExamRule:
    rule = ExamRule.query.filter_by(state=state).first()
    if not rule:
        raise StateSwitchValidationError(f"No exam rule configured for state '{state}'.")
    return rule


def _normalise_state(state: str | None) -> str:
    return (state or "").strip().upper()


def _serialise_profile(student: Student) -> dict[str, Any]:
    return {
        "userId": student.id,
        "nickname": student.name,
        "avatarUrl": student.avatar_url,
        "state": student.state,
        "preferredLanguage": student.preferred_language,
        "targetExamDate": student.target_exam_date.isoformat()
        if student.target_exam_date
        else None,
        "notificationPreferences": {
            "push": student.notification_push_enabled,
            "email": student.notification_email_enabled,
        },
        "profileVersion": student.profile_version,
        "updatedAt": student.profile_updated_at.isoformat()
        if student.profile_updated_at
        else None,
    }


def _questions_payload(student: Student, *, state: str, topic: str | None = None) -> list[dict[str, Any]]:
    questions = get_questions_for_state(state)
    starred_ids = {
        entry.question_id for entry in StarredQuestion.query.filter_by(student_id=student.id)
    }
    payload: list[dict[str, Any]] = []
    for question in questions:
        if topic and question.topic.lower() != topic.lower():
            continue
        payload.append(
            {
                "id": question.id,
                "qid": question.qid,
                "prompt": question.prompt,
                "topic": question.topic,
                "stateScope": question.state_scope,
                "options": {
                    "A": question.option_a,
                    "B": question.option_b,
                    "C": question.option_c,
                    "D": question.option_d,
                },
                "starred": question.id in starred_ids,
                "imageUrl": question.image_url,
            }
        )
    return payload


def _session_questions(session: StudentExamSession) -> list[dict[str, Any]]:
    ordered = sorted(session.paper.questions, key=lambda pq: pq.position)
    answer_lookup = {answer.question_id: answer for answer in session.answers}
    items: list[dict[str, Any]] = []
    for paper_question in ordered:
        question = paper_question.question
        answer = answer_lookup.get(question.id)
        items.append(
            {
                "questionId": question.id,
                "qid": question.qid,
                "position": paper_question.position,
                "prompt": question.prompt,
                "topic": question.topic,
                "options": {
                    "A": question.option_a,
                    "B": question.option_b,
                    "C": question.option_c,
                    "D": question.option_d,
                },
                "selectedOption": answer.selected_option if answer else None,
                "isCorrect": answer.is_correct if answer and session.status == "submitted" else None,
                "correctOption": question.correct_option if session.status == "submitted" else None,
                "explanation": question.explanation if session.status == "submitted" else None,
            }
        )
    return items


def _ensure_session_active(session: StudentExamSession) -> StudentExamSession:
    if (
        session.status == "ongoing"
        and session.expires_at
        and datetime.utcnow() >= session.expires_at
    ):
        _finalise_session(session, auto=True)
    return session


def _finalise_session(session: StudentExamSession, *, auto: bool) -> None:
    if session.status != "ongoing":
        return

    now = datetime.utcnow()
    ordered = sorted(session.paper.questions, key=lambda pq: pq.position)
    answer_lookup = {answer.question_id: answer for answer in session.answers}
    score = 0
    wrong_questions: list[Question] = []

    for paper_question in ordered:
        question = paper_question.question
        answer = answer_lookup.get(question.id)
        if answer and answer.is_correct:
            score += 1
        else:
            wrong_questions.append(question)

    session.status = "submitted"
    session.finished_at = now
    session.score = score
    session.total_questions = session.total_questions or len(ordered)

    summary = MockExamSummary(student_id=session.student_id, state=session.state, score=score)
    db.session.add(summary)

    for question in wrong_questions:
        entry = (
            NotebookEntry.query.filter_by(
                student_id=session.student_id, question_id=question.id, state=session.state
            ).first()
        )
        if not entry:
            entry = NotebookEntry(
                student_id=session.student_id,
                question_id=question.id,
                state=session.state,
                wrong_count=1,
                last_wrong_at=now,
            )
            db.session.add(entry)
        else:
            entry.wrong_count += 1
            entry.last_wrong_at = now

    db.session.commit()


@api_bp.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    mobile = (data.get("mobileNumber") or "").strip()
    password = (data.get("password") or "").strip()
    nickname = (data.get("nickname") or "").strip()
    state = _normalise_state(data.get("state"))
    preferred_language = _normalise_state(data.get("preferredLanguage")) or "ENGLISH"

    if not PHONE_REGEX.match(mobile):
        return _json_error("A valid mobile number is required.")
    if len(password) < 6:
        return _json_error("Password must be at least 6 characters long.")
    if not nickname:
        return _json_error("Nickname is required.")
    if not state:
        return _json_error("A target state is required.")
    if preferred_language not in VALID_LANGUAGES:
        return _json_error("Preferred language must be English or Chinese.")
    if Student.query.filter_by(mobile_number=mobile).first():
        return _json_error("Mobile number is already registered.", 409)

    try:
        _ensure_exam_rule(state)
    except StateSwitchValidationError as exc:  # pragma: no cover - defensive
        return _json_error(str(exc))

    target_exam_date = _parse_date(data.get("targetExamDate"))
    student = Student(
        name=nickname,
        email=data.get("email"),
        mobile_number=mobile,
        state=state,
        preferred_language=preferred_language,
        target_exam_date=target_exam_date,
        avatar_url=data.get("avatarUrl"),
        notification_push_enabled=data.get("notificationPush", True),
        notification_email_enabled=data.get("notificationEmail", True),
        profile_version=1,
        profile_updated_at=datetime.utcnow(),
    )
    student.set_password(password)
    db.session.add(student)
    db.session.commit()

    switch_student_state(student, state, acting_student=student)

    token = student.issue_token()
    student.last_login_at = datetime.utcnow()
    db.session.add(student)
    db.session.commit()

    current_app.logger.info("register success", extra={"mobile": mobile})

    return (
        jsonify(
            {
                "userId": student.id,
                "token": token.token,
                "expiresAt": token.expires_at.isoformat(),
                "redirectUrl": "/home",
            }
        ),
        201,
    )


@api_bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    mobile = (data.get("mobileNumber") or "").strip()
    password = (data.get("password") or "").strip()

    if not mobile or not password:
        return _json_error("Mobile number and password are required.")

    now = datetime.utcnow()
    window = StudentLoginRateLimit.query.filter_by(mobile_number=mobile).first()
    if not window:
        window = StudentLoginRateLimit(mobile_number=mobile, attempt_count=0, window_started_at=now)
        db.session.add(window)
    elif now - window.window_started_at >= timedelta(minutes=15):
        window.attempt_count = 0
        window.window_started_at = now

    if window.attempt_count >= 5:
        db.session.commit()
        return _json_error("Too many login attempts. Try again later.", 429)

    student = Student.query.filter_by(mobile_number=mobile).first()
    if not student or not student.check_password(password):
        window.attempt_count += 1
        db.session.commit()
        return _json_error("Invalid mobile number or password.", 401)

    window.attempt_count = 0
    window.window_started_at = now
    window.student = student

    token = student.issue_token()
    student.last_login_at = now
    db.session.add(student)
    db.session.commit()

    current_app.logger.info("login success", extra={"mobile": mobile})

    return jsonify(
        {
            "userId": student.id,
            "token": token.token,
            "expiresAt": token.expires_at.isoformat(),
            "redirectUrl": "/home",
        }
    )


@api_bp.post("/auth/logout")
@_require_auth
def logout():
    token: StudentAuthToken = g.current_token
    token.revoked = True
    db.session.commit()
    return jsonify({"message": "Logged out"})


@api_bp.post("/auth/password/change")
@_require_auth
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = (data.get("currentPassword") or "").strip()
    new_password = (data.get("newPassword") or "").strip()
    student: Student = g.current_student

    if not student.check_password(current_password):
        return _json_error("Current password is incorrect.", 403)
    if len(new_password) < 6:
        return _json_error("Password must be at least 6 characters long.")

    student.set_password(new_password)
    db.session.commit()
    return jsonify({"message": "Password updated"})


@api_bp.post("/auth/password/reset")
def reset_password():
    data = request.get_json(silent=True) or {}
    mobile = (data.get("mobileNumber") or "").strip()
    new_password = (data.get("newPassword") or "").strip()

    if not PHONE_REGEX.match(mobile):
        return _json_error("Valid mobile number required.")
    if len(new_password) < 6:
        return _json_error("Password must be at least 6 characters long.")

    student = Student.query.filter_by(mobile_number=mobile).first()
    if not student:
        return _json_error("Account not found.", 404)

    student.set_password(new_password)
    db.session.commit()
    return jsonify({"message": "Password reset"})


@api_bp.get("/profile")
@_require_auth
def get_profile():
    student: Student = g.current_student
    return jsonify(_serialise_profile(student))


@api_bp.put("/profile")
@_require_auth
def update_profile():
    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip()
    avatar_url = data.get("avatarUrl")
    preferred_language = _normalise_state(data.get("preferredLanguage")) or "ENGLISH"
    target_state = _normalise_state(data.get("state"))
    target_exam_date = _parse_date(data.get("targetExamDate"))
    push_enabled = data.get("notificationPush")
    email_enabled = data.get("notificationEmail")

    if not nickname:
        return _json_error("Nickname is required.")
    if preferred_language not in VALID_LANGUAGES:
        return _json_error("Preferred language must be English or Chinese.")

    student: Student = g.current_student

    if target_state and target_state != student.state:
        try:
            switch_student_state(student, target_state, acting_student=student)
        except StateSwitchError as exc:
            return _json_error(str(exc))

    student.name = nickname
    student.avatar_url = avatar_url
    student.preferred_language = preferred_language
    student.target_exam_date = target_exam_date
    if push_enabled is not None:
        student.notification_push_enabled = bool(push_enabled)
    if email_enabled is not None:
        student.notification_email_enabled = bool(email_enabled)
    student.profile_version += 1
    student.profile_updated_at = datetime.utcnow()

    db.session.commit()

    return jsonify(_serialise_profile(student))


@api_bp.post("/state/switch")
@_require_auth
def manual_state_switch():
    data = request.get_json(silent=True) or {}
    state = _normalise_state(data.get("state"))
    if not state:
        return _json_error("State is required.")
    student: Student = g.current_student
    try:
        summary = switch_student_state(student, state, acting_student=student)
    except StateSwitchError as exc:
        return _json_error(str(exc))
    return jsonify({"message": summary})


@api_bp.get("/questions")
@_require_auth
def list_questions():
    student: Student = g.current_student
    state = _normalise_state(request.args.get("state")) or student.state
    topic = request.args.get("topic")
    if state != student.state:
        return _json_error("Questions are limited to the current state context.", 403)

    try:
        _ensure_exam_rule(state)
    except StateSwitchValidationError as exc:
        return _json_error(str(exc))

    return jsonify({"questions": _questions_payload(student, state=state, topic=topic)})


@api_bp.get("/questions/<int:question_id>")
@_require_auth
def get_question(question_id: int):
    student: Student = g.current_student
    question = Question.query.get_or_404(question_id)
    if question.state_scope not in {"ALL", student.state}:
        return _json_error("Question not available for current state.", 403)

    return jsonify(
        {
            "id": question.id,
            "qid": question.qid,
            "prompt": question.prompt,
            "topic": question.topic,
            "stateScope": question.state_scope,
            "options": {
                "A": question.option_a,
                "B": question.option_b,
                "C": question.option_c,
                "D": question.option_d,
            },
            "explanation": question.explanation,
            "imageUrl": question.image_url,
        }
    )


@api_bp.post("/questions/<int:question_id>/attempt")
@_require_auth
def attempt_question(question_id: int):
    student: Student = g.current_student
    question = Question.query.get_or_404(question_id)
    if question.state_scope not in {"ALL", student.state}:
        return _json_error("Question not available for current state.", 403)

    data = request.get_json(silent=True) or {}
    chosen = (data.get("chosenOption") or "").strip().upper()
    time_spent = int(data.get("timeSpentSeconds") or 0)
    time_spent = max(time_spent, 0)

    if chosen not in VALID_OPTIONS:
        return _json_error("A valid option (A-D) must be provided.")

    is_correct = chosen == question.correct_option
    attempt = QuestionAttempt(
        student_id=student.id,
        question_id=question.id,
        state=student.state,
        is_correct=is_correct,
        chosen_option=chosen,
        time_spent_seconds=time_spent,
    )
    db.session.add(attempt)

    if not is_correct:
        entry = (
            NotebookEntry.query.filter_by(
                student_id=student.id, question_id=question.id, state=student.state
            ).first()
        )
        now = datetime.utcnow()
        if not entry:
            entry = NotebookEntry(
                student_id=student.id,
                question_id=question.id,
                state=student.state,
                wrong_count=1,
                last_wrong_at=now,
            )
            db.session.add(entry)
        else:
            entry.wrong_count += 1
            entry.last_wrong_at = now

    db.session.commit()

    return jsonify(
        {
            "correct": is_correct,
            "correctOption": question.correct_option,
            "explanation": question.explanation,
        }
    )


@api_bp.post("/questions/<int:question_id>/star")
@_require_auth
def star_question(question_id: int):
    student: Student = g.current_student
    action = (request.get_json(silent=True) or {}).get("action", "star")
    question = Question.query.get_or_404(question_id)
    if question.state_scope not in {"ALL", student.state}:
        return _json_error("Question not available for current state.", 403)

    entry = StarredQuestion.query.filter_by(
        student_id=student.id, question_id=question.id
    ).first()

    if action == "star":
        if not entry:
            entry = StarredQuestion(student_id=student.id, question_id=question.id)
            db.session.add(entry)
            db.session.commit()
        return jsonify({"starred": True})

    if entry:
        db.session.delete(entry)
        db.session.commit()
    return jsonify({"starred": False})


@api_bp.get("/progress")
@_require_auth
def progress_summary():
    student: Student = g.current_student
    state = request.args.get("state")
    try:
        summary = get_progress_summary(student, state=state, acting_student=student)
    except (ProgressValidationError, ProgressAccessError) as exc:
        return _json_error(str(exc))
    return jsonify(
        {
            "state": summary.state,
            "total": summary.total,
            "done": summary.done,
            "correct": summary.correct,
            "wrong": summary.wrong,
            "pending": summary.pending,
            "lastScore": summary.last_score,
        }
    )


@api_bp.get("/progress/export")
@_require_auth
def progress_export():
    student: Student = g.current_student
    state = request.args.get("state")
    try:
        csv_payload = export_state_progress_csv(student, state=state, acting_student=student)
    except (ProgressValidationError, ProgressAccessError) as exc:
        return _json_error(str(exc))

    response = Response(csv_payload, mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=progress.csv"
    return response


@api_bp.get("/mock-exams/papers")
@_require_auth
def list_mock_papers():
    student: Student = g.current_student
    papers = (
        MockExamPaper.query.filter_by(state=student.state)
        .order_by(MockExamPaper.id.asc())
        .all()
    )
    payload = [
        {
            "paperId": paper.id,
            "title": paper.title,
            "timeLimitMinutes": paper.time_limit_minutes,
            "questionCount": len(paper.questions),
        }
        for paper in papers
    ]
    return jsonify({"papers": payload})


@api_bp.post("/mock-exams/start")
@_require_auth
def start_mock_exam():
    data = request.get_json(silent=True) or {}
    paper_id = data.get("paperId")
    if not paper_id:
        return _json_error("paperId is required.")
    student: Student = g.current_student
    paper = MockExamPaper.query.filter_by(id=paper_id, state=student.state).first()
    if not paper:
        return _json_error("Exam paper not available for current state.", 404)

    existing = (
        StudentExamSession.query.filter_by(student_id=student.id, status="ongoing")
        .order_by(StudentExamSession.started_at.desc())
        .first()
    )
    if existing and existing.paper_id != paper.id:
        return _json_error("Finish the current exam before starting a new one.", 409)

    if existing:
        session = _ensure_session_active(existing)
        if session.status == "submitted":
            existing = None
        else:
            return jsonify(
                {
                    "sessionId": session.id,
                    "status": session.status,
                    "startedAt": session.started_at.isoformat(),
                    "expiresAt": session.expires_at.isoformat() if session.expires_at else None,
                    "questions": _session_questions(session),
                }
            )

    now = datetime.utcnow()
    session = StudentExamSession(
        student_id=student.id,
        state=student.state,
        paper_id=paper.id,
        expires_at=now + timedelta(minutes=paper.time_limit_minutes),
        total_questions=len(paper.questions),
    )
    db.session.add(session)
    db.session.commit()

    return jsonify(
        {
            "sessionId": session.id,
            "status": session.status,
            "startedAt": session.started_at.isoformat(),
            "expiresAt": session.expires_at.isoformat() if session.expires_at else None,
            "questions": _session_questions(session),
        }
    )


@api_bp.post("/mock-exams/sessions/<int:session_id>/answer")
@_require_auth
def answer_question(session_id: int):
    student: Student = g.current_student
    session = StudentExamSession.query.filter_by(id=session_id, student_id=student.id).first_or_404()
    session = _ensure_session_active(session)
    if session.status != "ongoing":
        return _json_error("Exam session already finished.", 409)

    data = request.get_json(silent=True) or {}
    question_id = data.get("questionId")
    selected_option = (data.get("selectedOption") or "").strip().upper()
    if question_id is None or selected_option not in VALID_OPTIONS:
        return _json_error("questionId and a valid selectedOption are required.")

    paper_question = next((pq for pq in session.paper.questions if pq.question_id == question_id), None)
    if not paper_question:
        return _json_error("Question not part of this exam.", 404)

    question = paper_question.question
    answer = StudentExamAnswer.query.filter_by(
        session_id=session.id, question_id=question_id
    ).first()
    is_correct = selected_option == question.correct_option
    if not answer:
        answer = StudentExamAnswer(
            session_id=session.id,
            question_id=question_id,
            selected_option=selected_option,
            is_correct=is_correct,
        )
        db.session.add(answer)
    else:
        answer.selected_option = selected_option
        answer.is_correct = is_correct
        answer.answered_at = datetime.utcnow()

    db.session.commit()

    return jsonify({"saved": True, "isCorrect": is_correct if session.status == "submitted" else None})


@api_bp.post("/mock-exams/sessions/<int:session_id>/submit")
@_require_auth
def submit_mock_exam(session_id: int):
    student: Student = g.current_student
    session = StudentExamSession.query.filter_by(id=session_id, student_id=student.id).first_or_404()
    _ensure_session_active(session)
    if session.status == "submitted":
        rule = _ensure_exam_rule(session.state)
        return jsonify(
            {
                "score": session.score,
                "total": session.total_questions,
                "passMark": rule.pass_mark,
                "passed": (session.score or 0) >= rule.pass_mark if session.score is not None else False,
            }
        )

    _finalise_session(session, auto=False)
    rule = _ensure_exam_rule(session.state)
    return jsonify(
        {
            "score": session.score,
            "total": session.total_questions,
            "passMark": rule.pass_mark,
            "passed": (session.score or 0) >= rule.pass_mark if session.score is not None else False,
        }
    )


@api_bp.get("/mock-exams/sessions")
@_require_auth
def list_sessions():
    student: Student = g.current_student
    sessions = (
        StudentExamSession.query.filter_by(student_id=student.id)
        .order_by(StudentExamSession.started_at.desc())
        .all()
    )
    rule_lookup = {
        session.state: _ensure_exam_rule(session.state) for session in sessions
    }
    payload = []
    for session in sessions:
        rule = rule_lookup.get(session.state)
        payload.append(
            {
                "sessionId": session.id,
                "paperId": session.paper_id,
                "status": session.status,
                "score": session.score,
                "total": session.total_questions,
                "passMark": rule.pass_mark if rule else None,
                "startedAt": session.started_at.isoformat(),
                "finishedAt": session.finished_at.isoformat() if session.finished_at else None,
            }
        )
    return jsonify({"sessions": payload})


@api_bp.get("/mock-exams/sessions/<int:session_id>")
@_require_auth
def get_session(session_id: int):
    student: Student = g.current_student
    session = StudentExamSession.query.filter_by(id=session_id, student_id=student.id).first_or_404()
    session = _ensure_session_active(session)
    rule = _ensure_exam_rule(session.state)
    return jsonify(
        {
            "sessionId": session.id,
            "paperId": session.paper_id,
            "status": session.status,
            "score": session.score,
            "total": session.total_questions,
            "passMark": rule.pass_mark,
            "startedAt": session.started_at.isoformat(),
            "finishedAt": session.finished_at.isoformat() if session.finished_at else None,
            "expiresAt": session.expires_at.isoformat() if session.expires_at else None,
            "questions": _session_questions(session),
        }
    )
