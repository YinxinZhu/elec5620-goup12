# DKT Learning Assistant
## Learner Practice Portal (Unified Web Experience)

**Table of Contents**

- [Project Overview](#project-overview)
- [Configuration & Deployment](#configuration--deployment)
- [Advanced Technologies](#advanced-technologies)
- [AI Agent](#ai-agent)
- [Feature Details](#feature-details)
- [Development Guide](#development-guide)
- [Use of AI Statement](#use-of-ai-statement)


## Project Overview

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



## Configuration & Deployment

### Prerequisites

- Python 3.10+
- SQLite (bundled with Python) or any database supported by SQLAlchemy
- Optional but recommended: `venv` or `pyenv` for virtual environment
  management

### Installation guide

#### One-command bootstrap (recommended for local demos)

```bash
scripts/bootstrap.bat
```

The helper script creates a `.venv` virtual environment, installs the
dependencies, initialises the SQLite database, seeds demo data, and launches the
development server. Pass `--no-seed` to skip demo fixtures or `--skip-run` to
only prepare the environment.

1. **Install dependencies**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Initialise (or upgrade) the database**
   ```bash
   flask --app manage.py init-db
   ```
   The application also runs lightweight maintenance checks at startup that add
   missing columns/tables and reseed the administrator account when upgrading an
   existing SQLite database.

3. **(Optional) Seed demo data**
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

4. **Run the development server**
   ```bash
   flask --app app run --debug
   ```
   The unified web portal is available at http://127.0.0.1:5000/coach/login and
   serves administrators, coaches, and students from the same entry point.

## Demo Accounts

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



## Advanced Technologies

### Flask
Flask is a lightweight Python web framework that powers the application's request routing, templating, and middleware stack, giving us the flexibility to compose blueprints for coaches, administrators, and learners within a unified portal. Its modular extension ecosystem lets us layer in authentication, caching, and background workers incrementally so the platform scales without sacrificing clarity in the core server code.

### Modular Flask Full-stack Framework: 
The backend is centered on Flask, 
combined with SQLAlchemy ORM, Flask-Migrate data migration framework, 
and Flask-Login authentication, forming an extensible multi-blueprint Web application skeleton, 
and realizing dynamic language switching and template context injection in request hooks.

### SQLAlchemy
SQLAlchemy provides the ORM and SQL toolkit used to model the training data, generate migrations, and interact with the underlying database through expressive Python abstractions rather than raw SQL.

### LangChain + FastAPI Agent Service: 
`langchain/server.py` exposes FastAPI interfaces, 
and internally reuses LangChain's tool calling agent, ChatOpenAI model, 
and custom Agent tracer to produce structured JSON question variant results according to a strict workflow.


### LangChain
LangChain orchestrates large language model workflows in the project, enabling the variant generation services and AI agent to chain prompts, tools, and memory for context-aware reasoning.

### Built-in Multilingual Support and Localization Resources: 
`app/i18n.py` provides cacheable language mappings, 
translation dictionaries, and speech metadata, enabling the entire portal interface to support Chinese-English bilingual switching 
and seamlessly integrate with identity management logic.


### OpenAI GPT-5
GPT-5 is OpenAI's newest and most capable model launched in 2025. The model's expanded context window and fine-grained alignment controls keep outputs consistent with project guidelines. With GPT-5 as This breadth of capability underpins the AI agent flows in the platform, giving them a dependable foundation for sophisticated tooling decisions and high-quality assistance.

### Codex
Codex is a powerful AI coding tool developed by OpenAI. Its core strength is the ability to self-invoke and deliver robust functionality without elaborate prompting. Codex adapts quickly to complex systems, compensates for context-window limits by dispatching specialized tools to gather relevant information, and confidently synthesizes correct implementations even when multiple files must be considered simultaneously.



## AI Agent

### Architecture and work flows of LangChain AI Agent

#### Step 1: analyze_topic
The planner first calls the analyze_topic tool to capture the knowledge point name and summary that will serve as shared context for every variant.

#### Step 2: plan_variations
With that context and the target quantity, the planner calls plan_variations to obtain a list of variation plans, each indicating the aspect to focus on (scenario, wording, numbers, etc.).

#### Step 3: generate_question (loop)
For each plan item, the planner calls generate_question to create a full prompt, four answer choices, the correct option, and an explanation.

#### Step 4: validate_question (loop, with backtracking when needed)
Right after generation, the planner invokes validate_question to ensure compliance. If the check fails, the planner incorporates the feedback and repeats Step 3 until the question passes.

Once every question clears validation, the planner outputs the final JSON result, and the agent parses and organizes everything in one shot. This is the internal tool-calling flow you need for the agent.



## Feature Details

### Portal usage overview

- Sign in with the mobile number associated with the account (staff and learners
  share the same form).
- The "Register learner account" link routes to a dedicated registration page
  so the flow works without relying on modal JavaScript. After submitting valid
  details the learner is logged in and redirected to their dashboard
  automatically.
- All interface copy (including the exam centre, practice flows, review
  pagination, and the coach/administrator workspaces) has matching Simplified
  Chinese translations. Switch languages on the login form or in profile
  settings and the state-specific content updates immediately across dashboards,
  availability management, and personnel tables.
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
  slot to a booked state on both the student and coach dashboards, while
  cancellation windows follow the training policy: more than 24 hours' notice
  cancels instantly, requests within 24 hours but outside two hours require
  coach approval, and the final two-hour window locks the booking.
- Question banks and exam papers respect state boundaries: uploading questions
  or building papers captures the state scope, and students only see the
  variants targeted to their chosen jurisdiction.

### Question bank Excel template

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



## Development Guide

### Student API quick reference

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

### Running tests

```bash
pytest
```

To collect coverage details:

```bash
pytest --cov=app --cov-report=term-missing
```

### Database maintenance

`app.db_maintenance.ensure_database_schema` applies safe, idempotent checks when
the Flask app starts:

1. Add the `students.mobile_number` column for legacy records and backfill
   placeholder values while recreating the unique index
2. Create the `admins` table (if absent) and ensure the default
   `admin@example.com` account exists with a hashed password
3. Create the variant question tables used by AH-03 so upgraded deployments gain
   AI-generated content storage automatically

### Project structure

```
app/                # Flask blueprints, models, templates, services
manage.py           # CLI entry point (init-db, seed-demo)
app.py              # Convenience runner that imports create_app
requirements.txt    # Python dependencies
tests/              # pytest regression suite
```

With these steps the learner practice portal is ready for local development or
integration into a broader deployment.



## Use of AI Statement

Generative AI tools were used sparingly to assist with requirement triage, copy
editing, and light code review. All critical architecture decisions, core
business logic, and the final published code were designed, implemented, and
verified by the project team, who retain full responsibility for the output. AI
acts solely as an efficiency aid and does not replace human judgement.


