# Learner Practice Portal (Unified Web Experience)

This repository powers the unified administrator, coach, and learner web
experience for a driver training platform. It is built with Flask, SQLAlchemy,
Bootstrap, and a pytest-backed test suite. In addition to the coaching flows,
the API surface for the student app covers:

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
management for creating accounts and resetting passwords across roles. The same
web portal now authenticates every role with a mobile number and surfaces a
learner self-registration form directly beneath the login action.

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
   The unified web portal is available at http://127.0.0.1:5000/coach/login and
   serves administrators, coaches, and students from the same entry point.

### Portal usage overview

- Sign in with the mobile number associated with the account (staff and learners
  share the same form).
- The "Register learner account" link routes to a dedicated registration page
  so the flow works without relying on modal JavaScript. After submitting valid
  details the learner is logged in and redirected to their dashboard
  automatically.
- All interface copy (including the exam centre, practice flows, and review
  pagination) has matching Simplified Chinese translations. Switch languages on
  the login form or in the profile settings and the state-specific exam content
  updates immediately.
- Language toggles no longer appear in the main navigation; switching happens on
  the login card or within profile settings, and the preference is reset on
  logout so every account returns to its default language.

### Exam management & learner practice

- Coaches (and administrators) have a new **Exams** workspace that surfaces
  published papers and provides a guided form for building new timed exams.
  Choose between manual question selection or automatic sampling by topic.
- Upload a complete question bank in bulk via the Excel importer. Matching QIDs
  are updated in-place so corrections can be re-uploaded without duplicate
  records.
- Students gain an **Exam centre** hub with two entry points: resume or start
  coach-issued papers aligned to their currently selected state, and launch a
  self-practice set that pulls random questions from the state bank plus
  nationally shared items.
- The **Study progress** area now supports state, topic, and date filters with
  performance cards, daily attempt trends, learning goal tracking, and
  state-scoped CSV exports that honour the chosen filters.
- Wrong answer review has a dedicated **Notebook** page linked from the student
  navigation for quick access to logged mistakes per state.
- During an exam the learner receives a compact navigator, countdown timer, and
  a structured review view with pagination (five questions per page) that can be
  filtered to show only incorrect answers. Saved responses instantly turn their
  navigator buttons green so it is obvious which items are complete. Timed
  sessions are persisted so refreshes do not lose progress.
- The learner dashboard surfaces the assigned coach's upcoming availability and
  lets students book open slots directly. Confirmations immediately convert the
  slot to a booked state on both the student and coach dashboards.
- Question banks and exam papers respect state boundaries: uploading questions
  or building papers captures the state scope, and students only see the
  variants targeted to their chosen jurisdiction.

#### Question bank Excel template

The importer accepts `.xlsx` workbooks with the following header names (English
or the paired Chinese equivalent). Columns marked as required must contain a
value for every row.

| Header (EN / 中文)     | Field               | Required | Notes |
| --------------------- | ------------------- | -------- | ----- |
| `QID` / `题目编号`     | External question ID| No       | When supplied, updates the matching record instead of creating a new one. |
| `Prompt` / `题干`      | Question stem       | **Yes**  | Supports rich text copied from Word/Excel. |
| `Option A` / `选项A`   | Answer option A     | **Yes**  | Text shown beside the `A` radio button. |
| `Option B` / `选项B`   | Answer option B     | **Yes**  | |
| `Option C` / `选项C`   | Answer option C     | **Yes**  | |
| `Option D` / `选项D`   | Answer option D     | **Yes**  | |
| `Correct Option` / `答案` | Correct letter (A–D) | **Yes** | Only the letter is required; the portal displays the matching option text. |
| `Topic` / `考点类型`   | Knowledge point     | No       | Defaults to `general` when omitted. |
| `Explanation` / `解析` | Rationale shown after grading | No | Ideal for remediation and practice mode. |
| `State Scope` / `适用州` | State/territory code | No | Uses the upload form's default (or `ALL`) if blank. |
| `Language` / `语言`    | Content language    | No       | Defaults to `ENGLISH`. |
| `Image URL` / `配图`   | Optional illustration | No    | Rendered alongside the prompt when present. |

> Tip: download the example template (see `/coach/exams`) and replace the
> placeholder rows to guarantee column order.

## Demo credentials

`seed-demo` provisions the following accounts for quick manual testing (all
roles authenticate with their mobile number):

| Role          | Mobile (login) | Email               | Password     |
| ------------- | -------------- | ------------------- | ------------ |
| Administrator | `0400999000`   | `admin@example.com` | `password123`|
| Coach         | `0400111222`   | `coach@example.com` | `password123`|
| Students      | `0400000100`   | `jamie@example.com` | `password123`|
|               | `0400000101`   | `priya@example.com` | `password123`|
|               | `0400000102`   | `morgan@example.com`| `password123`|

Administrators access all coach pages plus `/coach/personnel` for cross-role
account provisioning and password resets, while students are redirected to the
learner dashboard after signing in or registering.

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

To collect coverage details:

```bash
pytest --cov=app --cov-report=term-missing
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
