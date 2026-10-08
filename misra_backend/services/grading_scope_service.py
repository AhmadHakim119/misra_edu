"""Approved scope, independent of OCR guesses or model marking decisions."""


def is_external_question(question) -> bool:
    # rubric_json is the approved compatibility copy, updated atomically on approval.
    rubric = question.rubric_json or {}
    return (rubric.get("policy") or {}).get("assessment_scope", "paper") == "external"


def scope_summary(questions) -> dict:
    external = [q for q in questions if is_external_question(q)]
    paper = [q for q in questions if not is_external_question(q)]
    return {
        "kind": "paper_only" if external else "full_assessment",
        "paper_question_count": len(paper),
        "paper_max_score": sum(float(q.max_score) for q in paper),
        "external_max_score": sum(float(q.max_score) for q in external),
        "external_question_ids": [q.id for q in external],
        "external_question_numbers": [q.question_number for q in external],
    }
