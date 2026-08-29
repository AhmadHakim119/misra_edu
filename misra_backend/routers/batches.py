from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Batch, Submission, User
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.job_queue_service import create_processing_job, job_to_dict

router = APIRouter(prefix="/api", tags=["batches"])

@router.get("/batches/{batch_id}")
async def get_batch_status(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    batch = db.query(Batch).filter(
        Batch.id == batch_id,
        Batch.institution_id == user.institution_id,
    ).first()
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

@router.post("/batches/{batch_id}/retry")
async def retry_failed_submissions(
    batch_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    batch = db.query(Batch).filter(
        Batch.id == batch_id,
        Batch.institution_id == user.institution_id,
    ).first()
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

    job, created = create_processing_job(
        db,
        institution_id=batch.institution_id,
        requested_by=user.id,
        job_type="ocr_batch",
        batch_id=batch.id,
        progress_total=len(submission_ids),
        payload={"submission_ids": submission_ids},
    )

    if created:
        record_audit_event(
            db,
            institution_id=batch.institution_id,
            actor_id=user.id,
            action="batch_retry_queued",
            entity_type="batch",
            entity_id=batch.id,
            details={"job_id": job.id, "submission_count": len(submission_ids)},
        )
        db.commit()

    return {
        "message": "Retry queued",
        "retry_count": len(submission_ids),
        "job": job_to_dict(job),
    }
