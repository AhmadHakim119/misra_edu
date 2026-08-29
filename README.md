# MISRA-EDU

MISRA-EDU is an instructor-facing assessment workflow for secure paper upload,
OCR extraction, rubric-based AI grading, multimodal evidence review, instructor
overrides, grade export, and AI-instructor agreement evaluation.

MISRA-EDU is currently a local thesis prototype. It is not yet intended for
public internet deployment or use as an official institutional gradebook.

## Core capabilities

- Course and assessment creation
- Versioned AI-assisted rubrics and configurable grading approaches
- Secure individual and batch paper uploads
- OCR extraction, question mapping, and page-level source tracking
- Manual correction and recovery of OCR mappings
- Text-only, image-plus-text, and adaptive grading
- Instructor review, approval, and score overrides
- Persistent grading-run and review-label history
- Confidence-based review routing and agreement evaluation
- Blackboard-compatible CSV, generic CSV, and detailed Excel exports
- Instructor authentication, password recovery, and administration
- Institution-scoped audit records
- Redis-backed jobs, progress, retries, and orphan recovery

## Active application

- `misra_backend/` - FastAPI, SQLAlchemy, MariaDB/MySQL, OCR, Gemini grading,
  authentication, exports, background jobs, and evaluation
- `misra-frontend/` - static HTML, CSS, and JavaScript instructor workspace
- `database/schema.sql` - complete database schema for fresh installations
- `docs/` - detailed system and architecture documentation

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
```

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

At the current milestone, the suite contains 75 passing tests covering
authentication, account management, institution authorization, secure uploads,
submission deletion, OCR evidence, extraction review, rubric behavior, visual
routing, exports, Redis/RQ jobs, retry idempotency, orphan recovery, and admin
records.

## Documentation

- [Complete MISRA-EDU System Guide](docs/MISRA_EDU_Complete_System_Guide.docx)
- [Redis, RQ, and Admin Operations Explained](docs/MISRA_EDU_Redis_RQ_Admin_Operations_Explained.docx)

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
3. Add questions and draft/approve versioned rubrics in Rubric Studio.
4. Select the grading approach and evidence-routing policy.
5. Upload one paper or a batch and monitor OCR progress.
6. Verify student identity, OCR mapping, and source pages.
7. Recover, move, or remove incorrectly mapped segments when needed.
8. Grade with adaptive routing.
9. Resolve flagged answers and record instructor labels.
10. Inspect agreement metrics on the Evaluation page.
11. Export Blackboard CSV, generic CSV, or a detailed Excel report.

Seed scripts are development fixtures only. A normal assessment should not
require a seed script.

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
