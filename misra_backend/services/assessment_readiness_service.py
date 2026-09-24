"""Deterministic assessment checks; never a prediction of grading accuracy."""
import math
import re

from models import AnswerKeyVersion, Question, QuestionGradingPolicy, RubricVersion


VISUAL_EVIDENCE_PATTERNS = (
    r"\bdiagrams?\b", r"\bgraphs?\b", r"\bcharts?\b", r"\bfigures?\b",
    r"\bdraw(?:n|ing)?\b", r"\bsketch(?:es|ed|ing)?\b", r"\bschemas?\b",
    r"\bvisual\b", r"\bnotation\b", r"\bunderlin(?:e|ed|ing)\b", r"\barrows?\b",
    r"\bcardinalit(?:y|ies)\b", r"\bparticipation\b",
    r"\badjacency\s+matrix\b",
)


def requires_visual_evidence(question_text, rubric):
    """Detect explicit visual requirements; this is routing metadata, not semantics."""
    searchable = [str(question_text or "")]
    if isinstance(rubric, dict):
        for criterion in rubric.get("criteria", []):
            if not isinstance(criterion, dict):
                continue
            searchable.extend([
                str(criterion.get("title") or ""),
                str(criterion.get("description") or ""),
                " ".join(map(str, criterion.get("required_evidence") or [])),
            ])
    text = " ".join(searchable).lower()
    return any(re.search(pattern, text) for pattern in VISUAL_EVIDENCE_PATTERNS)


def _key_value(key, name, default=None):
    if key is None:
        return default
    if isinstance(key, dict):
        return key.get(name, default)
    return getattr(key, name, default)


def _issue(code, message):
    return {"code": code, "message": message}


def definition_consistency(question, rubric, answer_key=None, routing_policy=None):
    """Return structural blockers and deterministic advisory conflicts.

    These checks compare explicit fields only. They never claim that the prose in
    a question, reference answer, or criterion is academically correct.
    """
    blocking = []
    advisory = []
    rubric = rubric if isinstance(rubric, dict) else {}
    policy = rubric.get("policy") if isinstance(rubric.get("policy"), dict) else {}
    mode = _key_value(answer_key, "mode")
    reference_text = str(_key_value(answer_key, "reference_text", "") or "").strip()
    alternatives = list(_key_value(answer_key, "alternatives",
                                   _key_value(answer_key, "acceptable_answers", [])) or [])
    documents = list(_key_value(answer_key, "document_refs", []) or [])
    legacy_text = str(rubric.get("reference_context") or "").strip()
    legacy_alternatives = list(rubric.get("acceptable_answers") or [])

    if answer_key is not None and mode not in {"reference", "no_fixed_answer"}:
        blocking.append(_issue(
            "invalid_answer_key_mode",
            "The approved answer key has an unsupported mode. Approve a valid key version.",
        ))
    if mode == "no_fixed_answer" and (reference_text or alternatives or documents):
        blocking.append(_issue(
            "no_fixed_answer_contains_reference",
            "A no-fixed-answer key cannot contain reference answers or reference documents.",
        ))
    if mode == "reference" and not (reference_text or alternatives or documents):
        advisory.append(_issue(
            "reference_key_has_no_content",
            "The approved reference key has no text, alternatives, or selected document pages.",
        ))

    if answer_key is not None and mode == "no_fixed_answer" and (legacy_text or legacy_alternatives):
        advisory.append(_issue(
            "no_fixed_answer_legacy_reference_conflict",
            "The approved key says no fixed answer, while the rubric still contains a legacy reference. The approved key takes precedence.",
        ))
    elif answer_key is not None and mode == "reference" and (legacy_text or legacy_alternatives):
        if reference_text != legacy_text or alternatives != legacy_alternatives:
            advisory.append(_issue(
                "approved_key_legacy_reference_mismatch",
                "The approved answer key differs from the rubric's legacy reference fields. The approved key takes precedence.",
            ))

    criteria = [item for item in rubric.get("criteria", []) if isinstance(item, dict)]
    if policy.get("alternative_methods_allowed") is False and any(
        item.get("alternative_methods") for item in criteria
    ):
        advisory.append(_issue(
            "criterion_alternatives_policy_conflict",
            "A criterion lists valid alternative methods, but the rubric policy disables alternative methods. The criterion-specific alternatives require instructor review.",
        ))
    if policy.get("evidence_requirement") == "final_answer_only" and any(
        item.get("required_evidence") for item in criteria
    ):
        advisory.append(_issue(
            "criterion_evidence_policy_conflict",
            "A criterion requires specific evidence, but the rubric policy says final answer only. Criterion requirements take precedence and should be confirmed.",
        ))

    visual_required = requires_visual_evidence(question.question_text, rubric)
    routing_mode = (
        routing_policy.mode
        if routing_policy is not None and getattr(routing_policy, "enabled", True)
        else "adaptive"
    )
    if visual_required and routing_mode == "text_only":
        advisory.append(_issue(
            "visual_requirement_text_only_policy",
            "The question or rubric explicitly requires visual evidence, but its routing policy is text only.",
        ))

    return {
        "blocking_errors": blocking,
        "advisories": advisory,
        "visual_evidence_required": visual_required,
    }


def definition_errors(question, rubric):
    """Shared by setup preflight and grading, including legacy rubric documents."""
    errors = []
    if not (question.question_text or '').strip():
        errors.append('Add the question text and any context students need.')
    if not isinstance(rubric, dict):
        return errors + ['The rubric is not a valid document.']
    try:
        maximum = float(rubric['max_score'])
        question_maximum = float(question.max_score)
        criteria = rubric['criteria']
        points = [float(c['points']) for c in criteria]
        identifiers = [c['id'] for c in criteria]
        if not criteria or not all(isinstance(i, str) and i.strip() for i in identifiers):
            raise ValueError()
        if len(set(identifiers)) != len(identifiers):
            errors.append('Give each criterion a unique identifier.')
        if not all(math.isfinite(v) and v > 0 for v in [maximum, question_maximum, *points]):
            raise ValueError()
        if abs(maximum - question_maximum) > .01:
            errors.append('Question marks and rubric marks do not match.')
        if abs(sum(points) - maximum) > .01:
            errors.append('Criterion marks do not add up to the question total.')
        if any(not str(c.get('description') or '').strip() for c in criteria):
            errors.append('Explain what earns credit for every criterion.')
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append('Provide valid positive marks and at least one named criterion.')
    return errors


def assessment_readiness(db, exam_id):
    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(
        Question.order_index, Question.question_number).all()
    # Bulk reads keep a large assessment from generating one query per question.
    all_versions = db.query(RubricVersion).join(
        Question, RubricVersion.question_id == Question.id).filter(Question.exam_id == exam_id).all()
    versions = {v.id: v for v in all_versions}
    versioned_questions = {v.question_id for v in all_versions}
    policies = {p.question_id: p for p in db.query(QuestionGradingPolicy).join(
        Question, QuestionGradingPolicy.question_id == Question.id).filter(Question.exam_id == exam_id).all()}
    keys = {k.question_id: k for k in db.query(AnswerKeyVersion).join(
        Question, AnswerKeyVersion.question_id == Question.id).filter(
        Question.exam_id == exam_id, AnswerKeyVersion.status == 'approved').order_by(
        AnswerKeyVersion.version_number).all()}
    rows = []
    numbers = [q.question_number.strip().casefold() for q in questions]
    for q in questions:
        version = versions.get(q.active_rubric_version_id)
        approved = bool(version and version.question_id == q.id and version.status == 'approved')
        legacy = q.id not in versioned_questions
        rubric = version.rubric_json if approved else q.rubric_json if legacy else {}
        definition_ready = approved or legacy
        rubric_errors = (
            definition_errors(q, rubric)
            if definition_ready
            else ['Review and approve a rubric for this question.']
        )
        errors = list(rubric_errors)
        rubric = rubric if isinstance(rubric, dict) else {}
        if not q.question_number.strip() or numbers.count(q.question_number.strip().casefold()) > 1:
            errors.append('Use a non-empty, unique question number.')
        reference = bool(isinstance(rubric, dict) and (
            str(rubric.get('reference_context') or '').strip() or
            bool(rubric.get('acceptable_answers'))))
        warnings = []
        key = keys.get(q.id)
        if key and key.document_refs:
            # Approval captured the exact setup document and hash. Re-check it
            # during upload preflight so a removed or replaced file cannot turn
            # into an untraceable grading reference later.
            try:
                from services.answer_key_service import resolve_document_refs
                resolve_document_refs(q, key.document_refs, db, verify_hash=True)
            except ValueError as error:
                errors.append(str(error))
        if key:
            reference = key.mode == 'reference'
        if approved and not reference and not (key and key.mode == 'no_fixed_answer'):
            warnings.append('No reference answer recorded. Confirm that the criteria are sufficient; open-ended questions may not need a fixed answer.')
        policy = policies.get(q.id)
        mode = policy.mode if policy and policy.enabled else 'disabled' if policy else 'adaptive'
        if policy and not policy.enabled:
            warnings.append('Saved routing policy is disabled. Review the routing setting before grading.')
        consistency = definition_consistency(q, rubric, key, policy)
        errors.extend(issue['message'] for issue in consistency['blocking_errors'])
        warnings.extend(issue['message'] for issue in consistency['advisories'])
        rows.append(dict(question_id=q.id, question_number=q.question_number,
            max_score=float(q.max_score), approved=approved,
            rubric_source='versioned' if approved else 'legacy' if legacy else 'unapproved',
            definition_ready=definition_ready and not rubric_errors,
            rubric_version=version.version_number if approved else None,
            answer_key_version=key.version_number if key else None,
            answer_key_mode=key.mode if key else None,
            reference_recorded=reference, grading_approach=(rubric.get('policy') if isinstance(rubric.get('policy'), dict) else {}).get('grading_approach', 'balanced'),
            evidence_mode=mode, errors=errors, warnings=warnings,
            definition_consistency=consistency))
    pending = [r['question_number'] for r in rows if r['errors']]
    ready = bool(rows) and not pending
    return dict(ready=ready, question_count=len(rows), approved_count=sum(r['approved'] for r in rows),
        total_points=round(sum(r['max_score'] for r in rows), 2), pending_questions=pending,
        warning_count=sum(len(r['warnings']) for r in rows), questions=rows,
        message=('Add questions and approve their rubrics first.' if not rows else
                 'Resolve the question and rubric checks before uploading student answers.' if pending else
                 'Setup checks passed. Ready for student answers.'))
