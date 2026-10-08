# MISRA-EDU

MISRA-EDU is an instructor-facing assessment workflow for secure paper upload,
OCR extraction, rubric-based AI grading, multimodal evidence review, instructor
overrides, grade export, and AI-instructor agreement evaluation.

MISRA-EDU is currently a local thesis prototype. It is not yet intended for
public internet deployment or use as an official institutional gradebook.

## Core capabilities

- Course and assessment creation
- Versioned AI-assisted rubrics, answer keys, and configurable grading policies
- Secure individual and batch paper uploads
- OCR extraction, question mapping, and page-level source tracking
- Manual correction and recovery of OCR mappings
- Text-only, image-plus-text, and adaptive grading
- Instructor review, approval, and score overrides
- Evidence-cited criterion results and immutable grading-package snapshots
- Persistent grading-run history and structured instructor review reasons
- Optional versioned instructor preference profiles and non-binding suggestions
- Confidence-based review routing and agreement evaluation
- Blackboard-compatible CSV, generic CSV, and detailed Excel exports
- Instructor authentication, password recovery, and administration
- Institution-scoped audit records
- Redis-backed jobs, progress, retries, and orphan recovery
- Responsive instructor workspace with keyboard support and light/dark themes
- Assessment duplication with rubric and grading-policy reuse

## Active application

- `misra_backend/` - FastAPI, SQLAlchemy, MariaDB/MySQL, OCR, Gemini grading,
  authentication, exports, background jobs, and evaluation
- `misra-frontend/` - static HTML, CSS, and JavaScript instructor workspace
- `database/schema.sql` - complete database schema for fresh installations
- `docs/` - public technical notes; private student-work reports are excluded

`misra_ui/` is legacy reference material and is not part of the active
application.

## Architecture overview

```text
Instructor browser
        |
        v
MISRA frontend
        |
        v
FastAPI backend
   |         |
   |         +---- Redis Queue ---- RQ worker
   |                              |       |
   v                              v       v
MariaDB/MySQL                  OCR jobs  Grading jobs
                                      |
                                      v
                                  Gemini API
```

MariaDB is the authoritative store for assessments, submissions, answers,
rubrics, grading runs, review labels, processing jobs, users, and audit events.
Redis coordinates background work; it does not replace MariaDB or hold the
authoritative assessment results.

## Prerequisites

- Python 3.11 or newer
- MariaDB 10.4+ or MySQL 8+
- Redis 5+ (or a Redis-compatible Windows service such as Memurai)
- Poppler available on `PATH` (`pdftoppm -v` must work)
- A Gemini API key

On Windows, install a maintained Poppler build and add its `Library/bin` or
`bin` directory to the system `PATH`. Restart PowerShell after changing `PATH`.

## First-time setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\misra_backend\requirements.txt
Copy-Item .\.env.example .\misra_backend\.env
```

Edit `misra_backend/.env` and supply the real database URL, Gemini key, and a
random recovery and authentication signing key. Never put secrets in
`.env.example`. The example also documents configurable upload boundaries:
25 MB per file, 100 MB per batch request, 25 files per batch, 50 pages per PDF,
and 40 million pixels per image.

Create an empty database and a least-privilege local user. Example MariaDB SQL:

```sql
CREATE DATABASE misra_edu
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'misra_user'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES
  ON misra_edu.* TO 'misra_user'@'localhost';
FLUSH PRIVILEGES;
```

For a fresh database, use **one** of the following methods. Do not run both
against the same new database.

### Option A - Import the complete SQL schema

Run from the repository root:

```powershell
Get-Content .\database\schema.sql | mysql -u root -p misra_edu
```

### Option B - Create tables from the SQLAlchemy models

Ensure `misra_backend/.env` points to the new empty database, then run:

```powershell
Set-Location .\misra_backend
python .\scripts\bootstrap_database.py --create
```

Expected result:

```text
Database connection successful. The current model schema is present.
```

### Existing database upgrades

For an existing database created before account administration was added, back
it up and run the explicit additive upgrade once:

```powershell
Set-Location .\misra_backend
python .\scripts\upgrade_account_management.py
python .\scripts\upgrade_processing_jobs.py
python .\scripts\upgrade_grading_foundations.py
```

The grading-foundation coordinator adds exam-setup jobs, versioned answer keys,
instructor preference versions, structured review reasons, and immutable review
revision links. It is idempotent and does not regrade or rewrite existing answers. Restart both
Uvicorn and the RQ worker after upgrading.

## Run the application

OCR and whole-submission grading use Redis Queue (RQ). MariaDB is the durable
source of job status and Redis carries only processing-job IDs. On Windows,
Redis documents Memurai or WSL as supported local options. Configure the local
service on port `6379`, then verify it from `misra_backend/`:

```powershell
python -c "from services.job_queue_service import redis_connection; print(redis_connection().ping())"
```

The expected output is `True`. Run the application from `misra_backend/` in two
separate PowerShell terminals so uploaded-file paths resolve consistently.

Terminal 1 — API and frontend:

```powershell
uvicorn main:app --reload
```

Terminal 2 — OCR and grading worker:

```powershell
python .\worker.py
```

The local Windows worker uses RQ's documented `SimpleWorker` pattern with a
timer-based timeout; Linux deployment uses the standard process-isolated
worker. Keep both terminals open. Upload endpoints return immediately with a
submission and job ID; the frontend reads persisted `queued`, `processing`,
`retrying`, `completed`, and `failed` states and offers a safe retry when the
attempt limit is reached. At worker startup, MISRA reconciles stale database
jobs against Redis. Missing jobs are requeued only when their retry budget
allows it; live RQ jobs are left untouched. Run the reconciliation without
starting a worker with `python .\worker.py --recover-only`.

Open:

- Instructor workspace: <http://127.0.0.1:8000/app/pages/dashboard.html>
- API documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/api/health>
- Admin operations: <http://127.0.0.1:8000/app/pages/admin-operations.html>

The frontend has no build step. It is served by FastAPI from
`misra-frontend/`. Instructor sessions use signed, HTTP-only cookies with CSRF
protection. The current prototype shares an institution's assessment workspace
between its authenticated instructors; course/section-level roles are a future
multi-instructor administration feature. Set `COOKIE_SECURE=true` when
deploying behind HTTPS.

Institution administrators can inspect institution-scoped activity, security
events, background jobs, and service health from Admin operations. Audit
exports deliberately exclude passwords, reset tokens, cookies, API keys, and
paper/OCR content. Configure `AUDIT_RETENTION_DAYS` (180 by default) and
`JOB_ORPHAN_AFTER_SECONDS` (1800 by default) in `misra_backend/.env` when a
deployment needs different policies.

Instructor accounts are provisioned by an institution administrator rather
than through public signup. The first local administrator can be provisioned
or updated with:

```powershell
python .\scripts\create_instructor.py `
  --institution-id "YOUR_INSTITUTION_ID" `
  --email "admin@example.edu" `
  --name "Institution Admin" `
  --role admin
```

Password recovery defaults to `PASSWORD_RESET_DELIVERY=console` for local
development; the one-use reset link appears in the Uvicorn terminal. Configure
the documented SMTP variables and set the mode to `smtp` before deployment.

## Run tests

From `misra_backend/`:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Tests use isolated in-memory databases and mocked model calls where applicable.
They must not depend on files under `storage/uploads/`.

At the current milestone, the suite contains 77 passing backend tests covering
authentication, account management, institution authorization, secure uploads,
submission deletion, OCR evidence, extraction review, rubric behavior, visual
routing, exports, Redis/RQ jobs, retry idempotency, orphan recovery, and admin
records.

Frontend interaction tests use Playwright. From the repository root:

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
```

The suite exercises desktop and mobile navigation, keyboard access, persisted
theme selection, live records, and actionable request-failure states with
mocked API responses.

## Documentation

Locally generated Word guides and evaluation/research reports are private and
are not distributed with the repository: they may include student identities,
paper images or individual grades. Papers and exported gradebooks are ignored
by default. Use synthetic records in public tests and screenshots.

Ignore rules do not remove previously committed content from Git history.
Any historical exposure requires a separate, coordinated history-cleanup step.

## Privacy and repository safety

Uploaded papers may contain names, student numbers, handwriting, and grades.
The entire `misra_backend/storage/uploads/` directory is ignored except for its
empty `.gitkeep` placeholder. Debug paper copies and generated OCR images are
also ignored.

Before every commit, run:

```powershell
git status --short
git ls-files | Select-String -Pattern 'storage/uploads|\.(pdf|png|jpg|jpeg)$'
```

Do not commit a paper merely because it is called an answer key: verify that it
contains no student identity or handwritten work first. If sensitive files were
committed previously, deleting them in a later commit does **not** remove them
from Git history. Purging history is a separate destructive operation that
requires coordination with every clone and remote.

## Normal instructor workflow

1. Sign in with an administrator-provisioned account.
2. Create a course and assessment in the frontend.
3. In Rubric Studio, upload a blank exam and optional answer key to suggest questions, or add questions manually. Review the extracted text, numbering and marks; confirm the import to create **draft** rubrics, then edit and approve them.
4. Select the grading approach and evidence-routing policy.
5. Once every question has an approved rubric, upload student answers (one paper or a batch) and monitor OCR progress.
6. Verify student identity, OCR mapping, and source pages.
7. Recover, move, or remove incorrectly mapped segments when needed.
8. Grade with adaptive routing.
9. Resolve flagged answers and record instructor labels.
10. Inspect agreement metrics on the Evaluation page.
11. Export Blackboard CSV, generic CSV, or a detailed Excel report.

Seed scripts are development fixtures only. A normal assessment should not
require a seed script.

Exam/key uploads use separate `exam_setup` processing jobs and never create student
submissions or answers. The worker must be restarted after upgrading. Setup drafts
can be reopened from Rubric Studio after leaving the page; unsaved edits in the
question-review form are not persisted until confirmation. Review image-dependent
questions against the original document and verify any shared diagram/table context.
Imported marking guides are initial suggestions; refine their criteria before approval.
Setup documents remain in private local upload storage until explicitly removed;
automatic retention for these documents is not yet implemented.

## Assessment workspace and setup checks

The Assessments page groups work by course, supports typo-tolerant local search,
and opens an assessment-specific workspace linking marking rules, student papers,
grades, and exports. Question-by-question setup checks show approved rubric
versions, evidence-routing settings, and reference-answer availability.

Deterministic checks block setup readiness when approved criteria have invalid
marks, duplicate identifiers, mismatched totals, or missing question text. Approved
rubric definitions are checked again when resolved for grading. A missing reference
answer is advisory: open-ended questions can be graded against sufficiently clear
criteria. Passing these checks does not establish that an AI grade is correct.
Legacy references remain supported. Rubric Studio also provides independent,
versioned answer keys: reference text, acceptable alternatives, and selected pages
from private PDF/image documents, or an explicit **No fixed answer** setting.
Drafts do not affect grading; approved versions are immutable. Reference uploads
do not create student submissions or call OCR. Each question supports up to five
reference documents and 20 selected pages in total.

For an existing database, the `upgrade_grading_foundations.py` command in the
setup section creates these additive tables and fields. Back up first, then
restart both Uvicorn and the RQ worker.

New grading runs save a question-linked grading package containing the approved
key, rubric and policy, student evidence, version identifiers and document hashes.
The policy is versioned within the rubric. Later edits do not rewrite saved runs;
older runs are not retroactively populated with packages. Grades exposes the saved
rules and run history. Criterion responses support evidence references, applied
policy fields and uncertainties; invalid references are rejected, while missing
citations or reported uncertainty require review. Valid citations do not by
themselves prove that a deduction is justified.

Explicit policy fields cover handwritten syntax, language quality and
error-carried-forward handling alongside the existing marking controls.
Deterministic consistency checks compare explicit question, key, rubric, and
routing fields. Structural conflicts stop grading before a provider call;
advisories cap confidence and require instructor review. These checks do not
claim to understand whether academic prose is semantically correct.

Settings provides optional, versioned instructor marking profiles. Scenario
answers create proposed rubric defaults, but approval never changes an
assessment. An instructor must explicitly copy an approved profile into an
editable Rubric Studio draft and approve that rubric separately. Review forms
record structured reasons such as valid alternatives, notation tolerance,
method credit, and carried-forward errors. After three distinct decisions of
one kind, MISRA may suggest a new profile rule. OCR/mapping failures, rubric
problems, and miscellaneous reasons are excluded from preference evidence, and
suggestions are never applied automatically.

Long-document semantic retrieval remains a future phase. No vector database is
required for the current exact question-linked references.

The pinned Fuse.js browser bundle and its license are committed locally; runtime
search does not contact a CDN or send assessment text to a search service. To
rebuild that bundle after dependency changes, run `npm ci` followed by
`npm run vendor:frontend` from the repository root. Normal use still requires no
frontend build step.

## Known deployment boundary

This repository currently represents a local thesis prototype, not an
internet-safe production deployment. Signed instructor sessions,
institution-scoped extraction authorization, and validated upload limits are
implemented. Password change/recovery, global session invalidation,
administrator-provisioned instructor accounts, and database-backed recovery
throttling are also implemented. Durable Redis-backed OCR and grading jobs are
implemented for the local prototype. The browser-origin allowlist is
configurable through `APP_ORIGINS`, but production CORS validation, login
throttling, HTTPS, managed encrypted file storage, retention automation,
centralized secrets, durable Redis monitoring, and deployment monitoring remain
before public use.

## Planned direction

MISRA may later expose a stable, versioned assessment-processing API for LMS
integration. The LMS would manage enrollment, assignments, student access, and
the official gradebook. MISRA would manage paper ingestion, OCR, question
mapping, rubric grading, multimodal review, instructor overrides, and
evaluation evidence.

Possible future integrations include LTI 1.3, Assignment and Grade Services,
Blackboard REST APIs, Canvas and Moodle adapters, signed completion webhooks,
external LMS identifiers, and idempotent API requests. A standalone student
portal is optional and should be developed only when MISRA must operate without
an LMS.
