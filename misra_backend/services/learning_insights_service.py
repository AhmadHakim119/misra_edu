"""Descriptive teaching feedback from recorded grades, never new AI judgments."""
from collections import defaultdict
import hashlib
import json
import math

from models import Answer, Question, Submission
from services.grading_scope_service import is_external_question


def finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def learning_insights(db, exam):
    questions = db.query(Question).filter(Question.exam_id == exam.id,
        Question.institution_id == exam.institution_id).order_by(Question.order_index).all()
    papers = db.query(Submission).filter(Submission.exam_id == exam.id,
        Submission.institution_id == exam.institution_id).all()
    rows = db.query(Answer).join(Submission, Answer.submission_id == Submission.id).filter(
        Submission.exam_id == exam.id, Submission.institution_id == exam.institution_id,
        Answer.institution_id == exam.institution_id).all()
    by_question = defaultdict(list)
    for answer in rows:
        by_question[answer.question_id].append(answer)
    output = []
    for question in questions:
        if is_external_question(question):
            continue
        answers = by_question[question.id]
        valid, reviewed, ratios, grounded, groups, excluded = 0, 0, [], 0, {}, 0
        for answer in answers:
            score = finite(answer.teacher_override_score if answer.teacher_override_score is not None else answer.score)
            maximum = finite(answer.max_score)
            if score is None or maximum is None or maximum <= 0 or not 0 <= score <= maximum:
                continue
            valid += 1
            reviewed += bool(answer.needs_review and answer.review_status not in {'approved', 'overridden'})
            ratios.append(score / maximum)
            package = (answer.grading_raw_response or {}).get('grading_package') or {}
            refs = (package.get('course_references') or {}).get('passages') or []
            definitions = {c['id']: c for c in (package.get('rubric') or {}).get('criteria', []) if 'id' in c}
            scores = answer.criteria_scores if isinstance(answer.criteria_scores, list) else []
            grounded += bool(scores) and all(any(p.get('id') in (c.get('reference_refs') or []) and
                c.get('criterion_id') in p.get('criterion_ids', []) for p in refs) for c in scores)
            # Total-only overrides must not masquerade as instructor criterion marks.
            if answer.teacher_override_score is not None:
                excluded += 1
                continue
            signature = package.get('rubric_version_id') or hashlib.sha256(json.dumps(
                package.get('rubric') or {}, sort_keys=True).encode()).hexdigest()[:12]
            for criterion in scores:
                cid = criterion.get('criterion_id')
                definition = definitions.get(cid)
                earned, cap = finite(criterion.get('points_earned')), finite(criterion.get('max_points'))
                if not definition or earned is None or cap is None or cap <= 0 or not 0 <= earned <= cap:
                    continue
                key = (signature, cid)
                group = groups.setdefault(key, dict(criterion_id=cid, rubric_version_id=signature,
                    title=definition.get('title') or definition.get('description') or cid,
                    description=definition.get('full_credit_conditions') or definition.get('description') or '',
                    assessed_count=0, full_credit_count=0, partial_credit_count=0, zero_credit_count=0,
                    sum_ratio=0, source_pages={}))
                group['assessed_count'] += 1
                group['sum_ratio'] += earned / cap
                category = 'full_credit_count' if abs(earned-cap) < .005 else 'zero_credit_count' if earned == 0 else 'partial_credit_count'
                group[category] += 1
                for passage in refs:
                    if passage.get('id') in (criterion.get('reference_refs') or []):
                        identity = (passage.get('material_version_id'), passage.get('page_index'))
                        group['source_pages'][identity] = {k: passage.get(k) for k in
                            ('title', 'material_id', 'material_version_id', 'material_version_number', 'page_index')}
        criteria = []
        for group in groups.values():
            group['average_percent'] = round(100 * group.pop('sum_ratio') / group['assessed_count'], 1)
            group['source_pages'] = list(group['source_pages'].values())
            criteria.append(group)
        output.append(dict(question_id=question.id, question_number=question.question_number,
            question_text=question.question_text, graded_count=valid, awaiting_review_count=reviewed,
            average_percent=round(100 * sum(ratios)/len(ratios), 1) if ratios else None,
            course_grounded_count=grounded, criterion_override_excluded_count=excluded,
            criteria=sorted(criteria, key=lambda c: (c['average_percent'], c['title']))))
    return dict(exam_id=exam.id, submission_count=len(papers), questions=output,
        confidence_status='uncalibrated', notes=[
            'Counts describe recorded grades, not proven student misconceptions or grading accuracy.',
            'Missing or ungraded answers are not counted as zero. External practical questions are excluded.',
            'Criterion counts are AI observations, separated by saved rubric version. Total-only overrides are excluded.',
            'Lecture citations locate evidence; they do not prove the academic judgment is correct.'])
