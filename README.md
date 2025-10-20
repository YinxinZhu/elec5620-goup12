# DriveWise Learning Platform (Coach & Admin Module)

This repository contains the coach and administrator experience for the DriveWise
learning platform. It is a Flask application that uses SQLAlchemy for data
access, Bootstrap for styling, and pytest for automated testing.

## Feature overview

- **Authentication** – Login/logout for coaches, students, and administrators
  backed by Flask-Login.
- **Coach dashboard** – Summaries of assigned students, upcoming availability,
  mock exam outcomes, and appointment status.
- **Availability & appointments** – Create, update, and monitor weekly
  availability slots and manage bookings.
- **Student insights** – Review student rosters, performance summaries, and
  mock exam sessions.
- **Administrator tooling** – Administrators inherit all coach capabilities and
  gain platform-wide personnel management (create/reset accounts for any role)
  plus visibility of every coach and student.

## Prerequisites

- Python 3.10+
- SQLite (bundled with Python) or another database supported by SQLAlchemy.
- Recommended: virtual environment tooling such as `venv` or `pyenv`.

## Getting started

Follow these steps the first time you set up the project:

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd elec5620
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Initialise (or upgrade) the database**
   - On first run create the schema with:
     ```bash
     flask --app manage.py init-db
     ```
   - Legacy databases are automatically patched at application start via
     `app.db_maintenance.ensure_current_schema`. No additional manual work is
     required; see [Database maintenance](#database-maintenance) for details.

5. **(Optional) Seed demo data**
   ```bash
   flask --app manage.py seed-demo
   ```
   This resets the database and inserts representative coaches, students,
   availability slots, mock exam records, and the default administrator.

6. **Run the development server**
   ```bash
   flask --app app run --debug
   ```
   Access the UI at http://127.0.0.1:5000/.

### Demo credentials

These accounts are created by `seed-demo` and useful for local testing:

| Role           | Email                | Password     |
| -------------- | -------------------- | ------------ |
| Administrator  | `admin@example.com`  | `password123`|
| Coach          | `coach@example.com`  | `password123`|
| Students       | `jamie@example.com`  | `password123`|
|                | `priya@example.com`  | `password123`|
|                | `morgan@example.com` | `password123`|

Administrators can access every coach page plus the personnel management area
(`/coach/personnel`) to create or reset accounts for any role.

## Common workflows

- **Create additional accounts** – Log in as the administrator and navigate to
  *Personnel Management* in the side navigation. Choose the desired role
  (coach, student, administrator), fill in the form, and submit. Password reset
  options are available in the account tables on the same page.
- **Manage availability** – Coaches (and administrators) can add 30 or 60 minute
  slots on the *Availability* page. Use the appointment list to accept or update
  booking statuses.
- **Review student activity** – The *Students* page summarises performance data,
  exam sessions, and provides quick filters per coach.

## Running tests

All automated checks run through pytest:

```bash
pytest
```

## Database maintenance

Legacy deployments created before the administrator role was introduced may lack
new columns or tables. The application invokes
`ensure_current_schema` from `app.db_maintenance` on start-up to:

1. Add the `students.mobile_number` column when missing and backfill placeholder
   data to preserve uniqueness constraints.
2. Create the `admins` table if it does not exist.
3. Ensure the default administrator account (`admin@example.com`) is present
   with a secure password hash.

These operations are idempotent and safe to run repeatedly. They ensure that
existing installations are upgraded without manual migrations.

## Environment configuration

- The default database lives at `instance/app.db` (SQLite). Override by setting
  the `DATABASE_URL` environment variable before launching the app.
- Configure Flask’s secret key via `FLASK_SECRET_KEY` for non-development
  environments.
- Flask respects the standard `FLASK_ENV` and `FLASK_DEBUG` variables. Use
  `--debug` locally to enable the reloader and interactive debugger.

## Project structure

```
app/                # Flask blueprints, models, templates, maintenance helpers
manage.py           # CLI entry point (init-db, seed-demo)
app.py              # Convenience runner that imports create_app
requirements.txt    # Python dependencies
tests/              # pytest-based regression suite
```

With these steps the DriveWise coach and administrator module is ready for local
development or evaluation.
