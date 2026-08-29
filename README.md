# MISRA-EDU

MISRA-EDU is an instructor-facing assessment workflow for OCR extraction,
rubric-based AI grading, multimodal evidence review, human overrides, and
AI-instructor agreement evaluation.

The active application is:

- `misra_backend/`: FastAPI, SQLAlchemy, MariaDB/MySQL, OCR and Gemini grading
- `misra-frontend/`: static HTML/CSS/JavaScript instructor workspace

`misra_ui/` is legacy reference material and is not the active frontend.

## Prerequisites

- Python 3.11 or newer
- MariaDB 10.6+ or MySQL 8+
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

For a **new empty database**, create and verify the current model schema:

```powershell
Set-Location .\misra_backend
python .\scripts\bootstrap_database.py --create
```

For an existing database created before account administration was added, back
it up and run the explicit additive upgrade once:

```powershell
Set-Location .\misra_backend
python .\scripts\upgrade_account_management.py
python .\scripts\upgrade_processing_jobs.py
```

For a new database, import the complete schema:

```powershell
mysql -u root -p -e "CREATE DATABASE misra_edu CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
Get-Content .\database\schema.sql | mysql -u root -p misra_edu
```

Fresh installations use the complete schema or current SQLAlchemy models.

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

1. Create a course and assessment in the frontend.
2. Add questions and draft/approve versioned rubrics in Rubric Studio.
3. Upload one paper or a batch.
4. Review OCR mapping and page sources; recover or move segments when needed.
5. Grade with adaptive routing.
6. Resolve flagged answers and record instructor labels.
7. Inspect agreement metrics on the Evaluation page.

Seed scripts are development fixtures only. A normal assessment should not
require a seed script.

## Known deployment boundary

This repository currently represents a local thesis prototype, not an
internet-safe production deployment. Signed instructor sessions,
institution-scoped extraction authorization, and validated upload limits are
implemented. Password change/recovery, global session invalidation,
administrator-provisioned instructor accounts, and database-backed recovery
throttling are also implemented. Durable Redis-backed OCR and grading jobs are
implemented for the local prototype. Login throttling, restrictive production
CORS, managed encrypted file storage, retention automation, and deployment
monitoring remain before public use.
