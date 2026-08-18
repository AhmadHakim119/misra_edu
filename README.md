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
random recovery signing key. Never put secrets in `.env.example`.

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

## Create the database schema

For a new database, import the complete schema from the repository root:

```powershell
Get-Content .\database\schema.sql | mysql -u root -p misra_edu
```

Alternatively, create the current schema from the SQLAlchemy models:

```powershell
Set-Location .\misra_backend
python .\scripts\bootstrap_database.py --create
```

Use only one of these methods for a new database. The SQL file is recommended
when reproducing the exact submitted schema.

## Run the application

Run from `misra_backend/` so uploaded-file paths resolve consistently:

```powershell
Set-Location .\misra_backend
uvicorn main:app --reload
```

Open:

- Instructor workspace: <http://127.0.0.1:8000/app/pages/dashboard.html>
- API documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/api/health>

The frontend has no build step. It is served by FastAPI from
`misra-frontend/`. Authentication is not implemented yet, so the application
must remain on a trusted local machine until API authorization is added.

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
internet-safe production deployment. Authentication, authorization, upload
limits, restrictive CORS, durable background jobs, and managed encrypted file
storage must be completed before public deployment.
