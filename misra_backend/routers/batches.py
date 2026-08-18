from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks
from database import SessionLocal
from services.ocr_service import process_submission
from database import get_db
from models import Batch, Submission

router = APIRouter(prefix="/api", tags=["batches"])

@router.get("/batches/{batch_id}")
async def get_batch_status(batch_id: str, db: Session = Depends(get_db)):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    submissions = (
        db.query(Submission)
        .filter(Submission.batch_id == batch_id)
        .order_by(Submission.uploaded_at)
        .all()
    )

    return {
        "batch": batch,
        "submissions": submissions
    }

def _retry_failed_in_background(batch_id: str, submission_ids: list[str]):
    db = SessionLocal()
    try:
        batch = db.query(Batch).filter(Batch.id == batch_id).first()
        for submission_id in submission_ids:
            try:
                process_submission(submission_id, db)
                batch.completed_count += 1
                batch.failed_count -= 1
            except Exception:
                pass  # still failed; counts already reflect this from the original run
            db.commit()

        batch.status = "completed" if batch.failed_count == 0 else "completed_with_errors"
        db.commit()
    finally:
        db.close()


@router.post("/batches/{batch_id}/retry")
async def retry_failed_submissions(
    batch_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    batch = db.query(Batch).filter(Batch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

    failed_submissions = (
        db.query(Submission)
        .filter(Submission.batch_id == batch_id, Submission.status == "error")
        .all()
    )

    if not failed_submissions:
        return {"message": "No failed submissions to retry", "retry_count": 0}

    submission_ids = [s.id for s in failed_submissions]
    for s in failed_submissions:
        s.status = "uploaded"
        s.error_message = None

    batch.status = "processing"
    db.commit()

    background_tasks.add_task(_retry_failed_in_background, batch_id, submission_ids)

    return {"message": "Retry started", "retry_count": len(submission_ids)}