from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services.auth_dependencies import require_instructor
from services.audit_service import record_audit_event
from services.grade_export_service import (
    blackboard_omission_reasons,
    build_csv,
    build_export_preflight,
    build_grade_export,
    build_xlsx,
    safe_filename,
)


router = APIRouter(prefix="/api", tags=["exports"])


@router.get("/exams/{exam_id}/exports/preflight")
def export_grades_preflight(
    exam_id: str,
    identifier: str = Query(default="student_number", pattern="^(student_number|email)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    try:
        export = build_grade_export(exam_id, user.institution_id, db)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return build_export_preflight(export, identifier)


@router.get("/exams/{exam_id}/exports/grades.csv")
def export_grades_csv(
    exam_id: str,
    profile: str = Query(default="generic", pattern="^(generic|blackboard)$"),
    identifier: str = Query(default="student_number", pattern="^(student_number|email)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    try:
        export = build_grade_export(exam_id, user.institution_id, db)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    content, omitted = build_csv(export, profile, identifier)
    reasons = blackboard_omission_reasons(export, identifier) if profile == "blackboard" else {}
    if profile == "blackboard" and omitted == len(export.rows) and export.rows:
        messages = []
        if reasons["missing_identifier"]:
            label = "email" if identifier == "email" else "student number / Blackboard username"
            messages.append(f"{reasons['missing_identifier']} missing {label}")
        if reasons["incomplete_grading"]:
            messages.append(f"{reasons['incomplete_grading']} incompletely graded")
        if reasons["needs_review"]:
            messages.append(f"{reasons['needs_review']} awaiting review")
        detail = "; ".join(messages) or "no rows are ready"
        raise HTTPException(
            status_code=409,
            detail=(
                f"No Blackboard rows can be exported yet: {detail}. "
                "Add the exact roster username/student number in the submission details, "
                "finish grading, and resolve any flagged answers."
            ),
        )
    suffix = "blackboard" if profile == "blackboard" else "gradebook"
    filename = f"{safe_filename(export.exam.title)}-{suffix}.csv"
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="grades_exported",
        entity_type="exam",
        entity_id=exam_id,
        details={"format": "csv", "profile": profile, "identifier": identifier, "row_count": len(export.rows) - omitted, "omitted_count": omitted},
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-MISRA-Omitted-Rows": str(omitted),
            "X-MISRA-Missing-Identifier": str(reasons.get("missing_identifier", 0)),
            "X-MISRA-Incomplete-Grading": str(reasons.get("incomplete_grading", 0)),
            "X-MISRA-Needs-Review": str(reasons.get("needs_review", 0)),
        },
    )


@router.get("/exams/{exam_id}/exports/grades.xlsx")
def export_grades_xlsx(
    exam_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_instructor),
):
    try:
        export = build_grade_export(exam_id, user.institution_id, db)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    filename = f"{safe_filename(export.exam.title)}-gradebook.xlsx"
    content = build_xlsx(export)
    record_audit_event(
        db,
        institution_id=user.institution_id,
        actor_id=user.id,
        action="grades_exported",
        entity_type="exam",
        entity_id=exam_id,
        details={"format": "xlsx", "profile": "instructor_report", "row_count": len(export.rows)},
    )
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
