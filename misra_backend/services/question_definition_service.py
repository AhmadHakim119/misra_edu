"""Question corrections share rubric versions and whole-guide approval.

Current question IDs and historical input packages never change. The previous
definition is retained in the correction version, including pre-versioned text.
"""
from schemas.question_definition import QuestionDefinitionCorrection


def current_definition(question):
    return dict(question_number=question.question_number,
                question_text=question.question_text or '', language=question.language)


def correction_document(raw):
    return QuestionDefinitionCorrection.model_validate(raw).model_dump()


def proposed_definition(question, rubric):
    value = current_definition(question)
    raw = (rubric or {}).get('question_definition')
    if not raw:
        return value
    correction = correction_document(raw)
    proposed = {key: correction[key] for key in value}
    if proposed != value and correction['previous'] != value:
        raise ValueError('Question details changed after this draft was opened. Reload and review the correction.')
    return proposed


def validate_number_available(question, proposed, db):
    from models import Question
    others = db.query(Question).filter(Question.exam_id == question.exam_id,
        Question.institution_id == question.institution_id, Question.id != question.id).all()
    from services.grading_scope_service import active_questions
    others = active_questions(others)
    if any(other.question_number.strip().casefold() == proposed['question_number'].strip().casefold() for other in others):
        raise ValueError('Question number is already used. Correct all affected numbers and approve the whole guide together.')


def apply_definition(question, rubric, db, *, batch_validated=False):
    proposed = proposed_definition(question, rubric)
    if not batch_validated:
        validate_number_available(question, proposed, db)
    for key, value in proposed.items():
        setattr(question, key, value)
