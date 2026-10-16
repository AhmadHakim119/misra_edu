from pathlib import Path
import os

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from services.frontend_routes import mount_frontend
from dotenv import load_dotenv
from database import engine, Base
import models
from routers import admin_operations, admin_users, answer_keys, auth, batches, evaluation, exams, exports, grading, grading_policies, identity_routes, instructor_preferences, jobs, ocr, questions, results, review_resolution, rubric_resolution, rubric_suggestions, rubric_versions
from services.gemini_client import DEFAULT_MODEL
from services.auth_dependencies import require_instructor
from services.job_queue_service import redis_connection
from services.build_info import build_info
from routers import exam_setup
from routers import course_materials
from routers import material_library

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
    expose_headers=["Content-Disposition", "X-MISRA-Omitted-Rows"],
)


@app.middleware("http")
async def prevent_sensitive_page_caching(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/api/", "/app/", "/legacy/", "/js/")):
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
app.include_router(answer_keys.router, dependencies=protected)
app.include_router(instructor_preferences.router, dependencies=protected)
app.include_router(exports.router, dependencies=protected)
app.include_router(jobs.router, dependencies=protected)
app.include_router(exam_setup.router, dependencies=protected)
app.include_router(course_materials.router, dependencies=protected)
app.include_router(material_library.router, dependencies=protected)

@app.get("/")
def read_root():
    return FileResponse(Path(__file__).resolve().parent.parent/'misra-frontend'/'app'/'landing.html')

@app.get("/api/health")
def health():
    try:
        queue_online = bool(redis_connection().ping())
    except Exception:
        queue_online = False
    from services.inference_service import configuration
    return {
        "status": "online" if queue_online else "degraded",
        "model": DEFAULT_MODEL,
        "ocr_provider": configuration('ocr')['provider'],
        "grading_provider": configuration('grading')['provider'],
        "grading_model": configuration('grading')['model'],
        "queue": "online" if queue_online else "unavailable",
        "build": build_info(),
        'agents': {name:configuration(task) for name,task in [('extraction','ocr'),('assessment','grading'),('verification','verification')]},
        'verification_enabled': os.getenv('VERIFICATION_ENABLED','true').lower() == 'true',
    }


frontend_dir = Path(__file__).resolve().parent.parent / "misra-frontend"
if frontend_dir.exists():
    mount_frontend(app,frontend_dir)
