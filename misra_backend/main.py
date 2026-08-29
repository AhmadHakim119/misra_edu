from pathlib import Path
import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from database import engine, Base
import models
from routers import admin_operations, admin_users, auth, batches, evaluation, exams, exports, grading, grading_policies, identity_routes, jobs, ocr, questions, results, review_resolution, rubric_resolution, rubric_suggestions, rubric_versions
from services.gemini_client import DEFAULT_MODEL
from services.auth_dependencies import require_instructor
from services.job_queue_service import redis_connection

load_dotenv()

app = FastAPI(title="MISRA-EDU API")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("APP_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prevent_sensitive_page_caching(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/app/pages/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

app.include_router(auth.router)
app.include_router(admin_users.router)
app.include_router(admin_operations.router)
protected = [Depends(require_instructor)]
app.include_router(ocr.router, dependencies=protected)
app.include_router(grading.router, dependencies=protected)
app.include_router(exams.router, dependencies=protected)
app.include_router(results.router, dependencies=protected)
app.include_router(questions.router, dependencies=protected)
app.include_router(rubric_suggestions.router, dependencies=protected)
app.include_router(batches.router, dependencies=protected)
app.include_router(rubric_resolution.router, dependencies=protected)
app.include_router(identity_routes.router, dependencies=protected)
app.include_router(review_resolution.router, dependencies=protected)
app.include_router(grading_policies.router, dependencies=protected)
app.include_router(evaluation.router, dependencies=protected)
app.include_router(rubric_versions.router, dependencies=protected)
app.include_router(exports.router, dependencies=protected)
app.include_router(jobs.router, dependencies=protected)

@app.get("/")
def read_root():
    return {"status": "MISRA Engine Online"}

@app.get("/api/health")
def health():
    try:
        queue_online = bool(redis_connection().ping())
    except Exception:
        queue_online = False
    return {
        "status": "online" if queue_online else "degraded",
        "model": DEFAULT_MODEL,
        "queue": "online" if queue_online else "unavailable",
    }


frontend_dir = Path(__file__).resolve().parent.parent / "misra-frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")
