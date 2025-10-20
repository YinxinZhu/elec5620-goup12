from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest
from werkzeug.datastructures import MultiDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.config import TestConfig
from app.models import Admin, Appointment, AvailabilitySlot, Coach, Student


@pytest.fixture
def admin_app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()

        coach = Coach(
            email="coach@example.com",
            name="Coach One",
            phone="0400000001",
            city="Sydney",
            state="NSW",
            vehicle_types="AT,MT",
        )
        coach.set_password("password123")

        admin_coach = Coach(
            email="admin@example.com",
            name="Admin User",
            phone="0400000002",
            city="Melbourne",
            state="VIC",
            vehicle_types="AT,MT",
        )
        admin_coach.set_password("password123")

        db.session.add_all([coach, admin_coach])
        db.session.flush()

        db.session.add(Admin(id=admin_coach.id))

        student_a = Student(
            name="Jamie Lee",
            email="jamie@example.com",
            state="NSW",
            mobile_number="0410000001",
            preferred_language="ENGLISH",
            coach=coach,
        )
        student_b = Student(
            name="Morgan Patel",
            email="morgan@example.com",
            state="VIC",
            mobile_number="0410000002",
            preferred_language="ENGLISH",
            coach=admin_coach,
        )
        for student in (student_a, student_b):
            student.set_password("password123")
        db.session.add_all([student_a, student_b])
        db.session.flush()

        slot_coach = AvailabilitySlot(
            coach=coach,
            start_time=datetime.utcnow() + timedelta(days=1),
            duration_minutes=60,
            location_text="Sydney Olympic Park",
        )
        slot_admin = AvailabilitySlot(
            coach=admin_coach,
            start_time=datetime.utcnow() + timedelta(days=2),
            duration_minutes=60,
            location_text="Virtual session",
        )
        db.session.add_all([slot_coach, slot_admin])
        db.session.flush()

        appointment = Appointment(slot=slot_coach, student=student_a)
        slot_coach.status = "booked"
        db.session.add(appointment)

        db.session.commit()
        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(admin_app):
    return admin_app.test_client()


def test_account_roles_flagged(admin_app):
    with admin_app.app_context():
        coach = Coach.query.filter_by(email="coach@example.com").one()
        admin = Coach.query.filter_by(email="admin@example.com").one()

        assert coach.is_admin is False
        assert coach.get_id().startswith("coach:")

        assert admin.is_admin is True
        assert admin.get_id().startswith("admin:")
        assert Admin.query.filter_by(id=admin.id).one()


def test_admin_overview_and_slot_creation(client, admin_app):
    response = client.post(
        "/coach/login",
        data={"email": "admin@example.com", "password": "password123"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Administrator overview" in page
    assert "Total Students" in page

    students_page = client.get("/coach/students")
    students_html = students_page.get_data(as_text=True)
    assert "Jamie Lee" in students_html
    assert "Morgan Patel" in students_html
    assert "Assigned Coach" in students_html

    with admin_app.app_context():
        coach = Coach.query.filter_by(email="coach@example.com").one()
        original_count = AvailabilitySlot.query.filter_by(coach_id=coach.id).count()

    slot_time = (datetime.utcnow() + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")
    create_resp = client.post(
        "/coach/slots",
        data={
            "start_time": slot_time,
            "duration": "60",
            "location": "Test Location",
            "coach_id": str(coach.id),
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200

    with admin_app.app_context():
        new_count = AvailabilitySlot.query.filter_by(coach_id=coach.id).count()
        assert new_count == original_count + 1


def test_non_admin_cannot_access_personnel(client):
    client.post(
        "/coach/login",
        data={"email": "coach@example.com", "password": "password123"},
        follow_redirects=True,
    )

    response = client.get("/coach/personnel", follow_redirects=True)
    assert response.status_code == 200
    assert "Only administrators may access personnel management." in response.get_data(as_text=True)


def test_admin_can_manage_personnel(client, admin_app):
    client.post(
        "/coach/login",
        data={"email": "admin@example.com", "password": "password123"},
        follow_redirects=True,
    )

    page = client.get("/coach/personnel")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Add Account" in html
    assert "Coaches &amp; Administrators" in html

    coach_payload = MultiDict([
        ("form_type", "create"),
        ("role", "coach"),
        ("name", "Jordan Smith"),
        ("email", "jordan@example.com"),
        ("password", "secret99"),
        ("state", "QLD"),
        ("phone", "0400123123"),
        ("city", "Brisbane"),
        ("vehicle_types", "AT"),
        ("vehicle_types", "MT"),
    ])
    client.post("/coach/personnel", data=coach_payload, follow_redirects=True)

    with admin_app.app_context():
        new_coach = Coach.query.filter_by(email="jordan@example.com").one()
        assert new_coach.is_admin is False

    student_payload = MultiDict([
        ("form_type", "create"),
        ("role", "student"),
        ("name", "Taylor Reed"),
        ("email", "taylor@example.com"),
        ("password", "student99"),
        ("state", "QLD"),
        ("mobile_number", "0410000999"),
        ("assigned_coach_id", str(new_coach.id)),
    ])
    client.post("/coach/personnel", data=student_payload, follow_redirects=True)

    with admin_app.app_context():
        new_student = Student.query.filter_by(email="taylor@example.com").one()
        assert new_student.assigned_coach_id == new_coach.id

    update_student_password = {
        "form_type": "update_password",
        "account_type": "student",
        "account_id": str(new_student.id),
        "new_password": "refresh123",
    }
    client.post("/coach/personnel", data=update_student_password, follow_redirects=True)

    with admin_app.app_context():
        student = Student.query.filter_by(email="taylor@example.com").one()
        assert student.check_password("refresh123") is True

        admin_account = Coach.query.filter_by(email="admin@example.com").one()

    update_admin_password = {
        "form_type": "update_password",
        "account_type": "admin",
        "account_id": str(admin_account.id),
        "new_password": "newadminpass",
    }
    client.post("/coach/personnel", data=update_admin_password, follow_redirects=True)

    with admin_app.app_context():
        refreshed_admin = Coach.query.filter_by(email="admin@example.com").one()
        assert refreshed_admin.check_password("newadminpass") is True
