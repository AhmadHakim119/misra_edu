"""Remove an unused draft question without touching published or student records."""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models import (Answer, AnswerKeyVersion, Exam, GradingRun, ProcessingJob, Question,
                    QuestionGradingPolicy, QuestionMaterialScopeVersion, RubricSuggestion,
                    RubricVersion, Submission)
from services.audit_service import record_audit_event


def delete_draft_question(db, user, question_id):
    # The same lock order as whole-guide approval: exam, question, definitions.
    exam_id = db.query(Question.exam_id).filter(Question.id == question_id,
        Question.institution_id == user.institution_id).scalar()
    if exam_id is None:
        raise HTTPException(404, 'Question not found')
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.institution_id == user.institution_id).with_for_update().first()
    question = db.query(Question).filter(Question.id == question_id,
        Question.institution_id == user.institution_id).with_for_update().populate_existing().first()
    if not exam or not question:
        raise HTTPException(404, 'Question not found')
    versions = db.query(RubricVersion).filter_by(question_id=question.id).with_for_update().all()
    keys = db.query(AnswerKeyVersion).filter_by(question_id=question.id).with_for_update().all()
    scopes = db.query(QuestionMaterialScopeVersion).filter_by(question_id=question.id).with_for_update().all()
    if not versions or question.active_rubric_version_id or any(v.status != 'draft' or v.approved_at or v.approved_by for v in [*versions, *keys, *scopes]):
        raise HTTPException(409, 'Only unused draft questions can be deleted. This question has approved or historical definitions.')
    if db.query(Submission.id).filter_by(exam_id=exam.id).first() or db.query(Answer.id).filter_by(question_id=question.id).first():
        raise HTTPException(409, 'Papers already exist for this assessment. This question cannot be deleted.')
    if db.query(GradingRun.id).filter(GradingRun.rubric_version_id.in_([v.id for v in versions])).first() or db.query(RubricSuggestion.id).filter_by(question_id=question.id).first():
        raise HTTPException(409, 'This question has saved AI history and cannot be deleted.')
    active_jobs = db.query(ProcessingJob).filter(ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.status.in_(['queued', 'processing', 'retrying'])).all()
    if any((job.payload or {}).get('exam_id') == exam.id or (job.payload or {}).get('question_id') == question.id for job in active_jobs):
        raise HTTPException(409, 'This assessment is still being processed. Wait for its tasks to finish before deleting a question.')
    try:
        # All version rows have been checked; never delete source material or job outputs.
        for model in [QuestionMaterialScopeVersion, AnswerKeyVersion, QuestionGradingPolicy, RubricVersion]:
            db.query(model).filter_by(question_id=question.id).delete(synchronize_session=False)
        db.delete(question)
        db.flush()
        record_audit_event(db, institution_id=user.institution_id, actor_id=user.id,
            action='draft_question_deleted', entity_type='question', entity_id=question_id,
            details={'exam_id':exam.id, 'question_number':question.question_number,
                     'draft_rubric_count':len(versions), 'draft_key_count':len(keys), 'draft_scope_count':len(scopes)})
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, 'This question is referenced by saved work. Reload the guide; it was not deleted.') from error
