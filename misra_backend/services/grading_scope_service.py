"""Approved scope, independent of OCR guesses or model marking decisions."""


def is_removed_question(question) -> bool:
    value=(question.rubric_json or {}).get('question_lifecycle')
    return isinstance(value,dict) and value.get('status') == 'removed'


def active_questions(questions):
    return [question for question in questions if not is_removed_question(question)]


def is_paper_question(question) -> bool:
    return not is_removed_question(question) and not is_external_question(question)


def is_external_question(question) -> bool:
    # rubric_json is the approved compatibility copy, updated atomically on approval.
    rubric = question.rubric_json or {}
    return (rubric.get("policy") or {}).get("assessment_scope", "paper") == "external"


def scope_summary(questions) -> dict:
    removed = [q for q in questions if is_removed_question(q)]
    questions = active_questions(questions)
    external = [q for q in questions if is_external_question(q)]
    paper = [q for q in questions if not is_external_question(q)]
    return {
        "kind": "paper_only" if external else "full_assessment",
        "paper_question_count": len(paper),
        "paper_max_score": sum(float(q.max_score) for q in paper),
        "external_max_score": sum(float(q.max_score) for q in external),
        "external_question_ids": [q.id for q in external],
        "external_question_numbers": [q.question_number for q in external],
        "removed_question_ids": [q.id for q in removed],
        "removed_question_count": len(removed),
        "removed_questions": [{"id":q.id,"number":q.question_number} for q in removed],
    }
