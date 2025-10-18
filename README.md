# DriveWise Learning Platform (Coach Module)

This repository implements the coach-facing features for the DriveWise driving theory preparation platform. It is built with Flask, SQLAlchemy, and Bootstrap.

## Coach capabilities

* Secure login/logout for registered coaches.
* Dashboard summarising assigned students, upcoming availability, and pending bookings.
* Profile management (contact info, operating state, vehicle types, personal bio).
* Weekly availability management with validation for 30/60 minute blocks.
* Appointments view with ability to update booking status (booked/completed/cancelled).
* Student list with quick insight into mock exam history summaries.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app manage.py init-db
flask --app manage.py seed-demo  # optional demo data
flask --app app run --debug
```

Demo credentials are seeded via `seed-demo` (`coach@example.com` / `password123`).

The application stores data in `instance/app.db` by default (SQLite). Configure `DATABASE_URL` for PostgreSQL or other engines in production.
