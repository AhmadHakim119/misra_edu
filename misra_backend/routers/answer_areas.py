from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Answer, AnswerSource, ProcessingJob, Submission, User, Question
from schemas.answer_area_input import AreaPreviewRequest, AreaConfirmRequest, AreaRegradeRequest
from services.auth_dependencies import require_instructor
from services.answer_area_service import (OPERATION, source_context, source_signature, document_hash,
    active_paper_job, latest_revision, confirm_area, answer_revisions)
from services.job_queue_service import create_processing_job,job_to_dict
from services.audit_service import record_audit_event

router=APIRouter(prefix='/api',tags=['answer areas'])


def owned_source(db,source_id,user):
    try:return source_context(db,source_id,user.institution_id)
    except ValueError:raise HTTPException(404,'Answer source not found') from None


def area_job(db,source,job_id,user):
    job=db.query(ProcessingJob).filter(ProcessingJob.id==job_id,
        ProcessingJob.institution_id==user.institution_id).first()
    if not job or (job.payload or {}).get('operation')!=OPERATION or job.payload.get('source_id')!=source.id:
        raise HTTPException(404,'Area preview not found')
    return job


@router.post('/answer-sources/{source_id}/area-preview',status_code=202)
def preview_area(source_id:str,payload:AreaPreviewRequest,db:Session=Depends(get_db),user:User=Depends(require_instructor)):
    source,answer,submission=owned_source(db,source_id,user)
    db.query(Submission).filter(Submission.id==submission.id).with_for_update().one()
    db.refresh(source,with_for_update=True)
    if payload.expected_text!=source.extracted_text:
        raise HTTPException(409,'The extraction changed. Reload before selecting an area.')
    running=active_paper_job(db,submission)
    if running:
        if ((running.payload or {}).get('operation')==OPERATION and running.payload.get('source_id')==source.id
                and running.payload.get('bounding_box')==payload.bounding_box.model_dump()):
            return {'job':job_to_dict(running)}
        raise HTTPException(409,'Wait for the current paper task to finish before reading an area.')
    try:sha=document_hash(submission)
    except OSError:raise HTTPException(404,'Original paper is unavailable') from None
    job,_=create_processing_job(db,institution_id=user.institution_id,requested_by=user.id,
        job_type='ocr_submission',submission_id=submission.id,progress_total=1,payload={
            'operation':OPERATION,'source_id':source.id,'page_index':source.page_index,
            'source_signature':source_signature(source),'document_sha256':sha,
            'base_revision_id':(latest_revision(db,source,user.institution_id,for_update=True) or {}).get('id'),
            'bounding_box':payload.bounding_box.model_dump()})
    return {'job':job_to_dict(job)}


@router.get('/answer-sources/{source_id}/area-preview/{job_id}')
def get_area_preview(source_id:str,job_id:str,db:Session=Depends(get_db),user:User=Depends(require_instructor)):
    source,_,submission=owned_source(db,source_id,user)
    job=area_job(db,source,job_id,user)
    return {'job':job_to_dict(job),'source_id':source.id,'page_index':source.page_index,
        'bounding_box':job.payload['bounding_box'],
        'preview':job.payload.get('area_preview') if job.status=='completed' else None,
        'expected_revision_id':job.payload.get('base_revision_id'),
        'confirmed':bool(job.payload.get('area_confirmation'))}


@router.post('/answer-sources/{source_id}/area-preview/{job_id}/confirm')
def confirm_source_area(source_id:str,job_id:str,payload:AreaConfirmRequest,db:Session=Depends(get_db),user:User=Depends(require_instructor)):
    source,answer,submission=owned_source(db,source_id,user)
    db.query(Submission).filter(Submission.id==submission.id).with_for_update().one()
    db.refresh(source,with_for_update=True)
    job=area_job(db,source,job_id,user)
    if active_paper_job(db,submission):
        raise HTTPException(409,'Wait for the current paper task to finish before saving this correction.')
    try:revision=confirm_area(db,source,submission,job,payload,user)
    except (ValueError,OSError) as error:raise HTTPException(409,str(error)) from error
    record_audit_event(db,institution_id=user.institution_id,actor_id=user.id,
        action='answer_area_confirmed',entity_type='answer',entity_id=answer.id,
        details={'revision_id':revision['id'],'page_index':source.page_index,'prior_grades_retained':True})
    db.commit()
    return {'revision':revision,'answer_id':answer.id,'requires_regrade':answer.score is not None}


@router.post('/answers/{answer_id}/regrade-corrected',status_code=202)
def regrade_area_answer(answer_id:str,payload:AreaRegradeRequest,db:Session=Depends(get_db),user:User=Depends(require_instructor)):
    from routers.grading import _require_verified_mapping
    from services.grading_scope_service import is_external_question
    answer=db.query(Answer).filter(Answer.id==answer_id,Answer.institution_id==user.institution_id).first()
    if not answer:raise HTTPException(404,'Answer not found')
    submission=db.query(Submission).filter(Submission.id==answer.submission_id,
        Submission.institution_id==user.institution_id).with_for_update().one()
    db.refresh(answer,with_for_update=True)
    previous=db.query(ProcessingJob).filter(ProcessingJob.institution_id==user.institution_id,
        ProcessingJob.submission_id==submission.id,ProcessingJob.payload['request_id'].as_string()==str(payload.request_id)).with_for_update().first()
    if previous:
        prior=previous.payload or {}
        if prior.get('operation')!='regrade_corrected_answer' or prior.get('answer_id')!=answer.id or prior.get('expected_run_id')!=payload.expected_run_id or sorted(prior.get('revision_ids',[]))!=sorted(payload.revision_ids):
            raise HTTPException(409,'This request identifier belongs to a different grading request.')
        return {'job':job_to_dict(previous),'answer_id':answer.id}
    if active_paper_job(db,submission):raise HTTPException(409,'Wait for the current paper task to finish.')
    if (answer.grading_raw_response or {}).get('grading_run_id')!=payload.expected_run_id:
        raise HTTPException(409,'A newer grade is available. Reload before regrading.')
    question=db.get(Question,answer.question_id)
    if not question or is_external_question(question):raise HTTPException(409,'This question is not assessed here.')
    sources=db.query(AnswerSource).filter(AnswerSource.answer_id==answer.id).order_by(AnswerSource.page_index,AnswerSource.segment_index).all()
    revisions=answer_revisions(db,answer,sources,for_update=True)
    if len(set(payload.revision_ids))!=len(payload.revision_ids) or sorted(payload.revision_ids)!=sorted(r['id'] for r in revisions):
        raise HTTPException(409,'The confirmed extraction changed. Reload before regrading.')
    _require_verified_mapping(submission.id,db)
    job,_=create_processing_job(db,institution_id=user.institution_id,requested_by=user.id,
        job_type='grade_submission',submission_id=submission.id,progress_total=1,payload={
            'operation':'regrade_corrected_answer','answer_id':answer.id,'revision_ids':payload.revision_ids,
            'expected_run_id':payload.expected_run_id,'request_id':str(payload.request_id),'mode':'image_text'})
    record_audit_event(db,institution_id=user.institution_id,actor_id=user.id,
        action='corrected_answer_regrade_requested',entity_type='answer',entity_id=answer.id,
        details={'job_id':job.id,'revision_ids':payload.revision_ids})
    db.commit()
    return {'job':job_to_dict(job),'answer_id':answer.id}
