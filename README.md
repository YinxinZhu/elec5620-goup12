# Learner Practice Portal (Coach & Admin Module)

This repository powers the coach and administrator experience for a learner
driver training platform. It is built with Flask, SQLAlchemy, Bootstrap, and a
pytest-backed test suite. In addition to the coaching flows, the API surface for
the student app covers:

- **Question bank practice (AH-01)** – Browse questions by state/topic,
  attempt single-choice items, receive instant feedback with explanations,
  toggle starred questions, and automatically capture wrong attempts in a
  notebook without duplicates.
- **Mock exams (AH-02)** – Two timed papers per state with full navigation,
  autosubmission on expiry, grading, summaries, and post-exam review screens
  that highlight incorrect answers while withholding solutions for in-progress
  sessions.
- **Variant question generation (AH-03)** – Create AI-inspired scenario
  variations from any base question, persist knowledge point groupings, and
  revisit generated items later.
- **Notebook (AH-04)** – Unified access to wrong and starred questions with
  paginated metadata, the latest student selection, correct answers, and manual
  removal controls.

Administrators inherit every coach ability and add platform-wide personnel
management for creating accounts and resetting passwords across roles.

## Prerequisites

- Python 3.10+
- SQLite (bundled with Python) or any database supported by SQLAlchemy
- Optional but recommended: `venv` or `pyenv` for virtual environment
  management

## Getting started

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd elec5620
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   ```

3. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Initialise (or upgrade) the database**
   ```bash
   flask --app manage.py init-db
   ```
   The application also runs lightweight maintenance checks at startup that add
   missing columns/tables and reseed the administrator account when upgrading an
   existing SQLite database.

5. **(Optional) Seed demo data**
   ```bash
   flask --app manage.py seed-demo
   ```
   This command resets the database and seeds:
   - Coach and administrator accounts (with hashed credentials)
   - Three sample students linked to the demo coaches
   - Availability slots, an appointment booking, and historical mock exam
     summaries
   - A 300-question bank (120 NSW questions, 180 across VIC/QLD/SA) plus timed
     papers that satisfy AH-01/AH-02 requirements

6. **Run the development server**
   ```bash
   flask --app app run --debug
   ```
   The coach/admin UI is available at http://127.0.0.1:5000/.

## Demo credentials

`seed-demo` provisions the following accounts for quick manual testing:

| Role          | Email               | Password     |
| ------------- | ------------------- | ------------ |
| Administrator | `admin@example.com` | `password123`|
| Coach         | `coach@example.com` | `password123`|
| Students      | `jamie@example.com` | `password123`|
|               | `priya@example.com` | `password123`|
|               | `morgan@example.com`| `password123`|

Administrators access all coach pages plus `/coach/personnel` for cross-role
account provisioning and password resets.

## Student API quick reference

- `GET /api/questions` – Question bank by topic/state with starred flags
- `POST /api/questions/<id>/attempt` – Record an attempt, return correctness and
  explanation, and update the wrong-question notebook
- `POST /api/questions/<id>/star` – Star/unstar for quick access
- `GET /api/notebook` / `DELETE /api/notebook/<id>` – Review or clear wrong
  notebook entries; starred questions are returned alongside wrong answers
- `POST /api/questions/<id>/variants` – Generate and store scenario variants;
  retrieve via `GET /api/questions/variants`
- `POST /api/mock-exams/start` – Begin a timed session; submit with
  `/submit`, inspect with `/sessions/<id>`

Refer to `tests/test_student_api.py` for end-to-end usage examples.

## Running tests

```bash
pytest
```

## Database maintenance

`app.db_maintenance.ensure_database_schema` applies safe, idempotent checks when
the Flask app starts:

1. Add the `students.mobile_number` column for legacy records and backfill
   placeholder values while recreating the unique index
2. Create the `admins` table (if absent) and ensure the default
   `admin@example.com` account exists with a hashed password
3. Create the variant question tables used by AH-03 so upgraded deployments gain
   AI-generated content storage automatically

## Project structure

```
app/                # Flask blueprints, models, templates, services
manage.py           # CLI entry point (init-db, seed-demo)
app.py              # Convenience runner that imports create_app
requirements.txt    # Python dependencies
tests/              # pytest regression suite
```

With these steps the learner practice portal is ready for local development or
integration into a broader deployment.
