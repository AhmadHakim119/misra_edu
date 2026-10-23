import hashlib
import json

from models import Answer, AuditLog, GradingRun, ReviewLabel


def review_token(answer):
    """Version of the displayed decision, including reopening and AI-run changes."""
    raw = answer.grading_raw_response or {}
    state = {key: getattr(answer, key, None) for key in
             ('id', 'review_status', 'teacher_notes', 'needs_review')}
    for key in ('score', 'max_score', 'teacher_override_score'):
        value = getattr(answer, key, None)
        state[key] = float(value) if value is not None else None
    state['reviewed_at'] = answer.reviewed_at.replace(tzinfo=None).isoformat() if answer.reviewed_at else None
    state['run'] = {key: raw.get(key) for key in
                    ('grading_run_id', 'mode', 'applied_review_label_id', 'review_reopened', 'guide_review_required')}
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


def pending_reopening(answer):
    raw = getattr(answer, 'grading_raw_response', None) or {}
    return raw.get('guide_review_required') or raw.get('review_reopened')


def operational_run(db, answer):
    raw = answer.grading_raw_response or {}
    run = db.query(GradingRun).filter(GradingRun.id == raw.get('grading_run_id'), GradingRun.answer_id == answer.id).first() if raw.get('grading_run_id') else None
    if run:
        return run
    query = db.query(GradingRun).filter(GradingRun.answer_id == answer.id)
    if raw.get('mode') in {'text_only','image_text'}:
        query = query.filter(GradingRun.mode == raw['mode'])
    return query.order_by(GradingRun.created_at.desc(), GradingRun.id.desc()).first()


def latest_operational_label(db, answer):
    run = operational_run(db, answer)
    labels = db.query(ReviewLabel).filter(ReviewLabel.answer_id == answer.id,
        ReviewLabel.grading_run_id == (run.id if run else None)).order_by(ReviewLabel.created_at.desc(), ReviewLabel.id.desc()).all()
    applied_id = (answer.grading_raw_response or {}).get('applied_review_label_id')
    if applied_id:
        return next((label for label in labels if label.id == applied_id), None)
    # Older records can be recovered only when the audit explicitly identifies
    # an applied label. Never infer authority from an evaluation label's recency.
    events = db.query(AuditLog).filter(AuditLog.entity_type == 'answer',
        AuditLog.entity_id == answer.id, AuditLog.institution_id == answer.institution_id,
        AuditLog.action.in_(('grade_approved', 'grade_overridden'))).all()
    applied = {(event.extra_data or {}).get('details', {}).get('review_label_id')
               for event in events if (event.extra_data or {}).get('details', {}).get('apply_as_current') is True}
    # Follow supersession through evaluation-only labels, without displaying them.
    by_id = {label.id: label for label in labels}
    candidates = set(applied) & set(by_id)
    for label in labels:
        if label.id not in applied:
            continue
        previous = label.supersedes_label_id
        seen = set()
        while previous in by_id and previous not in seen:
            seen.add(previous)
            candidates.discard(previous)
            previous = by_id[previous].supersedes_label_id
    return by_id[next(iter(candidates))] if len(candidates) == 1 else None


def resolved_review_status(answer: Answer) -> str | None:
    """Recover the authoritative human state, including older inconsistent rows."""
    if pending_reopening(answer):
        return None
    if answer.teacher_override_score is not None:
        return "overridden"
    if answer.review_status == "approved" or answer.reviewed_at is not None:
        return "approved"
    return None
