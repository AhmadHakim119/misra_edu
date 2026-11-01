"""Explicit exam-wide removal/restoration; preserve questions and grading history.

Lifecycle events use existing version JSON and immutable version rows. They do
not approve pending marking/source drafts or delete any student record.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func
from models import Answer, Exam, ProcessingJob, Question, RubricVersion, Submission
from services.audit_service import record_audit_event
from services.grading_scope_service import active_questions, is_removed_question


def _owned(db, user, question_id, *, lock=False):
    question = db.query(Question).filter(Question.id == question_id,
        Question.institution_id == user.institution_id).first()
    if not question:
        raise HTTPException(404, 'Question not found')
    exam_query = db.query(Exam).filter(Exam.id == question.exam_id, Exam.institution_id == user.institution_id)
    exam = (exam_query.with_for_update() if lock else exam_query).first()
    if not exam:
        raise HTTPException(404, 'Assessment not found')
    if lock:
        question = db.query(Question).filter(Question.id == question_id).with_for_update().populate_existing().one()
    return exam, question


def preview_question_change(db, user, question_id, action):
    if action not in ('remove', 'restore'):
        raise HTTPException(422, 'Choose remove or restore.')
    exam, question = _owned(db, user, question_id)
    removed = is_removed_question(question)
    if removed != (action == 'restore'):
        raise HTTPException(409, 'Question state changed. Refresh Extraction before continuing.')
    all_questions = db.query(Question).filter(Question.exam_id == exam.id).order_by(Question.order_index, Question.id).populate_existing().all()
    selected = [q for q in active_questions(all_questions) if q.id != question.id]
    if action == 'restore':
        if any(q.question_number.strip().casefold() == question.question_number.strip().casefold() for q in selected):
            raise HTTPException(409, 'Another active question uses this number. Correct that conflict before restoring.')
        selected.append(question)
    papers = db.query(Submission).filter(Submission.exam_id == exam.id).all()
    paper_ids, batch_ids = {p.id for p in papers}, {p.batch_id for p in papers if p.batch_id}
    jobs = db.query(ProcessingJob).filter(ProcessingJob.institution_id == user.institution_id,
        ProcessingJob.status.in_(('queued', 'processing', 'retrying'))).all()
    if any(j.submission_id in paper_ids or j.batch_id in batch_ids or (j.payload or {}).get('exam_id') == exam.id
           or (j.payload or {}).get('question_id') == question.id for j in jobs):
        raise HTTPException(409, 'Assessment processing is active. Wait for its saved tasks to finish before changing the question list.')
    from services.assessment_guide_service import review_guide
    guide = review_guide(db, exam)
    answers = db.query(Answer).filter(Answer.question_id == question.id).all()
    manifest = dict(exam_id=exam.id, question_id=question.id, action=action,
        current_guide_token=guide['review_token'], definition=question.rubric_json,
        papers=sorted(paper_ids), answers=[(a.id, str(a.score), str(a.teacher_override_score), str(a.reviewed_at)) for a in sorted(answers,key=lambda a:a.id)])
    token = hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    return dict(exam_id=exam.id, question_id=question.id, question_number=question.question_number,
        question_text=question.question_text, action=action, review_token=token, paper_count=len(papers),
        recorded_answer_count=sum(a.score is not None or a.teacher_override_score is not None for a in answers),
        previous_total_marks=round(sum(float(q.max_score) for q in active_questions(all_questions)),2),
        revised_total_marks=round(sum(float(q.max_score) for q in selected),2),
        remaining_questions=[dict(id=q.id,number=q.question_number,max_score=float(q.max_score)) for q in selected])


def change_question_state(db, user, question_id, request):
    if not request.confirm_reviewed:
        raise HTTPException(422, 'Confirm the effect on all papers before changing the exam question list.')
    exam, question = _owned(db, user, question_id, lock=True)
    preview = preview_question_change(db, user, question_id, request.action)
    if preview['review_token'] != request.review_token:
        raise HTTPException(409, 'The assessment changed after this preview. Refresh the removal preview; nothing was changed.')
    versions = db.query(RubricVersion).filter_by(question_id=question.id).with_for_update().all()
    old = next((v for v in versions if v.id == question.active_rubric_version_id), None)
    value = deepcopy(question.rubric_json or {})
    lifecycle = value.pop('question_lifecycle', {})
    number = max((v.version_number for v in versions), default=0) + 1
    if request.action == 'remove':
        # The new tombstone also retains legacy definitions that had no version.
        value['question_lifecycle'] = dict(status='removed', previous_version_id=question.active_rubric_version_id,
            previous_authority='approved' if old and old.status == 'approved' else 'unapproved' if versions else 'legacy',
            actor_id=user.id, changed_at=datetime.now(timezone.utc).isoformat(), review_token=request.review_token)
        if old and old.status == 'approved':
            old.status = 'superseded'
        version_status = 'removed'
    else:
        version_status = 'approved' if lifecycle.get('previous_authority') in ('approved','legacy') else 'draft'
    version = RubricVersion(question_id=question.id,version_number=number,schema_version=2,
        rubric_json=value,grading_approach=(value.get('policy') or {}).get('grading_approach','balanced'),
        source='manual',status=version_status,created_by=user.id,
        approved_by=user.id if version_status != 'draft' else None,
        approved_at=func.now() if version_status != 'draft' else None,
        change_summary=f'Question {request.action}d from Extraction; original papers, definitions and results retained.')
    db.add(version);db.flush()
    question.rubric_json=deepcopy(value)
    question.active_rubric_version_id=version.id if version_status == 'approved' else None
    # Revised totals require review; no mark, override or immutable run is changed.
    from services.rubric_version_service import require_guide_review
    for remaining in db.query(Question).filter(Question.exam_id == exam.id).all():
        require_guide_review(remaining,db,active_version_id=remaining.active_rubric_version_id,
            reason='The exam question list changed. Review the revised total and saved proposal before finalizing again.')
    record_audit_event(db,institution_id=user.institution_id,actor_id=user.id,
        action='exam_question_'+request.action,entity_type='question',entity_id=question.id,
        details=dict(exam_id=exam.id,question_number=question.question_number,version_id=version.id,
            previous_total_marks=preview['previous_total_marks'],revised_total_marks=preview['revised_total_marks'],paper_count=preview['paper_count']))
    db.commit()
    return dict(exam_id=exam.id,question_id=question.id,action=request.action,
        message='Question removed from the exam. Original papers and saved history are retained.' if request.action == 'remove' else 'Question restored. Review the saved marking guide and existing grades before continuing.')
