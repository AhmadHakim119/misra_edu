"""Review exact saved foundations and publish an assessment in one transaction.

Versions remain question-scoped internally; no grading history is rewritten.
Material-page approval is deliberately excluded: unread pages cannot be trusted
merely because their assessment guide is published.
"""
import hashlib
import json

from sqlalchemy import inspect
from models import (Question, RubricVersion, AnswerKeyVersion, MaterialVersion, CourseMaterial, QuestionGradingPolicy,
                    QuestionMaterialScopeVersion, AssessmentMaterialScopeVersion)
from schemas.answer_keys import AnswerKeyDraftRequest
from schemas.course_materials import MaterialScopeRequest, AssessmentMaterialScopeRequest
from services.assessment_readiness_service import definition_errors
from services.rubric_version_service import approve_rubric_version, validate_rubric_v2
from services import answer_key_service as keys
from services import course_material_service as materials
from services import assessment_source_service as sources


def _selected(db, model, column, identifier):
    rows = db.query(model).filter(column == identifier).order_by(model.version_number.desc()).all()
    return next((v for v in rows if v.status == 'draft'), None) or next(
        (v for v in rows if v.status == 'approved'), None)


def _scope(scope):
    return None if scope is None else dict(id=scope.id, status=scope.status,
        version_number=scope.version_number, mode=scope.mode, bindings=scope.bindings,
        scope_sha256=scope.scope_sha256)


def _labels(db, scope, exam):
    if not scope:
        return []
    labels = []
    for binding in scope.bindings:
        found = db.query(MaterialVersion, CourseMaterial).join(CourseMaterial,
            CourseMaterial.id == MaterialVersion.material_id).filter(MaterialVersion.id == binding['version_id'],
            CourseMaterial.course_id == exam.course_id, CourseMaterial.institution_id == exam.institution_id).first()
        labels.append(dict(version_id=binding['version_id'], title=found[1].title if found else 'Unavailable reference',
            version_number=found[0].version_number if found else None, page_indices=binding['page_indices']))
    return labels


def review_guide(db, exam):
    for model in (RubricVersion, AnswerKeyVersion, QuestionMaterialScopeVersion, AssessmentMaterialScopeVersion):
        if not inspect(db.connection()).has_table(model.__tablename__):
            raise ValueError('Install the pending grading-foundation/source upgrades before reviewing the guide.')
    questions = db.query(Question).filter(Question.exam_id == exam.id,
        Question.institution_id == exam.institution_id).order_by(Question.order_index, Question.id).all()
    default = _selected(db, AssessmentMaterialScopeVersion, AssessmentMaterialScopeVersion.exam_id, exam.id)
    errors, warnings, rows = [], [], []
    if not questions:
        errors.append('Add at least one question and its marking criteria.')
    if default:
        try:
            if default.status == 'approved' and default.scope_sha256 != sources.assessment_scope_hash(default):
                raise ValueError('Approved source choices changed; create a new draft before approval.')
            materials.validate_exam_bindings(db, exam,
                AssessmentMaterialScopeRequest(mode=default.mode, bindings=default.bindings))
        except ValueError as error:
            errors.append('Assessment sources: ' + str(error))
    else:
        warnings.append('No assessment sources selected. Existing question references are retained.')
    for question in questions:
        version = _selected(db, RubricVersion, RubricVersion.question_id, question.id)
        rubric = version.rubric_json if version else question.rubric_json
        issues = definition_errors(question, rubric)
        if not version and db.query(RubricVersion).filter(RubricVersion.question_id == question.id).first():
            issues.append('No current rubric or draft is available; restore a valid marking definition.')
        if version and version.status == 'draft':
            try:
                validate_rubric_v2(rubric)
            except ValueError as error:
                issues.append(str(error))
        key = _selected(db, AnswerKeyVersion, AnswerKeyVersion.question_id, question.id)
        reference = dict(id=key.id, status=key.status, version_number=key.version_number,
            mode=key.mode, reference_text=key.reference_text, acceptable_answers=key.acceptable_answers,
            document_refs=key.document_refs, change_summary=key.change_summary) if key else dict(
            id=None, status='legacy', mode='reference' if (rubric or {}).get('reference_context') else 'no_fixed_answer',
            reference_text=(rubric or {}).get('reference_context') or '', acceptable_answers=(rubric or {}).get('acceptable_answers') or [], document_refs=[])
        try:
            if key:
                AnswerKeyDraftRequest(**{k:reference[k] for k in (
                    'mode','reference_text','acceptable_answers','document_refs','change_summary')})
                resolved = keys.resolve_document_refs(question, key.document_refs, db, verify_hash=key.status == 'approved')
                reference['document_refs'] = [{k:v for k,v in ref.items() if k != 'path'} for ref in resolved]
        except ValueError as error:
            issues.append('Answer key: ' + str(error))
        exception = _selected(db, QuestionMaterialScopeVersion, QuestionMaterialScopeVersion.question_id, question.id)
        if exception:
            try:
                if exception.status == 'approved' and exception.scope_sha256 != materials.scope_hash(exception):
                    raise ValueError('Approved source exception changed; create a new draft before approval.')
                materials.validate_bindings(db, question,
                    MaterialScopeRequest(mode=exception.mode, bindings=exception.bindings), rubric)
            except ValueError as error:
                issues.append('Source exception: ' + str(error))
        scope = exception if exception and exception.mode != 'inherit' else default
        source_warnings = []
        if not scope or scope.mode == 'disabled':
            source_warnings.append('No course-material retrieval for this question; key and rubric still apply.')
        routing = db.query(QuestionGradingPolicy).filter(QuestionGradingPolicy.question_id == question.id).first()
        rows.append(dict(question_id=question.id, question_number=question.question_number, language=question.language,
            grading_input=routing.mode if routing else 'adaptive',
            question_text=question.question_text, max_score=float(question.max_score),
            rubric_version_id=version.id if version else None, rubric_status=version.status if version else 'legacy',
            rubric=rubric, answer_key=reference, source_exception=_scope(exception),
            sources=_scope(scope), source_references=_labels(db, scope, exam), errors=issues, warnings=source_warnings))
        errors.extend(f'Question {question.question_number}: {issue}' for issue in issues)
    # Content, not just IDs: edits to the same draft invalidate a prior review.
    manifest = dict(exam_id=exam.id, course_id=exam.course_id, title=exam.title, assessment_sources=_scope(default), questions=rows)
    token = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=str, allow_nan=False).encode()).hexdigest()
    pending = sum(r['rubric_status'] == 'draft' for r in rows) + sum(
        r['answer_key']['status'] == 'draft' for r in rows) + sum(
        bool(r['source_exception'] and r['source_exception']['status'] == 'draft') for r in rows) + int(bool(default and default.status == 'draft'))
    return dict(**manifest, review_token=token, errors=errors, warnings=warnings,
        pending_count=pending, can_approve=bool(rows) and not errors, total_marks=sum(r['max_score'] for r in rows),
        paper_total_marks=sum(r['max_score'] for r in rows if (r['rubric'].get('policy') or {}).get('assessment_scope') != 'external'))


def approve_guide(db, exam, user, expected_token):
    # Lock foundations before recomputing the review. The router owns commit.
    db.query(type(exam)).filter(type(exam).id == exam.id).with_for_update().one()
    db.query(Question).filter(Question.exam_id == exam.id).with_for_update().all()
    question_ids = [q.id for q in db.query(Question).filter(Question.exam_id == exam.id).all()]
    for model in (RubricVersion, AnswerKeyVersion, QuestionMaterialScopeVersion):
        db.query(model).filter(model.question_id.in_(question_ids)).with_for_update().all()
    db.query(AssessmentMaterialScopeVersion).filter(AssessmentMaterialScopeVersion.exam_id == exam.id).with_for_update().all()
    review = review_guide(db, exam)
    if review['review_token'] != expected_token:
        raise ValueError('The guide changed after review. Refresh and review the current saved definitions before approval.')
    if review['errors']:
        raise ValueError('Resolve the guide checks before approval: ' + ' '.join(review['errors']))
    changed = []
    for row in review['questions']:
        question = db.get(Question, row['question_id'])
        if row['rubric_status'] == 'draft':
            approve_rubric_version(version=db.get(RubricVersion, row['rubric_version_id']),
                db=db, approved_by=user.id, commit=False)
            changed.append(row['rubric_version_id'])
        if row['answer_key']['status'] == 'draft':
            keys.approve_key(question, db.get(AnswerKeyVersion, row['answer_key']['id']), db, user)
            changed.append(row['answer_key']['id'])
        exception = row['source_exception']
        if exception and exception['status'] == 'draft':
            materials.approve_scope(db, question, db.get(QuestionMaterialScopeVersion, exception['id']), user, row['rubric'])
            changed.append(exception['id'])
    default = review['assessment_sources']
    if default and default['status'] == 'draft':
        sources.approve_default(db, exam, db.get(AssessmentMaterialScopeVersion, default['id']), user)
        changed.append(default['id'])
    return changed
