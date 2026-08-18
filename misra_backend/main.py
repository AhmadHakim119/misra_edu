from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from database import engine, Base
import models
from routers import ocr, grading, exams, results, questions, rubric_suggestions, batches, rubric_resolution, identity_routes, review_resolution, grading_policies, evaluation, rubric_versions
from services.gemini_client import DEFAULT_MODEL

load_dotenv()

app = FastAPI(title="MISRA-EDU API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ocr.router)
app.include_router(grading.router)
app.include_router(exams.router)
app.include_router(results.router)
app.include_router(questions.router)
app.include_router(rubric_suggestions.router)
app.include_router(batches.router)
app.include_router(rubric_resolution.router)
app.include_router(identity_routes.router)
app.include_router(review_resolution.router)
app.include_router(grading_policies.router)
app.include_router(evaluation.router)
app.include_router(rubric_versions.router)

@app.get("/")
def read_root():
    return {"status": "MISRA Engine Online"}

@app.get("/api/health")
def health():
    return {"status": "online", "model": DEFAULT_MODEL}


frontend_dir = Path(__file__).resolve().parent.parent / "misra-frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")
