# Coach Module

This repository implements the coach-facing features for the DriveWise driving theory preparation platform. It is built with Flask, SQLAlchemy, and Bootstrap.

## Coach capabilities

* Secure login/logout for registered coaches.
* Dashboard summarising assigned students, upcoming availability, and pending bookings.
* Profile management (contact info, operating state, vehicle types, personal bio).
* Weekly availability management with validation for 30/60 minute blocks.
* Appointments view with ability to update booking status (booked/completed/cancelled).
* Student list with quick insight into mock exam history summaries.

## Getting started

### Cloning the correct branch

When the repository is first cloned it may default to an empty `main` branch. The
full implementation lives on the `codex/define-core-features-for-student-module`
branch. Fetch all remote references and create a local branch that tracks the
remote using either `git checkout` or the newer `git switch` syntax:

```bash
git fetch --all
git checkout -b define-core-features-for-student-module \
  origin/codex/define-core-features-for-student-module
# or
git switch --track origin/codex/define-core-features-for-student-module
```

After the branch is checked out your IDE should show the complete project
structure. Subsequent updates can be pulled with `git pull` while on this
branch.

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
